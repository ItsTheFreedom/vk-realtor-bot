#!/bin/bash
# start_bot.sh — запуск бота в фоне (nohup), работает после закрытия консоли

cd "$(dirname "$0")"  # переходим в папку скрипта

# Если существует виртуальное окружение, активируем его
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "Виртуальное окружение активировано"
else
    echo "Виртуальное окружение не найдено, используем системный Python"
fi

# Запускаем бота в фоне с nohup
nohup python main.py > bot.log 2>&1 &

echo "Бот запущен в фоне (PID: $!)"
echo "Логи: tail -f bot.log"
echo "Остановить: kill $!"