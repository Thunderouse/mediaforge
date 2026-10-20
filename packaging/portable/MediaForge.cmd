@echo off
rem MediaForge — портативный запуск. Ничего не устанавливает и не пишет в реестр.
setlocal
cd /d "%~dp0"
set "MEDIAFORGE_BIN=%~dp0bin"
set "MEDIAFORGE_CONFIG_DIR=%~dp0data"
if not exist "%~dp0data" mkdir "%~dp0data" >nul 2>&1
if not exist "%~dp0python\pythonw.exe" (
    echo Не найдены файлы python. Распакуйте архив целиком, не перетаскивая отдельные папки.
    pause
    exit /b 1
)
start "" "%~dp0python\pythonw.exe" -m mediaforge
endlocal
