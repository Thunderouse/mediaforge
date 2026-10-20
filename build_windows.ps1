# Сборка портативного MediaForge для Windows 11 (PowerShell 7+ или Windows PowerShell)
#   .\build_windows.ps1              -> dist\MediaForge\MediaForge.exe
#   .\build_windows.ps1 -WithFFmpeg  -> положить ffmpeg внутрь сборки

param(
    [switch]$WithFFmpeg
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Создаю виртуальное окружение..." -ForegroundColor Cyan
    py -3 -m venv .venv
}
& .\.venv\Scripts\Activate.ps1

Write-Host "Ставлю зависимости..." -ForegroundColor Cyan
python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt pyinstaller

Write-Host "Генерирую иконку..." -ForegroundColor Cyan
python tools\make_icons.py

if ($WithFFmpeg) {
    Write-Host "Скачиваю ffmpeg..." -ForegroundColor Cyan
    python tools\fetch_ffmpeg.py
}

Write-Host "Собираю exe..." -ForegroundColor Cyan
python -m PyInstaller MediaForge.spec --noconfirm --clean

$out = Join-Path $PSScriptRoot "dist\MediaForge"
Write-Host ""
Write-Host "Готово: $out\MediaForge.exe" -ForegroundColor Green
Write-Host "Папку dist\MediaForge можно скопировать на другой компьютер — установка не нужна."
if (-not $WithFFmpeg) {
    Write-Host "ffmpeg не вложен: он должен быть в PATH или в подпапке bin рядом с exe." -ForegroundColor Yellow
}
