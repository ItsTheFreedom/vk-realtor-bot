import json
from typing import Optional
try:
    from vk_api.keyboard import VkKeyboard, VkKeyboardColor
except ImportError:
    VkKeyboard = None
    VkKeyboardColor = None


class Keyboards:
    """Генератор клавиатур ВКонтакте (в формате JSON для API ВКонтакте)."""

    @staticmethod
    def _build_json_fallback(buttons_rows: list, one_time: bool = True) -> str:
        """Резервный генератор JSON клавиатуры (если vk_api не установлен или в тестах)."""
        color_map = {
            "positive": "positive",
            "primary": "primary",
            "negative": "negative",
            "secondary": "secondary"
        }
        buttons = []
        for row in buttons_rows:
            row_btns = []
            for btn in row:
                row_btns.append({
                    "action": {
                        "type": "text",
                        "label": btn["label"]
                    },
                    "color": color_map.get(btn.get("color", "secondary"), "secondary")
                })
            buttons.append(row_btns)
        return json.dumps({"one_time": one_time, "buttons": buttons}, ensure_ascii=False)

    @classmethod
    def get_start_keyboard(cls) -> str:
        """Клавиатура с кнопкой «🚀 Начать работу» для старта диалога."""
        if VkKeyboard:
            kb = VkKeyboard(one_time=True)
            kb.add_button("🚀 Начать работу", color=VkKeyboardColor.POSITIVE)
            return kb.get_keyboard()
        else:
            return cls._build_json_fallback([
                [{"label": "🚀 Начать работу", "color": "positive"}]
            ], one_time=True)

    @classmethod
    def get_accept_consent_keyboard(cls) -> str:
        """Клавиатура с кнопкой «✅ Принимаю» для подтверждения согласия с документами."""
        if VkKeyboard:
            kb = VkKeyboard(one_time=True)
            kb.add_button("✅ Принимаю", color=VkKeyboardColor.POSITIVE)
            return kb.get_keyboard()
        else:
            return cls._build_json_fallback([
                [{"label": "✅ Принимаю", "color": "positive"}]
            ], one_time=True)

    @classmethod
    def get_confirmation_keyboard(cls) -> str:
        """Клавиатура подтверждения: «Всё верно» / «Исправить»."""
        if VkKeyboard:
            kb = VkKeyboard(one_time=True)
            kb.add_button("Всё верно", color=VkKeyboardColor.POSITIVE)
            kb.add_button("Исправить", color=VkKeyboardColor.PRIMARY)
            kb.add_line()
            kb.add_button("/cancel", color=VkKeyboardColor.NEGATIVE)
            return kb.get_keyboard()
        else:
            return cls._build_json_fallback([
                [{"label": "Всё верно", "color": "positive"}, {"label": "Исправить", "color": "primary"}],
                [{"label": "/cancel", "color": "negative"}]
            ], one_time=True)

    @classmethod
    def get_edit_fields_keyboard(cls) -> str:
        """Клавиатура выбора поля для исправления."""
        if VkKeyboard:
            kb = VkKeyboard(one_time=True)
            kb.add_button("ФИО риэлтора", color=VkKeyboardColor.SECONDARY)
            kb.add_button("Агентство", color=VkKeyboardColor.SECONDARY)
            kb.add_line()
            kb.add_button("ФИО клиента", color=VkKeyboardColor.SECONDARY)
            kb.add_button("Телефон клиента", color=VkKeyboardColor.SECONDARY)
            kb.add_line()
            kb.add_button("/cancel", color=VkKeyboardColor.NEGATIVE)
            return kb.get_keyboard()
        else:
            return cls._build_json_fallback([
                [{"label": "ФИО риэлтора"}, {"label": "Агентство"}],
                [{"label": "ФИО клиента"}, {"label": "Телефон клиента"}],
                [{"label": "/cancel", "color": "negative"}]
            ], one_time=True)

    @classmethod
    def get_empty_keyboard(cls) -> str:
        """Скрытие (удаление) клавиатуры."""
        if VkKeyboard:
            return VkKeyboard.get_empty_keyboard()
        else:
            return json.dumps({"buttons": [], "one_time": True})
