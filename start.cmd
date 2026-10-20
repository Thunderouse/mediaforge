@echo off
rem Запуск из исходников на Windows: создаёт venv и открывает приложение.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Первый запуск: создаю окружение и ставлю зависимости...
    py -3 -m venv .venv || python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" run.pyw
