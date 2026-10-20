"""Общие утилиты разбора PE-зависимостей для сборки/проверки portable-версии."""

from __future__ import annotations

from pathlib import Path

SYSTEM_PREFIXES = (
    "api-ms-win-", "ext-ms-win-", "kernel32", "user32", "gdi32", "advapi32", "shell32",
    "ole32", "oleaut32", "shlwapi", "comdlg32", "comctl32", "ws2_32", "winmm", "version",
    "imm32", "uxtheme", "dwmapi", "msvcrt", "ntdll", "rpcrt4", "secur32", "crypt32",
    "bcrypt", "dnsapi", "iphlpapi", "netapi32", "userenv", "psapi", "setupapi", "wintrust",
    "gdiplus", "winspool.drv", "opengl32", "glu32", "msimg32", "dbghelp", "powrprof",
    "d3d11", "d3d9", "d3d12", "d3d10warp", "d3dcompiler_47", "dxgi", "dwrite", "d2d1",
    "uiautomationcore", "authz", "wtsapi32", "mpr", "wininet", "urlmon", "odbc32", "pdh",
    "shcore", "twain_32", "avrt", "mfplat", "mfreadwrite", "mf", "mfuuid", "ksuser",
    "winhttp", "vcruntime140", "vcruntime140_1", "msvcp140", "ucrtbase", "python311.dll",
    "python3.dll", "mscms", "ncrypt", "avicap32", "cabinet", "msi", "oleacc", "sechost",
    "profapi", "cfgmgr32", "imagehlp", "msvfw32", "msacm32", "dsound", "dinput8",
    "xinput", "wldap32", "normaliz", "evr", "quartz", "hid", "wevtapi",
    # Windows 10/11 поставляет ICU в System32 — Qt6Core импортирует icuuc.dll
    "icu",
)
# отсутствие этих библиотек — реальная ошибка, остальные считаем системными
CRITICAL_PREFIXES = ("qt6", "qt5", "qt", "shiboken", "python3", "icu", "libssl", "libcrypto")


def imports_of(path: Path) -> list[str]:
    import pefile

    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        result = []
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
            raw = entry.dll
            result.append(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw))
        pe.close()
        return result
    except Exception:  # noqa: BLE001 — битый/не-PE файл
        return []


def is_system(dep: str) -> bool:
    return dep.lower().startswith(SYSTEM_PREFIXES)


def is_critical(dep: str) -> bool:
    return dep.lower().startswith(CRITICAL_PREFIXES)


def prune_orphans(root: Path, passes: int = 6, protect: tuple[str, ...] = ()) -> int:
    """Удаляет файлы, чьи зависимости отсутствуют (осиротевшие Qt-модули).

    Запускается после чистки неиспользуемых модулей: удаляет то, что ссылается
    на вырезанное, пока набор не стабилизируется. Файлы из `protect`
    (шаблоны fnmatch по пути относительно root) не удаляются никогда.
    """
    import fnmatch

    try:
        import pefile  # noqa: F401
    except ImportError:
        print("  pefile не установлен — чистка сирот пропущена")
        return 0

    def protected(path: Path) -> bool:
        rel = str(path.relative_to(root)).replace("\\", "/").lower()
        return any(fnmatch.fnmatch(rel, pattern) for pattern in protect)

    total = 0
    for _ in range(passes):
        files = [p for p in root.rglob("*") if p.suffix.lower() in (".dll", ".pyd", ".exe")]
        present = {p.name.lower() for p in files}
        removed = 0
        for path in files:
            if protected(path):
                continue
            bad = [d for d in imports_of(path)
                   if d.lower() not in present and not is_system(d)]
            if bad:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        total += removed
        if not removed:
            break
    return total
