@echo off
rem Диагностический запуск: видно консоль и текст ошибки.
setlocal
cd /d "%~dp0"
set "MEDIAFORGE_BIN=%~dp0bin"
set "MEDIAFORGE_CONFIG_DIR=%~dp0data"
if not exist "%~dp0data" mkdir "%~dp0data" >nul 2>&1
"%~dp0python\python.exe" -m mediaforge
echo.
echo Код выхода: %ERRORLEVEL%
pause
endlocal
