#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"

if [ "$#" -eq 0 ]; then
  exec python3 "$SCRIPT_DIR/scripts/setup_main.py" --locale en
fi

exec python3 "$SCRIPT_DIR/scripts/setup_main.py" "$@"
