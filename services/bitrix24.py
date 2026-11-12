import datetime
import threading
import time
import requests
from typing import Tuple, Dict, Any, List
from config import Config
from core.logger import bot_logger
from services.notifier import notifier


class Bitrix24Service:
    """
    Сервис для работы с REST API Битрикс24 (метод crm.lead.add).
    Реализует формирование лида по ТЗ №1, а также механизм повторных попыток
    при сбоях (через 5 минут до 3 раз) в фоновом потоке.
    """

    def __init__(self, retry_delay_seconds: int = 300):
        self.retry_delay_seconds = retry_delay_seconds
        self._retry_queue: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._worker_thread = threading.Thread(target=self._retry_worker_loop, daemon=True)
        self._worker_thread.start()

    def build_lead_payload(self, realtor_fio: str, realtor_agency: str, client_fio: str, client_phone: str) -> Dict[str, Any]:
        """Формирует payload в строгом соответствии с пунктом 3.4 ТЗ."""
        now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        agency_str = realtor_agency if realtor_agency and realtor_agency.lower() != "нет" else "Нет"
        
        return {
            "fields": {
                "TITLE": f"Клиент от риэлтора {realtor_fio}",
                "NAME": client_fio,
                "PHONE": [{"VALUE": client_phone, "VALUE_TYPE": "WORK"}],
                "COMMENTS": f"Агентство: {agency_str}. Зафиксирован через бот {now_str}"
            }
        }

    def _send_request(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """Отправляет HTTP POST запрос к входящему вебхуку Битрикс24."""
        webhook_url = Config.BITRIX_WEBHOOK_URL.strip()
        if not webhook_url or "your_domain.bitrix24.ru" in webhook_url:
            bot_logger.warning("BITRIX_WEBHOOK_URL не настроен. Симуляция сбоя API для проверки логики очереди или тестового режима.")
            return False, "BITRIX_WEBHOOK_URL не задан или содержит шаблон"

        # Очищаем URL от возможных хвостов методов (например, если в .env указан profile.json или crm.lead.add)
        base_url = webhook_url.rstrip("/")
        for suffix in [".json", "/profile.json", "/profile", "/crm.lead.add.json", "/crm.lead.add"]:
            if base_url.endswith(suffix):
                base_url = base_url[:-len(suffix)].rstrip("/")
        endpoint_url = f"{base_url}/crm.lead.add.json"

        try:
            bot_logger.info(f"Отправка запроса в Битрикс24: {endpoint_url} | Payload: {payload}")
            response = requests.post(endpoint_url, json=payload, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    lead_id = str(data["result"])
                    bot_logger.info(f"Лид успешно создан в Битрикс24. ID лида: {lead_id}")
                    return True, lead_id
                elif "error_description" in data:
                    err_msg = data["error_description"]
                    bot_logger.error(f"Ошибка API Битрикс24: {err_msg}")
                    return False, err_msg
            return False, f"HTTP {response.status_code}: {response.text}"
        except Exception as e:
            bot_logger.error(f"Сбой сети или исключение при запросе к Битрикс24: {e}", exc_info=True)
            return False, str(e)

    def create_lead(self, realtor_fio: str, realtor_agency: str, client_fio: str, client_phone: str) -> Tuple[bool, str]:
        """
        Основной метод создания лида. В случае успеха возвращает (True, lead_id).
        В случае ошибки ставит задачу в очередь повторов (до 3 раз через 5 минут) и возвращает (False, error).
        """
        payload = self.build_lead_payload(realtor_fio, realtor_agency, client_fio, client_phone)
        success, result_or_error = self._send_request(payload)

        if not success:
            bot_logger.warning(f"Первая попытка создания лида не удалась ({result_or_error}). Добавление в очередь повторных попыток.")
            self._add_to_retry_queue(payload, attempt=1, last_error=result_or_error)

        return success, result_or_error

    def _add_to_retry_queue(self, payload: Dict[str, Any], attempt: int, last_error: str):
        """Добавляет задачу на повторную отправку в фоновую очередь."""
        next_try_time = time.time() + self.retry_delay_seconds
        with self._lock:
            self._retry_queue.append({
                "payload": payload,
                "attempt": attempt,
                "next_try_time": next_try_time,
                "last_error": last_error
            })

    def _retry_worker_loop(self):
        """Фоновый цикл для обработки задач в очереди повторных попыток."""
        while True:
            try:
                time.sleep(5.0)  # Проверка очереди каждые 5 секунд
                now = time.time()
                tasks_to_process = []

                with self._lock:
                    remaining_queue = []
                    for task in self._retry_queue:
                        if now >= task["next_try_time"]:
                            tasks_to_process.append(task)
                        else:
                            remaining_queue.append(task)
                    self._retry_queue = remaining_queue

                for task in tasks_to_process:
                    payload = task["payload"]
                    attempt = task["attempt"] + 1
                    bot_logger.info(f"Попытка #{attempt} повторной отправки лида в Битрикс24...")
                    
                    success, result_or_error = self._send_request(payload)
                    if success:
                        bot_logger.info(f"Лид успешно создан со {attempt}-й попытки. ID: {result_or_error}")
                    else:
                        bot_logger.warning(f"Попытка #{attempt} неудачна: {result_or_error}")
                        if attempt < 3:
                            # Ставим на следующую попытку через 5 минут
                            self._add_to_retry_queue(payload, attempt=attempt, last_error=result_or_error)
                        else:
                            # Окончательная неудача (3 попытки исчерпаны) — уведомляем администратора
                            err_msg = f"Не удалось создать лид в Битрикс24 после 3 попыток. Ошибка: {result_or_error}\nPayload: {payload}"
                            bot_logger.error(f"[FINAL BITRIX FAILURE] {err_msg}")
                            notifier.send_admin_alert("Сбой создания лида в Битрикс24 (3 попытки)", err_msg)
            except Exception as e:
                bot_logger.error(f"Ошибка в фоновом воркере Битрикс24: {e}", exc_info=True)
                time.sleep(10.0)


bitrix24 = Bitrix24Service()
