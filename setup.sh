#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SKILL_DIR/.venv"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
CLAUDE_DIR="$HOME/.claude/skills"
CODEX_DIR="$HOME/.codex/skills"
SKILL_NAME="telegram-telethon"

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

printf 'Bootstrapping %s\n' "$SKILL_NAME"
printf '  Source: %s\n' "$SKILL_DIR"

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

mkdir -p "$CLAUDE_DIR" "$CODEX_DIR"
ln -sfn "../../agents/skills/$SKILL_NAME" "$CLAUDE_DIR/$SKILL_NAME"
ln -sfn "../../agents/skills/$SKILL_NAME" "$CODEX_DIR/$SKILL_NAME"

printf '  Virtualenv: %s\n' "$VENV_DIR"
printf '  CLI: %s/tg-telethon\n' "$BIN_DIR"
printf '  Auth helper: %s/tg-telethon-auth-login\n' "$BIN_DIR"
printf '  Logout helper: %s/tg-telethon-auth-logout\n' "$BIN_DIR"
printf '  Claude skill link: %s/%s\n' "$CLAUDE_DIR" "$SKILL_NAME"
printf '  Codex skill link: %s/%s\n' "$CODEX_DIR" "$SKILL_NAME"
printf '\n'
printf 'Next step in a separate shell:\n'
printf '  %s/scripts/auth-login.sh\n' "$SKILL_DIR"
