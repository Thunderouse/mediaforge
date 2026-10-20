"""Точка входа `python -m mediaforge` и PyInstaller.

Импорт абсолютный намеренно: PyInstaller анализирует этот файл как скрипт и
`from .app import main` разрешить не может — зависимость выпадает из сборки
(.app собирался без PySide6)."""

from mediaforge.app import main

if __name__ == "__main__":
    raise SystemExit(main())
