from typing import Tuple, Optional, List
from core.storage import storage
from core.validator import validate_fio, validate_phone
from core.logger import bot_logger
from bot.states import States
from bot.texts import Texts
from bot.keyboards import Keyboards
from services.yandex_sheets import yandex_sheets
from services.bitrix24 import bitrix24


class HandlerResult(tuple):
    """
    Умный результат обработки сообщения:
    Позволяет как распаковку в 2 элемента `reply, kb = result` (для совместимости с тестами),
    так и доступ к списку прикрепляемых файлов через атрибут `result.attachments`.
    """
    def __new__(cls, text: str, keyboard: Optional[str] = None, attachments: Optional[List[str]] = None):
        return super().__new__(cls, (text, keyboard))
    
    def __init__(self, text: str, keyboard: Optional[str] = None, attachments: Optional[List[str]] = None):
        self.text = text
        self.keyboard = keyboard
        self.attachments = attachments or []


class MessageHandler:
    """Обработчик входящих сообщений, кнопок и команд чат-бота ВКонтакте."""

    @staticmethod
    def _handle_duplicate_client(user_id: int, realtor_fio: str, client_phone: str) -> Optional[HandlerResult]:
        """
        Проверяет таблицу на дубликат клиента по телефону.
        Возвращает HandlerResult с сообщением об ошибке или None, если фиксация возможна.
        """
        is_other, existing = yandex_sheets.is_client_registered_by_other_realtor(
            client_phone, realtor_fio
        )
        if not existing:
            return None

        storage.reset_client_data(user_id)
        if is_other:
            return HandlerResult(
                Texts.CLIENT_ALREADY_REGISTERED_OTHER_REALTOR,
                Keyboards.get_empty_keyboard(),
            )
        return HandlerResult(Texts.CLIENT_ALREADY_REGISTERED_SELF, Keyboards.get_empty_keyboard())

    @staticmethod
    def process_message(user_id: int, text: str) -> HandlerResult:
        """
        Обрабатывает текстовое сообщение от пользователя ВКонтакте по шагам FSM.
        
        :param user_id: ID пользователя ВКонтакте
        :param text: Текст сообщения
        :return: HandlerResult (текст_ответа, json_клавиатуры, attachments)
        """
        raw_text = (text or "").strip()
        lower_text = raw_text.lower()

        bot_logger.info(f"Входящее сообщение от [user_id={user_id}]: {raw_text}")

        # 1. Обработка глобальных команд /reset и /cancel
        if lower_text == "/reset":
            storage.reset_session(user_id)
            storage.update_session(user_id, state=States.WELCOME_SEEN)
            return HandlerResult(Texts.WELCOME_INTRO, Keyboards.get_start_keyboard())

        if lower_text in ("/cancel", "отмена"):
            storage.reset_client_data(user_id)
            return HandlerResult(Texts.CANCEL_SUCCESS, Keyboards.get_empty_keyboard())

        # Получаем текущее состояние сессии
        session = storage.get_session(user_id)
        state = session.get("state", States.IDLE)

        # Обработка нажатия кнопки "🚀 Начать работу" или "Начать" (старт диалога с выдачей согласий)
        if lower_text in ("🚀 начать работу", "начать работу", "начало", "начать", "/start_work", "старт", "/start"):
            storage.update_session(user_id, state=States.WAITING_CONSENT_ACCEPT)
            docs = [
                "policy.docx",
                "consent.docx"
            ]
            return HandlerResult(Texts.WELCOME_DOCS_CONSENT, Keyboards.get_accept_consent_keyboard(), attachments=docs)

        # Обработка согласия с документами (кнопка «✅ Принимаю»)
        if state == States.WAITING_CONSENT_ACCEPT:
            if lower_text in ("✅ принимаю", "принимаю", "согласен", "да", "/accept"):
                storage.update_session(user_id, state=States.WAITING_REALTOR_FIO)
                return HandlerResult(Texts.ASK_REALTOR_FIO, Keyboards.get_empty_keyboard())
            else:
                return HandlerResult("Пожалуйста, нажмите кнопку «✅ Принимаю» ниже, чтобы подтвердить согласие с условиями документов и продолжить работу:", Keyboards.get_accept_consent_keyboard())

        # Если сессия пустая или в состоянии IDLE, приветствуем и выдаём кнопку «🚀 Начать работу»
        if state == States.IDLE or not session.get("realtor_fio"):
            if state not in (States.WAITING_REALTOR_FIO, States.WAITING_CONSENT_ACCEPT, States.WELCOME_SEEN):
                storage.update_session(user_id, state=States.WELCOME_SEEN)
                return HandlerResult(Texts.WELCOME_INTRO, Keyboards.get_start_keyboard())
            elif state == States.WELCOME_SEEN:
                return HandlerResult(Texts.WELCOME_INTRO, Keyboards.get_start_keyboard())

        # ШАГ 1: ФИО риэлтора
        if state == States.WAITING_REALTOR_FIO:
            is_valid, cleaned_fio = validate_fio(raw_text)
            if is_valid:
                storage.update_session(user_id, realtor_fio=cleaned_fio, state=States.WAITING_AGENCY)
                return Texts.ASK_AGENCY, Keyboards.get_empty_keyboard()
            else:
                return Texts.REALTOR_FIO_INVALID, Keyboards.get_empty_keyboard()

        # ШАГ 2: Название агентства
        if state == States.WAITING_AGENCY:
            agency = raw_text if raw_text.lower() != "нет" and raw_text else "Нет"
            storage.update_session(user_id, realtor_agency=agency, state=States.WAITING_CLIENT_FIO)
            return (
                Texts.realtor_saved_ask_client_fio(session.get("realtor_fio", ""), agency),
                Keyboards.get_empty_keyboard()
            )

        # ШАГ 3: ФИО клиента
        if state == States.WAITING_CLIENT_FIO:
            is_valid, cleaned_fio = validate_fio(raw_text)
            if is_valid:
                storage.update_session(user_id, client_fio=cleaned_fio, state=States.WAITING_CLIENT_PHONE)
                return Texts.ASK_CLIENT_PHONE, Keyboards.get_empty_keyboard()
            else:
                return Texts.CLIENT_FIO_INVALID, Keyboards.get_empty_keyboard()

        # ШАГ 4: Телефон клиента
        if state == States.WAITING_CLIENT_PHONE:
            is_valid, clean_phone = validate_phone(raw_text)
            if is_valid:
                duplicate_reply = MessageHandler._handle_duplicate_client(
                    user_id, session.get("realtor_fio", ""), clean_phone
                )
                if duplicate_reply:
                    return duplicate_reply
                storage.update_session(user_id, client_phone=clean_phone, state=States.CONFIRMATION)
                return (
                    Texts.confirmation_summary(
                        session.get("realtor_fio", ""),
                        session.get("realtor_agency", ""),
                        session.get("client_fio", ""),
                        clean_phone
                    ),
                    Keyboards.get_confirmation_keyboard()
                )
            else:
                return Texts.CLIENT_PHONE_INVALID, Keyboards.get_empty_keyboard()

        # ШАГ 5: Подтверждение или исправление
        if state == States.CONFIRMATION:
            if lower_text in ("всё верно", "все верно"):
                realtor_fio = session.get("realtor_fio", "")
                realtor_agency = session.get("realtor_agency", "")
                client_fio = session.get("client_fio", "")
                client_phone = session.get("client_phone", "")

                duplicate_reply = MessageHandler._handle_duplicate_client(user_id, realtor_fio, client_phone)
                if duplicate_reply:
                    return duplicate_reply

                yandex_sheets.add_record(realtor_fio, realtor_agency, client_fio, client_phone)
                bitrix24.create_lead(realtor_fio, realtor_agency, client_fio, client_phone)

                storage.reset_client_data(user_id)
                return Texts.SUCCESS_FIXED, Keyboards.get_empty_keyboard()

            elif lower_text == "исправить":
                storage.update_session(user_id, state=States.EDIT_FIELD_SELECT)
                return Texts.SELECT_FIELD_TO_EDIT, Keyboards.get_edit_fields_keyboard()
            else:
                return (
                    Texts.confirmation_summary(
                        session.get("realtor_fio", ""),
                        session.get("realtor_agency", ""),
                        session.get("client_fio", ""),
                        session.get("client_phone", "")
                    ),
                    Keyboards.get_confirmation_keyboard()
                )

        # Выбор поля для исправления
        if state == States.EDIT_FIELD_SELECT:
            if lower_text in ("1", "1. фио риэлтора", "фио риэлтора"):
                storage.update_session(user_id, state=States.EDIT_REALTOR_FIO)
                return Texts.EDIT_PROMPT_REALTOR_FIO, Keyboards.get_empty_keyboard()
            elif lower_text in ("2", "2. агентство", "агентство"):
                storage.update_session(user_id, state=States.EDIT_AGENCY)
                return Texts.EDIT_PROMPT_AGENCY, Keyboards.get_empty_keyboard()
            elif lower_text in ("3", "3. фио клиента", "фио клиента"):
                storage.update_session(user_id, state=States.EDIT_CLIENT_FIO)
                return Texts.EDIT_PROMPT_CLIENT_FIO, Keyboards.get_empty_keyboard()
            elif lower_text in ("4", "4. телефон клиента", "телефон клиента", "телефон"):
                storage.update_session(user_id, state=States.EDIT_CLIENT_PHONE)
                return Texts.EDIT_PROMPT_CLIENT_PHONE, Keyboards.get_empty_keyboard()
            else:
                return Texts.SELECT_FIELD_TO_EDIT, Keyboards.get_edit_fields_keyboard()

        # Ввод нового значения при исправлении: ФИО риэлтора
        if state == States.EDIT_REALTOR_FIO:
            is_valid, cleaned_fio = validate_fio(raw_text)
            if is_valid:
                session = storage.update_session(user_id, realtor_fio=cleaned_fio, state=States.CONFIRMATION)
                return (
                    Texts.confirmation_summary(
                        cleaned_fio,
                        session.get("realtor_agency", ""),
                        session.get("client_fio", ""),
                        session.get("client_phone", "")
                    ),
                    Keyboards.get_confirmation_keyboard()
                )
            else:
                return Texts.REALTOR_FIO_INVALID, Keyboards.get_empty_keyboard()

        # Ввод нового значения при исправлении: Агентство
        if state == States.EDIT_AGENCY:
            agency = raw_text if raw_text.lower() != "нет" and raw_text else "Нет"
            session = storage.update_session(user_id, realtor_agency=agency, state=States.CONFIRMATION)
            return (
                Texts.confirmation_summary(
                    session.get("realtor_fio", ""),
                    agency,
                    session.get("client_fio", ""),
                    session.get("client_phone", "")
                ),
                Keyboards.get_confirmation_keyboard()
            )

        # Ввод нового значения при исправлении: ФИО клиента
        if state == States.EDIT_CLIENT_FIO:
            is_valid, cleaned_fio = validate_fio(raw_text)
            if is_valid:
                session = storage.update_session(user_id, client_fio=cleaned_fio, state=States.CONFIRMATION)
                return (
                    Texts.confirmation_summary(
                        session.get("realtor_fio", ""),
                        session.get("realtor_agency", ""),
                        cleaned_fio,
                        session.get("client_phone", "")
                    ),
                    Keyboards.get_confirmation_keyboard()
                )
            else:
                return Texts.CLIENT_FIO_INVALID, Keyboards.get_empty_keyboard()

        # Ввод нового значения при исправлении: Телефон клиента
        if state == States.EDIT_CLIENT_PHONE:
            is_valid, clean_phone = validate_phone(raw_text)
            if is_valid:
                duplicate_reply = MessageHandler._handle_duplicate_client(
                    user_id, session.get("realtor_fio", ""), clean_phone
                )
                if duplicate_reply:
                    return duplicate_reply
                session = storage.update_session(user_id, client_phone=clean_phone, state=States.CONFIRMATION)
                return (
                    Texts.confirmation_summary(
                        session.get("realtor_fio", ""),
                        session.get("realtor_agency", ""),
                        session.get("client_fio", ""),
                        clean_phone
                    ),
                    Keyboards.get_confirmation_keyboard()
                )
            else:
                return Texts.CLIENT_PHONE_INVALID, Keyboards.get_empty_keyboard()

        # Обработка неизвестного состояния
        bot_logger.warning(f"Неизвестное состояние {state} для пользователя {user_id}")
        return Texts.UNKNOWN_COMMAND, Keyboards.get_empty_keyboard()


message_handler = MessageHandler()
