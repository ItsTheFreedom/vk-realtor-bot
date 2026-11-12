import csv
import datetime
import re
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from config import Config
from core.logger import bot_logger
from core.validator import validate_phone


class YandexSheetsService:
    """
    Сервис для работы с облачной таблицей (Яндекс Документы / Таблицы / Яндекс Диск REST API).
    Обеспечивает автоматическое проставление даты и времени и добавление строки с данными фиксации
    в конец таблицы, а также ведение локального резервного файла CSV.
    """

    HEADERS = [
        "Дата и время фиксации",
        "ФИО риэлтора",
        "Название агентства",
        "ФИО клиента",
        "Телефон клиента"
    ]

    PHONE_COLUMN = "Телефон клиента"

    def __init__(self):
        self._ensure_local_backup_initialized()

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Приводит телефон к формату +7XXXXXXXXXX для сравнения записей."""
        is_valid, normalized = validate_phone(phone)
        if is_valid:
            return normalized
        digits = re.sub(r"\D", "", phone or "")
        if len(digits) == 11 and digits[0] in ("7", "8"):
            return f"+7{digits[1:]}"
        if len(digits) == 10:
            return f"+7{digits}"
        return phone.strip()

    def _download_from_yandex_disk(self) -> bool:
        """Скачивает актуальную таблицу с Яндекс Диска в локальный файл перед проверкой дубликатов."""
        if not Config.YANDEX_OAUTH_TOKEN:
            return False

        try:
            headers = {"Authorization": f"OAuth {Config.YANDEX_OAUTH_TOKEN}"}
            api_url = "https://cloud-api.yandex.net/v1/disk/resources/download"
            resp = requests.get(
                api_url,
                headers=headers,
                params={"path": Config.YANDEX_SHEET_PATH},
                timeout=10.0,
            )
            if resp.status_code != 200:
                bot_logger.warning(
                    f"Не удалось получить ссылку на скачивание таблицы с Яндекс Диска: "
                    f"HTTP {resp.status_code} | {resp.text}"
                )
                return False

            download_url = resp.json().get("href")
            if not download_url:
                return False

            local_path = (
                Config.LOCAL_BACKUP_SHEET.with_suffix(".xlsx")
                if Config.YANDEX_SHEET_PATH.lower().endswith(".xlsx")
                else Config.LOCAL_BACKUP_SHEET
            )
            file_resp = requests.get(download_url, timeout=15.0)
            if file_resp.status_code != 200:
                bot_logger.warning(f"Ошибка скачивания таблицы с Яндекс Диска: HTTP {file_resp.status_code}")
                return False

            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(file_resp.content)
            bot_logger.info(f"Таблица успешно загружена с Яндекс Диска: {local_path}")
            return True
        except Exception as e:
            bot_logger.error(f"Ошибка загрузки таблицы с Яндекс Диска: {e}", exc_info=True)
            return False

    def _read_records_from_csv(self) -> List[Dict[str, str]]:
        records: List[Dict[str, str]] = []
        if not Config.LOCAL_BACKUP_SHEET.exists() or Config.LOCAL_BACKUP_SHEET.stat().st_size == 0:
            return records

        try:
            with open(Config.LOCAL_BACKUP_SHEET, mode="r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f, delimiter=";")
                for row in reader:
                    if row.get(self.PHONE_COLUMN):
                        records.append(dict(row))
        except Exception as e:
            bot_logger.error(f"Ошибка чтения локального CSV: {e}", exc_info=True)
        return records

    def _read_records_from_xlsx(self, xlsx_path: Path) -> List[Dict[str, str]]:
        records: List[Dict[str, str]] = []
        if not xlsx_path.exists() or xlsx_path.stat().st_size == 0:
            return records

        try:
            import openpyxl
            wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
            if len(rows) < 2:
                return records

            headers = [str(h).strip() if h is not None else "" for h in rows[0]]
            for row in rows[1:]:
                if not row:
                    continue
                record = {}
                for idx, header in enumerate(headers):
                    if header:
                        value = row[idx] if idx < len(row) else ""
                        record[header] = str(value).strip() if value is not None else ""
                if record.get(self.PHONE_COLUMN):
                    records.append(record)
        except Exception as e:
            bot_logger.error(f"Ошибка чтения локального XLSX ({xlsx_path}): {e}", exc_info=True)
        return records

    def get_all_records(self, refresh_from_cloud: bool = True) -> List[Dict[str, str]]:
        """
        Возвращает все записи из таблицы.
        При наличии OAuth-токена сначала пробует обновить локальную копию с Яндекс Диска.
        """
        if refresh_from_cloud:
            self._download_from_yandex_disk()

        xlsx_path = Config.LOCAL_BACKUP_SHEET.with_suffix(".xlsx")
        if xlsx_path.exists() and xlsx_path.stat().st_size > 0:
            records = self._read_records_from_xlsx(xlsx_path)
            if records:
                return records

        return self._read_records_from_csv()

    def find_client_by_phone(self, client_phone: str, refresh_from_cloud: bool = True) -> Optional[Dict[str, str]]:
        """
        Ищет клиента в таблице по номеру телефона.
        Возвращает первую найденную запись или None.
        """
        target_phone = self._normalize_phone(client_phone)
        if not target_phone:
            return None

        for record in self.get_all_records(refresh_from_cloud=refresh_from_cloud):
            record_phone = self._normalize_phone(record.get(self.PHONE_COLUMN, ""))
            if record_phone == target_phone:
                return record
        return None

    def is_client_registered_by_other_realtor(
        self,
        client_phone: str,
        current_realtor_fio: str,
        refresh_from_cloud: bool = True,
    ) -> Tuple[bool, Optional[Dict[str, str]]]:
        """
        Проверяет, зафиксирован ли клиент другим риэлтором.
        :return: (is_duplicate_by_other, existing_record)
        """
        existing = self.find_client_by_phone(client_phone, refresh_from_cloud=refresh_from_cloud)
        if not existing:
            return False, None

        existing_realtor = (existing.get("ФИО риэлтора") or "").strip().lower()
        current_realtor = (current_realtor_fio or "").strip().lower()
        if existing_realtor and existing_realtor != current_realtor:
            return True, existing
        return False, existing

    def _ensure_local_backup_initialized(self):
        """Проверяет существование локального файла резервной таблицы и создает его с заголовком при необходимости или если файл пуст."""
        try:
            if not Config.LOCAL_BACKUP_SHEET.exists() or Config.LOCAL_BACKUP_SHEET.stat().st_size == 0:
                with open(Config.LOCAL_BACKUP_SHEET, mode="w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f, delimiter=";")
                    writer.writerow(self.HEADERS)
                bot_logger.info(f"Локальный резервный файл таблицы создан с заголовком: {Config.LOCAL_BACKUP_SHEET}")
        except Exception as e:
            bot_logger.error(f"Ошибка инициализации локального файла резервной копии таблицы: {e}", exc_info=True)

    def add_record(self, realtor_fio: str, realtor_agency: str, client_fio: str, client_phone: str) -> Tuple[bool, str]:
        """
        Добавляет запись о клиенте в таблицу.
        Колонки:
        1. Дата и время фиксации (автоматически проставляется ботом).
        2. ФИО риэлтора.
        3. Название агентства.
        4. ФИО клиента.
        5. Телефон клиента.
        
        :return: Кортеж (success, message_or_error)
        """
        self._ensure_local_backup_initialized()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [now_str, realtor_fio, realtor_agency or "Нет", client_fio, client_phone]

        # 1. Сначала гарантированно сохраняем в локальную таблицу (CSV с поддержкой Excel)
        local_saved = False
        try:
            with open(Config.LOCAL_BACKUP_SHEET, mode="a", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(row)
            local_saved = True
            bot_logger.info(f"Запись успешно добавлена в локальную таблицу CSV: {row}")
        except Exception as e:
            bot_logger.error(f"Ошибка добавления записи в локальный CSV: {e}", exc_info=True)

        # 1.1. Создаем/обновляем также полноценный файл Excel (.xlsx) для идеальной совместимости с Яндекс Документами
        xlsx_path = Config.LOCAL_BACKUP_SHEET.with_suffix(".xlsx")
        try:
            import openpyxl
            if xlsx_path.exists() and xlsx_path.stat().st_size > 0:
                wb = openpyxl.load_workbook(xlsx_path)
                ws = wb.active
            else:
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Клиенты"
                ws.append(self.HEADERS)
            
            row_idx = ws.max_row + 1
            for col_idx, val in enumerate(row, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=str(val) if val is not None else "")
                cell.number_format = '@'
                
            # Автоподбор ширины колонок
            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 3, 15)
            wb.save(xlsx_path)
            bot_logger.info(f"Запись успешно добавлена в локальный файл Excel: {xlsx_path}")
        except Exception as e:
            bot_logger.error(f"Ошибка обновления локального файла Excel (.xlsx): {e}", exc_info=True)

        # 2. Попытка синхронизации / отправки через облачный API Яндекса (если задан токен)
        cloud_saved = False
        if Config.YANDEX_OAUTH_TOKEN:
            try:
                headers = {"Authorization": f"OAuth {Config.YANDEX_OAUTH_TOKEN}"}
                api_url = "https://cloud-api.yandex.net/v1/disk/resources/upload"
                params = {"path": Config.YANDEX_SHEET_PATH, "overwrite": "true"}
                resp = requests.get(api_url, headers=headers, params=params, timeout=10.0)
                if resp.status_code == 200:
                    upload_url = resp.json().get("href")
                    file_to_upload = xlsx_path if Config.YANDEX_SHEET_PATH.lower().endswith(".xlsx") and xlsx_path.exists() else Config.LOCAL_BACKUP_SHEET
                    if upload_url and file_to_upload.exists():
                        bot_logger.info(f"Начинается загрузка {file_to_upload.name} на Яндекс Диск по URL...")
                        with open(file_to_upload, "rb") as f:
                            put_resp = requests.put(upload_url, data=f, timeout=15.0)
                        if put_resp.status_code in (200, 201, 202):
                            cloud_saved = True
                            bot_logger.info(f"Таблица ({file_to_upload.name}) успешно синхронизирована с Яндекс Диском на путь {Config.YANDEX_SHEET_PATH}")
                        else:
                            bot_logger.warning(f"Яндекс Диск вернул неожиданный статус при PUT загрузке: HTTP {put_resp.status_code} | Ответ: {put_resp.text}")
                else:
                    bot_logger.warning(f"Не удалось получить ссылку для загрузки от Яндекс Диска: HTTP {resp.status_code} | Ответ: {resp.text}")
            except Exception as e:
                bot_logger.error(f"Ошибка синхронизации с облачным API Яндекс Таблиц: {e}", exc_info=True)

        if local_saved or cloud_saved:
            return True, "Запись сохранена в таблице"
        else:
            return False, "Не удалось сохранить запись ни в локальную, ни в облачную таблицу"


yandex_sheets = YandexSheetsService()
