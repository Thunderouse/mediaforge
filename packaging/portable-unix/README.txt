MediaForge 1.0 — портативный медиаконвертер (Linux x86_64 / aarch64)
====================================================================

ЗАПУСК
  1. Распакуйте архив целиком:
       tar -xzf MediaForge-portable-linux-*.tar.gz
  2. Запустите:
       ./MediaForge.sh
     Или двойным кликом по MediaForge.sh в файловом менеджере
     (может понадобиться «Разрешить выполнение» в свойствах файла).
  3. Ярлык в меню приложений (необязательно):
       ./create-shortcut.sh

Ничего не устанавливается: ни пакетов, ни служб, ни записей в конфигах системы.
Настройки и геометрия окна лежат в папке data/ рядом с программой.
Удаление — просто удалить папку.

ЧТО ВНУТРИ
  python/   — переносимый Python 3.12 (python-build-standalone)
  app/      — код программы и библиотеки (PySide6, Pillow)
  bin/      — ffmpeg и ffprobe (статическая сборка johnvansickle.com)
  MediaForge.sh        — лаунчер
  create-shortcut.sh   — ярлык в меню приложений
  icon.png             — иконка

ТРЕБОВАНИЯ
  • Linux x86_64: glibc 2.34+ (Ubuntu 22.04+, Debian 12+, Fedora 36+)
  • Linux aarch64: glibc 2.39+ (Ubuntu 24.04+, Debian 13+, Fedora 40+)
  • графическая сессия X11 или Wayland;
  • для минимальных установок могут понадобиться системные библиотеки:
      Debian/Ubuntu: sudo apt install libegl1 libgl1 libxkbcommon-x11-0 \
                      libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
                      libxcb-keysyms1 libxcb-render-util0 libxcb-shape0
      Fedora:        sudo dnf install mesa-libEGL libxkbcommon-x11 xcb-util-cursor
  Проверить окружение: ./python/bin/python3 -c "import PySide6; print(PySide6.__version__)"

ВОЗМОЖНОСТИ
  • Видео → MP4 (H.264), MKV (H.265/H.264), WebM (VP9), MOV, AVI
  • Видео → GIF (FPS, ширина, зацикливание, двухпроходная палитра)
  • Звук из видео → MP3, M4A, WAV, FLAC, Opus, OGG
  • Картинки → PNG, JPEG, WebP, AVIF, TIFF, BMP, GIF, ICO, PDF
  • Перетаскивание файлов и папок, прогресс, отмена, светлая и тёмная темы

ГОРЯЧИЕ КЛАВИШИ
  Ctrl+O — добавить файлы     Ctrl+Enter — конвертировать
  Esc — остановить            Ctrl+L / Ctrl+D — светлая / тёмная тема

ЕСЛИ НЕ ЗАПУСКАЕТСЯ
  Запустите из терминала — там будет текст ошибки:
      ./MediaForge.sh
  Частые причины: не распакован архив целиком; нет прав на запуск
  (chmod +x MediaForge.sh); нет системных библиотек из списка выше;
  Wayland-сессия без XWayland — попробуйте QT_QPA_PLATFORM=xcb ./MediaForge.sh

ffmpeg — GPL (johnvansickle.com), исходники на ffmpeg.org.
Оболочка MediaForge — MIT.
