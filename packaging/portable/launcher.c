/* MediaForge.exe — тонкий нативный лаунчер портативной сборки.
 *
 * Запускает python\pythonw.exe -m mediaforge из папки, где лежит сам exe,
 * выставляет MEDIAFORGE_BIN и MEDIAFORGE_CONFIG_DIR (портативные настройки),
 * и ничего больше не делает: вся логика — в Python-коде приложения.
 *
 * Сборка (кросс-компиляция из Linux):
 *   zig cc -target x86_64-windows-gnu -municode -mwindows -static -O2 -o MediaForge.exe launcher.c
 */

#include <windows.h>
#include <stdio.h>
#include <wchar.h>

#define PATHBUF 4096

static void fatal(const wchar_t *text)
{
    MessageBoxW(NULL, text, L"MediaForge", MB_ICONERROR | MB_OK);
}

int WINAPI wWinMain(HINSTANCE hinst, HINSTANCE hprev, PWSTR args, int show)
{
    (void)hinst;
    (void)hprev;
    (void)show;

    wchar_t dir[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, dir, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) {
        fatal(L"Не удалось определить папку программы.");
        return 1;
    }
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash != NULL)
        *slash = L'\0';

    wchar_t python[PATHBUF];
    if (swprintf(python, PATHBUF, L"%s\\python\\pythonw.exe", dir) < 0) {
        fatal(L"Слишком длинный путь к программе.\n\n"
              L"Перенесите папку ближе к корню диска (например, C:\\MediaForge).");
        return 1;
    }
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        fatal(L"Рядом с MediaForge.exe нет папки python.\n\n"
              L"Распакуйте архив целиком — все папки должны лежать вместе.");
        return 1;
    }

    wchar_t data[PATHBUF];
    swprintf(data, PATHBUF, L"%s\\data", dir);
    CreateDirectoryW(data, NULL);

    wchar_t bin[PATHBUF];
    swprintf(bin, PATHBUF, L"%s\\bin", dir);

    SetEnvironmentVariableW(L"MEDIAFORGE_BIN", bin);
    SetEnvironmentVariableW(L"MEDIAFORGE_CONFIG_DIR", data);

    static wchar_t cmd[32768];
    swprintf(cmd, 32768, L"\"%s\" -m mediaforge", python);
    if (args != NULL && args[0] != L'\0') {
        wcscat(cmd, L" ");
        wcscat(cmd, args);
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        fatal(L"Не удалось запустить python\\pythonw.exe.\n\n"
              L"Проверьте, что папка python не повреждена и антивирус её не заблокировал.");
        return 1;
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
