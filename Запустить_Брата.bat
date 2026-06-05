@echo off
chcp 65001 >nul
cd /d "%~dp0"
title БРАТ — запуск
echo Запускаю БРАТ...
python -u dark_gui.py
if errorlevel 1 (
    echo.
    echo [!] Программа завершилась с ошибкой. Скрин этого окна пришли в чат.
    pause
)
