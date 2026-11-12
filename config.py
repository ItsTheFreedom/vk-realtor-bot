import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Определяем корневую директорию проекта
BASE_DIR = Path(__file__).resolve().parent

# Загружаем переменные окружения из .env (если файл существует)
load_dotenv(BASE_DIR / ".env")


class Config:
    """Класс конфигурации приложения, загружающий параметры из переменных окружения."""
    BASE_DIR: Path = BASE_DIR

    # ВКонтакте
    VK_GROUP_TOKEN: str = os.getenv("VK_GROUP_TOKEN", "")
    VK_GROUP_ID: int = int(re.sub(r"\D", "", os.getenv("VK_GROUP_ID", "0")) or 0)

    # Битрикс24
    BITRIX_WEBHOOK_URL: str = os.getenv("BITRIX_WEBHOOK_URL", "")

    # Яндекс Таблицы / Документы
    YANDEX_OAUTH_TOKEN: str = os.getenv("YANDEX_OAUTH_TOKEN", "")
    YANDEX_SHEET_PATH: str = os.getenv("YANDEX_SHEET_PATH", "/Таблицы/Фиксация_клиентов_СТС_Групп.xlsx")
    LOCAL_BACKUP_SHEET: Path = BASE_DIR / os.getenv("LOCAL_BACKUP_SHEET", "realtor_clients_backup.csv")

    # Уведомления администратору
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@stc-group.ru")
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.yandex.ru")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")

    # Хранилище сессий и логи
    DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "sessions.db")
    LOGS_DIR: Path = BASE_DIR / os.getenv("LOGS_DIR", "logs")
    SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "24"))

    @classmethod
    def ensure_dirs(cls):
        """Создание необходимых служебных директорий (логи и т.д.)."""
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)


# Инициализируем директории при импорте
Config.ensure_dirs()
