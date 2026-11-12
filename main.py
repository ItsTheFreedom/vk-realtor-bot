import sys
import time
import requests
from config import Config
from core.logger import bot_logger
from bot.handler import message_handler

try:
    import vk_api
    from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
    from vk_api.utils import get_random_id
except ImportError:
    vk_api = None
    VkBotLongPoll = None
    VkBotEventType = None
    get_random_id = None


def upload_and_get_doc_attachments(vk, peer_id, doc_filenames):
    """
    Загружает файлы .docx через VK API и возвращает строку вложений вида 'doc{owner_id}_{id},...'.
    Если у токена нет прав (Scope 15), выводит понятное сообщение и возвращает None, чтобы диалог продолжался.
    """
    attachments = []
    titles_map = {
        "policy.docx": "Политика обработки персональных данных.docx",
        "consent.docx": "Согласие на обработку персональных данных.docx"
    }
    for filename in doc_filenames:
        file_path = Config.BASE_DIR / filename
        if not file_path.exists():
            bot_logger.warning(f"Файл вложения не найден: {file_path}")
            continue
        for attempt in range(3):
            try:
                upload_server = vk.docs.getMessagesUploadServer(peer_id=peer_id)
                upload_url = upload_server["upload_url"]
                with open(file_path, "rb") as f:
                    resp = requests.post(upload_url, files={"file": (filename, f)}, timeout=15).json()
                file_str = resp.get("file")
                if file_str:
                    display_title = titles_map.get(filename, filename)
                    saved = vk.docs.save(file=file_str, title=display_title)
                    doc = saved.get("doc") or saved.get("audio_message") or (saved[0] if isinstance(saved, list) and saved else None)
                    if doc and "owner_id" in doc and "id" in doc:
                        attachments.append(f"doc{doc['owner_id']}_{doc['id']}")
                        time.sleep(0.5)
                        break
            except vk_api.exceptions.ApiError as e:
                if e.code == 15:
                    bot_logger.error(
                        f"[ВНИМАНИЕ] Для прикрепления файла {filename} в чат у токена VK нет права 'Документы' (код 15). "
                        "Создайте новый ключ с галочкой 'Документы' в настройках сообщества VK и обновите .env!"
                    )
                    break
                else:
                    bot_logger.warning(f"Попытка {attempt+1}/3 сбоя VK API при загрузке {filename}: {e}")
                    time.sleep(1.0)
            except Exception as e:
                bot_logger.warning(f"Попытка {attempt+1}/3 сбоя сети при загрузке {filename}: {e}")
                time.sleep(1.0)
    return ",".join(attachments) if attachments else None


def start_cli_interactive_mode():
    """
    Интерактивный тестовый режим в терминале PyCharm (CLI),
    если токен ВКонтакте ещё не задан или передан флаг --cli.
    """
    bot_logger.info("===============================================================")
    bot_logger.info("Запуск в интерактивном консольном режиме (CLI Test Mode).")
    bot_logger.info("Для реальной работы с ВКонтакте укажите VK_GROUP_TOKEN и VK_GROUP_ID в .env")
    bot_logger.info("Команды: /reset — сброс сессии, /cancel — отмена, /exit — выход")
    bot_logger.info("===============================================================")

    test_user_id = 10001
    while True:
        try:
            user_input = input(f"\n[Вы / Риэлтор (ID:{test_user_id})]: ").strip()
            if user_input.lower() in ("/exit", "exit", "quit"):
                bot_logger.info("Завершение интерактивного режима CLI.")
                break

            reply_text, keyboard_json = message_handler.process_message(test_user_id, user_input)
            print(f"\n[Бот ВКонтакте]: {reply_text}")
            if keyboard_json and "buttons" in keyboard_json and len(keyboard_json) > 30:
                print(f"[Клавиатура ВКонтакте (JSON)]: {keyboard_json}")
        except (KeyboardInterrupt, EOFError):
            print("\nВыход из программы.")
            break
        except Exception as e:
            bot_logger.error(f"Ошибка при обработке ввода CLI: {e}", exc_info=True)


def start_vk_bot():
    """Запуск официального LongPoll бота для ВКонтакте."""
    token = Config.VK_GROUP_TOKEN.strip()
    group_id = Config.VK_GROUP_ID

    if not token or "your_vk_group_token" in token or not group_id:
        bot_logger.warning("Токен сообщества (VK_GROUP_TOKEN) или ID (VK_GROUP_ID) не заданы в .env.")
        bot_logger.info("Переключение в консольный режим тестирования...")
        start_cli_interactive_mode()
        return

    if not vk_api:
        bot_logger.error("Библиотека vk-api не установлена. Запустите: pip install -r requirements.txt")
        return

    bot_logger.info(f"Инициализация сессии ВКонтакте для группы ID: {group_id}")
    vk_session = vk_api.VkApi(token=token)
    vk = vk_session.get_api()
    longpoll = None

    while True:
        try:
            if longpoll is None:
                bot_logger.info(f"Подключение к VkBotLongPoll (сообщество {group_id})...")
                longpoll = VkBotLongPoll(vk_session, group_id)
                bot_logger.info("Бот успешно запущен и ожидает входящих сообщений (VkBotLongPoll)...")

            for event in longpoll.listen():
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.obj.message
                    # Защита от эха/зацикливания: игнорируем исходящие сообщения и сообщения от сообщества
                    if msg.get("out") == 1 or msg.get("from_id", 0) <= 0 or msg.get("from_id") == group_id:
                        continue
                    user_id = msg["from_id"]
                    text = msg.get("text", "")

                    # Обрабатываем сообщение через наш FSM
                    result = message_handler.process_message(user_id, text)
                    reply_text, keyboard_json = result[0], result[1]
                    doc_filenames = getattr(result, "attachments", [])

                    # Подготовка параметров для отправки ответа
                    send_kwargs = {
                        "user_id": user_id,
                        "message": reply_text,
                        "random_id": get_random_id()
                    }
                    if keyboard_json:
                        send_kwargs["keyboard"] = keyboard_json

                    # Если к сообщению прилагаются документы согласия (.docx)
                    if doc_filenames and vk:
                        attachment_str = upload_and_get_doc_attachments(vk, user_id, doc_filenames)
                        if attachment_str:
                            send_kwargs["attachment"] = attachment_str

                    vk.messages.send(**send_kwargs)
                    bot_logger.info(f"Отправлен ответ [user_id={user_id}]: {reply_text[:60]}...")
        except KeyboardInterrupt:
            bot_logger.info("Остановка бота по сигналу пользователя (Ctrl+C).")
            break
        except Exception as e:
            bot_logger.error(f"Сбой в цикле LongPoll ВКонтакте: {e}", exc_info=True)
            bot_logger.info("Переподключение к LongPoll через 5 секунд...")
            longpoll = None
            time.sleep(5.0)


if __name__ == "__main__":
    if "--cli" in sys.argv:
        start_cli_interactive_mode()
    else:
        start_vk_bot()
