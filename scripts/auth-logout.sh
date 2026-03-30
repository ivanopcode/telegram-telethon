#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
profile_args=()
pass_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      if [[ $# -lt 2 ]]; then
        printf 'Missing value for --profile.\n' >&2
        exit 1
      fi
      profile_args+=("$1" "$2")
      shift 2
      ;;
    --profile=*)
      profile_args+=("$1")
      shift
      ;;
    *)
      pass_args+=("$1")
      shift
      ;;
  esac
done

exec "$SCRIPT_DIR/tg-telethon" "${profile_args[@]}" auth logout "${pass_args[@]}"
