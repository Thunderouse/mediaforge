# MediaForge — разработка и сборка

Пользовательская инструкция — в [README.md](../README.md). Здесь: архитектура,
запуск из исходников, тесты, сборка `.exe` и portable-архива.

## Стек и почему так

- **Python 3.10+**, потому что вся тяжёлая работа — внешний процесс `ffmpeg`;
  язык оболочки на результат не влияет, а итерация быстрая.
- **PySide6 (Qt Widgets)** — настоящий десктопный UI, один код на
  Windows/macOS/Linux, ~80 МБ ОЗУ в покое против 200+ у Electron/Compose.
  Оформление целиком на QSS + собственная отрисовка контролов, без ресурсов.
- **Pillow** — конвертация картинок: лучшее качество и скорость на JVM-альтернативах
  (включая WebP/AVIF/ICO, прозрачность и EXIF).
- **ffmpeg CLI**, а не libav-биндинги: те же аргументы, что человек набирает руками,
  проще отлаживать, и не нужны нативные сборки под каждый Python.

## Структура

```
mediaforge/
├── core/                 # не зависит от Qt — можно использовать как библиотеку
│   ├── ffmpeg.py         # поиск ffmpeg/ffprobe, метаданные, прогресс, отмена
│   ├── formats.py        # реестр форматов и параметры конвертации
│   ├── convert.py        # сборка команд ffmpeg / вызовы Pillow, одна конверсия
│   ├── engine.py         # очередь, потоки, события
│   └── config.py         # настройки (JSON)
├── ui/
│   ├── theme.py          # палитры светлая/тёмная + QSS-шаблон
│   ├── icons.py          # инлайн-SVG иконки (без файлов-ресурсов)
│   ├── widgets.py        # drop-зона, строка файла, чекбоксы, сегменты
│   └── main_window.py    # сборка окна и логика
├── app.py                # точка входа GUI
└── cli.py                # консольный режим
```

Добавить новый формат: одна запись в `core/formats.py` и ветка в
`core/convert.py` (видео — аргументы ffmpeg, картинки — Pillow). Интерфейс
подхватит его сам: списки форматов строятся из реестра.

## Запуск из исходников

Windows:

```powershell
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m mediaforge           # или двойной клик по run.pyw / start.cmd
```

Linux/macOS:

```bash
./start.sh                     # создаст venv и запустит
sudo apt install ffmpeg        # Debian/Ubuntu; macOS: brew install ffmpeg
```

`ffmpeg`/`ffprobe` ищутся в таком порядке: `MEDIAFORGE_BIN` → папка `bin` рядом
с приложением (или в `sys._MEIPASS`) → `PATH` → типичные места установки.
Если не найдены — приложение открывается, показывает баннер и блокирует
конвертацию (не падает).

## Тесты

```bash
pip install pytest
python -m pytest               # 18 тестов
```

Покрыто: реестр форматов, `unique_path`, `human_size/duration`, обход папок,
`ffprobe`-метаданные, конвертация картинок (PNG/JPEG/WebP/AVIF/TIFF/BMP/ICO/PDF),
ресайз по длинной стороне, видео в MP4/WebM, видео в GIF, извлечение звука,
ошибка «нет звуковой дорожки», отмена, форма собранных argv (`palettegen`,
`-vn`, `-threads`). Тестовые медиа генерируются на лету через `ffmpeg -f lavfi`;
без ffmpeg соответствующие тесты пропускаются (`pytest.mark.skipif`).

Линтер (используется в CI): `python -m ruff check --select F,E9 .`

## Сборка `.exe` (PyInstaller, только на Windows)

```powershell
.\build_windows.ps1              # dist\MediaForge\MediaForge.exe
.\build_windows.ps1 -WithFFmpeg  # то же + ffmpeg внутри папки bin
```

Linux/macOS: `./build_unix.sh --with-ffmpeg`. Скрипты создают venv, ставят
зависимости, генерируют иконку (`tools/make_icons.py`, нужен только Pillow)
и собирают по `MediaForge.spec`. PyInstaller **не** кросс-компилирует: бинарник
каждой ОС собирается на своей ОС.

## Portable-сборка Windows (без установки, собирается и из Linux)

```bash
pip install pefile           # нужен для чистки и проверки PE-зависимостей
python tools/build_portable.py --stage build/portable --out dist
python tools/check_portable.py build/portable/MediaForge-portable-win64
```

Что делает `build_portable.py`:

1. качает embeddable Python 3.11 и wheels `PySide6-Essentials`/`shiboken6`/`Pillow`
   для `win_amd64` (кэш — в `build/cache`, повторная сборка без сети);
2. раскладывает `python/`, `app/` (код + `site-packages`), `bin/` (ffmpeg), пишет
   `python311._pth` с путями `..\app` и `..\app\Lib\site-packages`;
3. вырезает неиспользуемые модули Qt (`qml`, `translations`, `Qt6Quick*`,
   `Qt6Pdf*` и т. п. — около 100 МБ), убирает `*.exe`-утилиты и импорт-библиотеки;
4. **чистит сирот по PE-импортам**: файл удаляется, если его зависимость вырезана,
   с защитным списком модулей, которые приложению нужны всегда;
5. собирает нативный лаунчер `MediaForge.exe` кросс-компиляцией `zig cc`
   (`packaging/portable/launcher.c`, `-target x86_64-windows-gnu -municode
   -Wl,--subsystem,windows`, иконка через `zig rc`); если `zig` недоступен —
   остаётся `.cmd`-лаунчер;
6. пакует zip с CRLF в `.cmd`/`.txt`.

`check_portable.py` проверяет обязательные файлы и разрешимость всех PE-импортов
внутри папки — именно эта проверка ловит лишнюю чистку Qt (например, удаление
`Qt6Core.dll` из-за отсутствующего `icuuc.dll`, который Windows держит в System32).

Лаунчер выставляет `MEDIAFORGE_BIN` и `MEDIAFORGE_CONFIG_DIR`, поэтому настройки
портативной сборки живут в `data\` рядом с программой.

## Особенности реализации, о которых легко забыть

- Под `pythonw.exe` `sys.stderr is None`: любые записи в него падают. Эксепшн-хук
  пишет traceback в `%TEMP%\mediaforge-error.log` и показывает QMessageBox.
- `ffmpeg` пишет `out_time_ms`, но это **микросекунды** — прогресс считается
  как `us / 1e6 / duration`.
- Кодировщики ищутся в списке `ffmpeg -encoders`, а аппаратный (NVENC/QSV/AMF/
  VideoToolbox) дополнительно проверяется реальным кадром 320×240 — наличие
  в списке ещё не значит «работает», иначе на машине без GPU всё падало бы.
- `QWidget`-подклассу нужен `setAttribute(Qt.WA_StyledBackground, True)`, иначе
  QSS-фон не рисуется.
- Завершение пачки — по счётчику `remaining == 0`, а не `running == 0`: пул
  опускает `running` в ноль между задачами и UI раньше времени объявляет «готово».

## Лицензия

MIT. `ffmpeg` в сборке — под GPL/GPLv3 (gyan.dev essentials), исходники на
ffmpeg.org; при распространении учитывайте условия лицензии бинарника.
