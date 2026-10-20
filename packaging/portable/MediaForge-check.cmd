@echo off
rem Диагностика portable-сборки: покажет версии Python, PySide6, Pillow, ffmpeg.
rem Если приложение не запускается — пришлите вывод этого окна.
chcp 65001 >nul
cd /d "%~dp0"
echo === MediaForge: проверка окружения ===
echo Папка: %CD%
echo.
"%~dp0python\python.exe" -c "import sys; print('Python  ', sys.version.split()[0], sys.maxsize > 2**32 and 'x64' or 'x86')"
"%~dp0python\python.exe" -c "import PySide6; print('PySide6 ', PySide6.__version__)"
"%~dp0python\python.exe" -c "import PIL; print('Pillow  ', PIL.__version__)"
"%~dp0python\python.exe" -c "import mediaforge; print('MediaForge', mediaforge.__version__)"
"%~dp0python\python.exe" -c "from PySide6.QtWidgets import QApplication, QWidget; print('Qt widgets: import OK')"
echo.
"%~dp0bin\ffmpeg.exe" -hide_banner -version 2>&1 | findstr /b /c:"ffmpeg version"
"%~dp0bin\ffprobe.exe" -hide_banner -version 2>&1 | findstr /b /c:"ffprobe version"
echo.
echo === конец проверки ===
pause
