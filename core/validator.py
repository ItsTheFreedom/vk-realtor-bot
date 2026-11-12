import re
from typing import Tuple


def title_case_fio(fio_str: str) -> str:
    """Поднимает первые буквы слов в верхний регистр (с учетом двойных фамилий/имён через дефис)."""
    words = []
    for word in fio_str.split():
        parts = word.split("-")
        capitalized_parts = [p.capitalize() if len(p) > 0 else p for p in parts]
        words.append("-".join(capitalized_parts))
    return " ".join(words)


def validate_fio(text: str) -> Tuple[bool, str]:
    """
    Валидация ФИО (как риэлтора, так и клиента).
    Требование ТЗ: введённая строка должна содержать не менее двух слов (разделённых пробелами).
    
    :param text: Входящая строка с ФИО
    :return: Кортеж (is_valid, cleaned_fio)
    """
    if not text or not isinstance(text, str):
        return False, ""

    # Очищаем от лишних начальных/конечных и двойных пробелов
    cleaned = re.sub(r"\s+", " ", text.strip())
    
    # Разделяем по пробелам
    words = cleaned.split()
    if len(words) < 2:
        return False, cleaned

    # Проверяем, что слова состоят преимущественно из букв (русских или латинских, а также дефисов для двойных фамилий/имён)
    for word in words:
        # Убираем дефисы при проверке на буквы
        word_letters = word.replace("-", "").replace("'", "")
        if not word_letters.isalpha() and not all(c.isalpha() or c == '.' for c in word_letters):
            return False, cleaned

    # Автоматически поднимаем первые буквы в верхний регистр
    return True, title_case_fio(cleaned)


def format_short_fio(full_fio: str) -> str:
    """
    Формирование краткого ФИО (например, "иванов иван иванович" -> "Иванов И.И.").
    Если только два слова ("иванов иван") -> "Иванов И.".
    """
    clean_title = title_case_fio(full_fio.strip())
    words = clean_title.split()
    if not words:
        return full_fio
    if len(words) == 1:
        return words[0]
    
    surname = words[0]
    initials = "".join([f"{w[0].upper()}." for w in words[1:] if w])
    return f"{surname} {initials}"


def validate_phone(text: str) -> Tuple[bool, str]:
    """
    Валидация и нормализация номера телефона клиента.
    Требование: российский номер должен содержать ровно 10 цифр (без кода) или 11 цифр (с кодом 7 или 8).
    Итоговая строка с '+7' содержит ровно 12 символов (например, +79501234567).
    
    :param text: Входящая строка с телефоном
    :return: Кортеж (is_valid, formatted_phone)
    """
    if not text or not isinstance(text, str):
        return False, ""

    # Извлекаем только цифры из строки
    digits = re.sub(r"\D", "", text)
    
    # Проверяем количество цифр: должно быть ровно 10 (например 9501234567) или 11 (79501234567 / 89501234567)
    if len(digits) not in (10, 11):
        return False, text.strip()

    # Форматируем номер к единому российскому стандарту (+7 и 10 цифр номера, всего 12 символов)
    if len(digits) == 10:
        clean_phone = f"+7{digits}"
    elif len(digits) == 11:
        if digits[0] in ("7", "8"):
            clean_phone = f"+7{digits[1:]}"
        else:
            # Если 11 цифр, но начинается не с 7 и не с 8 (например, опечатка)
            return False, text.strip()

    return True, clean_phone
