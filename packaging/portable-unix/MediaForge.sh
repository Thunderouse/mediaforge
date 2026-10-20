#!/bin/sh
# MediaForge — портативный запуск (Linux). Ничего не устанавливает в систему:
# настройки и кэш лежат в папке data/ рядом с этим файлом.
set -e
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DIR"

export MEDIAFORGE_BIN="$DIR/bin"
export MEDIAFORGE_CONFIG_DIR="$DIR/data"
mkdir -p "$DIR/data"

if [ ! -x "$DIR/python/bin/python3" ]; then
    echo "Не найден $DIR/python/bin/python3 — архив распакован не полностью." >&2
    exit 1
fi

PYTHONPATH="$DIR/app${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

exec "$DIR/python/bin/python3" -m mediaforge "$@"
