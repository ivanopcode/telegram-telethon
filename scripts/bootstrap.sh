#!/usr/bin/env bash
set -euo pipefail

quiet=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet)
      quiet=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$SKILL_DIR/.venv"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'This skill currently targets macOS because it stores Telegram credentials in Keychain.\n' >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  printf 'python3 is required.\n' >&2
  exit 1
fi

if ! command -v security >/dev/null 2>&1; then
  printf 'macOS security CLI is required.\n' >&2
  exit 1
fi

if [[ $quiet -eq 0 ]]; then
  printf 'Bootstrapping telegram-telethon\n'
  printf '  Source: %s\n' "$SKILL_DIR"
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --quiet -r "$SKILL_DIR/requirements.txt"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/tg-telethon" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$SKILL_DIR/scripts/tg-telethon" "\$@"
EOF
chmod +x "$BIN_DIR/tg-telethon"

cat > "$BIN_DIR/tg-telethon-auth-login" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$SKILL_DIR/scripts/auth-login.sh" "\$@"
EOF
chmod +x "$BIN_DIR/tg-telethon-auth-login"

cat > "$BIN_DIR/tg-telethon-auth-logout" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$SKILL_DIR/scripts/auth-logout.sh" "\$@"
EOF
chmod +x "$BIN_DIR/tg-telethon-auth-logout"

if [[ $quiet -eq 0 ]]; then
  printf '  Virtualenv: %s\n' "$VENV_DIR"
  printf '  CLI: %s/tg-telethon\n' "$BIN_DIR"
  printf '  Auth helper: %s/tg-telethon-auth-login\n' "$BIN_DIR"
  printf '  Logout helper: %s/tg-telethon-auth-logout\n' "$BIN_DIR"
  printf '\n'
  printf 'Next step in a separate shell:\n'
  printf '  %s/scripts/auth-login.sh\n' "$SKILL_DIR"
fi
