import sqlite3
import json
import time
from typing import Dict, Any, Optional
from config import Config
from core.logger import bot_logger


class Storage:
    """
    Персистентное хранилище сессий пользователей (риэлторов) на основе SQLite.
    Обеспечивает сохранение состояния FSM, данных риэлтора (ФИО, агентство) 
    и промежуточных данных клиента на срок не менее 24 часов (по ТЗ).
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or Config.DB_PATH)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Создание таблицы сессий, если она отсутствует."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        user_id INTEGER PRIMARY KEY,
                        state TEXT NOT NULL DEFAULT 'IDLE',
                        realtor_fio TEXT DEFAULT '',
                        realtor_agency TEXT DEFAULT '',
                        client_fio TEXT DEFAULT '',
                        client_phone TEXT DEFAULT '',
                        last_updated INTEGER NOT NULL
                    )
                """)
                conn.commit()
            bot_logger.info(f"База данных сессий инициализирована по пути: {self.db_path}")
        except Exception as e:
            bot_logger.error(f"Ошибка при инициализации базы данных {self.db_path}: {e}", exc_info=True)

    def get_session(self, user_id: int) -> Dict[str, Any]:
        """
        Получает текущую сессию пользователя.
        Если сессия истекла (> SESSION_TTL_HOURS часов), сбрасывает её.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM sessions WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()

                now = int(time.time())
                ttl_seconds = Config.SESSION_TTL_HOURS * 3600

                if row:
                    session_data = dict(row)
                    # Проверяем TTL сессии (не менее 24 часов)
                    if now - session_data["last_updated"] > ttl_seconds:
                        bot_logger.info(f"Сессия пользователя {user_id} истекла по TTL (>{Config.SESSION_TTL_HOURS}ч). Сброс.")
                        self.reset_session(user_id)
                        return self._empty_session(user_id)
                    return session_data
                else:
                    return self._empty_session(user_id)
        except Exception as e:
            bot_logger.error(f"Ошибка получения сессии для {user_id}: {e}", exc_info=True)
            return self._empty_session(user_id)

    def _empty_session(self, user_id: int) -> Dict[str, Any]:
        return {
            "user_id": user_id,
            "state": "IDLE",
            "realtor_fio": "",
            "realtor_agency": "",
            "client_fio": "",
            "client_phone": "",
            "last_updated": int(time.time())
        }

    def update_session(self, user_id: int, **kwargs) -> Dict[str, Any]:
        """
        Обновляет поля сессии для указанного пользователя и обновляет метку времени.
        """
        session = self.get_session(user_id)
        for key, value in kwargs.items():
            if key in session:
                session[key] = value
        session["last_updated"] = int(time.time())

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sessions (
                        user_id, state, realtor_fio, realtor_agency, client_fio, client_phone, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        state = excluded.state,
                        realtor_fio = excluded.realtor_fio,
                        realtor_agency = excluded.realtor_agency,
                        client_fio = excluded.client_fio,
                        client_phone = excluded.client_phone,
                        last_updated = excluded.last_updated
                """, (
                    user_id,
                    session["state"],
                    session["realtor_fio"],
                    session["realtor_agency"],
                    session["client_fio"],
                    session["client_phone"],
                    session["last_updated"]
                ))
                conn.commit()
        except Exception as e:
            bot_logger.error(f"Ошибка сохранения сессии для {user_id}: {e}", exc_info=True)

        return session

    def reset_session(self, user_id: int):
        """Полный сброс сессии пользователя (команда /reset)."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                conn.commit()
            bot_logger.info(f"Сессия пользователя {user_id} полностью сброшена.")
        except Exception as e:
            bot_logger.error(f"Ошибка при сбросе сессии {user_id}: {e}", exc_info=True)

    def reset_client_data(self, user_id: int):
        """
        Сброс только данных текущего клиента при сохранении данных риэлтора
        (после успешной фиксации лида или при команде /cancel).
        """
        session = self.get_session(user_id)
        if session.get("realtor_fio"):
            # Если данные риэлтора известны, переходим к ожиданию следующего клиента
            self.update_session(
                user_id,
                state="WAITING_CLIENT_FIO",
                client_fio="",
                client_phone=""
            )
        else:
            # Если данных риэлтора нет, полный сброс
            self.reset_session(user_id)


# Глобальный экземпляр хранилища
storage = Storage()
