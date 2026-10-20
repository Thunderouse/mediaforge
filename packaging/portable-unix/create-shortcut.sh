#!/bin/sh
# Добавляет MediaForge в меню приложений текущего пользователя.
# Запускать из папки программы: ./create-shortcut.sh
set -e
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET="$HOME/.local/share/applications/mediaforge.desktop"
ICON="$DIR/icon.png"
mkdir -p "$(dirname "$TARGET")"

cat > "$TARGET" <<EOF
[Desktop Entry]
Type=Application
Name=MediaForge
Comment=Медиаконвертер: видео, GIF, картинки, звук
Exec="$DIR/MediaForge.sh"
Path=$DIR
Icon=${ICON}
Terminal=false
Categories=AudioVideo;Graphics;
EOF

chmod +x "$TARGET"
echo "Ярлык создан: $TARGET"
echo "Если его не видно в меню — выйдите и войдите в сессию заново."
