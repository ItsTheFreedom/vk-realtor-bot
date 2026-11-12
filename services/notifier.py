import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import Config
from core.logger import bot_logger


class Notifier:
    """Сервис для отправки e-mail уведомлений администратору в случае окончательных сбоев интеграции."""

    @staticmethod
    def send_admin_alert(subject: str, message_body: str) -> bool:
        """
        Отправляет тревожное письмо администратору на адрес из конфигурации.
        
        :param subject: Тема письма
        :param message_body: Текст ошибки / не сработавшего payload
        :return: True при успешной отправке или логировании, False при ошибке
        """
        bot_logger.error(f"[ALARM FOR ADMIN] {subject} | {message_body}")

        # Проверяем наличие настроенных параметров SMTP
        if not Config.SMTP_USER or not Config.SMTP_PASSWORD:
            bot_logger.warning("SMTP_USER или SMTP_PASSWORD не настроены в .env. Письмо администратору зафиксировано только в логах.")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = Config.SMTP_USER
            msg["To"] = Config.ADMIN_EMAIL
            msg["Subject"] = f"[VK BOT ERROR] {subject}"

            msg.attach(MIMEText(message_body, "plain", "utf-8"))

            with smtplib.SMTP_SSL(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=10.0) as server:
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.send_message(msg)

            bot_logger.info(f"Уведомление об ошибке успешно отправлено администратору на {Config.ADMIN_EMAIL}")
            return True
        except Exception as e:
            bot_logger.error(f"Не удалось отправить e-mail уведомление администратору: {e}", exc_info=True)
            return False


notifier = Notifier()
