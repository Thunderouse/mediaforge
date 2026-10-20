"""Проверка целостности portable-сборки: все ли PE-зависимости на месте.

    python tools/check_portable.py build/portable/MediaForge-portable-win64

Проверяет импорты каждого .exe/.dll/.pyd: библиотеки Qt/shiboken/python, которых
нет ни в сборке, ни в списке системных, попадают в отчёт — так ловится лишняя
чистка Qt при сборке.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from peutil import imports_of, is_critical, is_system  # noqa: E402

REQUIRED = [
    "python/pythonw.exe",
    "python/python.exe",
    "python/python311._pth",
    "python/python311.dll",
    "bin/ffmpeg.exe",
    "bin/ffprobe.exe",
    "app/mediaforge/app.py",
    "app/mediaforge/core/convert.py",
    "MediaForge.cmd",
    "app/Lib/site-packages/PySide6/Qt6Core.dll",
    "app/Lib/site-packages/PySide6/Qt6Gui.dll",
    "app/Lib/site-packages/PySide6/Qt6Widgets.dll",
    "app/Lib/site-packages/PySide6/Qt6Svg.dll",
    "app/Lib/site-packages/PySide6/QtWidgets.pyd",
    "app/Lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
    "app/Lib/site-packages/PySide6/plugins/iconengines/qsvgicon.dll",
    "app/Lib/site-packages/shiboken6/shiboken6.abi3.dll",
    "app/Lib/site-packages/PIL/Image.py",
]


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "build/portable/MediaForge-portable-win64")
    if not root.is_dir():
        print(f"нет папки {root}")
        return 2
    files = [p for p in root.rglob("*") if p.suffix.lower() in (".dll", ".pyd", ".exe")]
    present = {p.name.lower() for p in files}
    print(f"бинарников: {len(files)}")

    missing: dict[str, set[str]] = {}
    for path in files:
        for dep in imports_of(path):
            low = dep.lower()
            if low in present or is_system(dep):
                continue
            missing.setdefault(dep, set()).add(str(path.relative_to(root)))

    absent = [r for r in REQUIRED if not (root / r).exists()]
    critical = {k: v for k, v in missing.items() if is_critical(k)}
    optional = {k: v for k, v in missing.items() if k not in critical}

    size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    print(f"размер: {size / 1e6:.0f} МБ (без сжатия)")
    if absent:
        print("\nНЕТ ОБЯЗАТЕЛЬНЫХ ФАЙЛОВ:")
        for a in absent:
            print("  -", a)
    if critical:
        print("\nКРИТИЧНО — отсутствуют библиотеки Qt/Python:")
        for dep, users in sorted(critical.items()):
            print(f"  - {dep}  ← {', '.join(sorted(users)[:3])}")
    if optional:
        print("\nнеобязательные (системные/неиспользуемые плагины):")
        for dep, users in sorted(optional.items()):
            print(f"  - {dep}  ← {', '.join(sorted(users)[:2])}")

    if not absent and not critical:
        print("\nOK: структура полная, все Qt/Python-зависимости разрешены внутри папки")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
