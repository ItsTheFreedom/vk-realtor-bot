import logging
import sys
from logging.handlers import RotatingFileHandler
from config import Config


def setup_logger(name: str = "RealtorBot") -> logging.Logger:
    """Настройка системы логирования диалогов и ошибок в отдельные файлы и консоль."""
    Config.ensure_dirs()
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Предотвращаем добавление дублирующих хэндлеров при повторном вызове
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Хэндлер для общего лога (все диалоги, переходы, отладка)
    bot_log_path = Config.LOGS_DIR / "bot.log"
    file_handler = RotatingFileHandler(
        bot_log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 2. Хэндлер только для ошибок
    errors_log_path = Config.LOGS_DIR / "errors.log"
    error_handler = RotatingFileHandler(
        errors_log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    # 3. Консольный хэндлер (для удобной разработки в PyCharm)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# Глобальный экземпляр логгера для импорта в других модулях
bot_logger = setup_logger()
