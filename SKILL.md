---
name: telegram-telethon
description: Access Telegram user chats through Python + Telethon with macOS Keychain-backed auth. Use when you need a local Telegram CLI to bootstrap one-time login, list chat folders and dialogs, find dialog IDs, or export 1:1/group chat history to NDJSON/JSON since a date or over the full accessible history.
triggers:
  - telethon
  - telegram export
  - telegram chat export
  - telegram history export
  - telegram dialog list
  - telegram folder list
  - telegram keychain auth
  - выгрузка телеграм
  - экспорт телеграм
  - история телеграм чата
  - список чатов телеграм
  - папки телеграм
---

# Telegram Telethon

Use this skill for local Telegram read/export workflows on macOS when Telegram user auth must stay in Keychain instead of files or shell env.

## Standing Rules

- Use a real user account through Telethon/MTProto, not the Bot API.
- Keep `api_id`, `api_hash`, phone, and the Telethon `StringSession` in macOS Keychain.
- Keep the active profile selection in local state and allow per-shell/per-agent override through `TG_TELETHON_PROFILE`.
- Do not write Telegram session SQLite files, plaintext tokens, or secrets into repo files or shell rc files.
- Run the first login in a separate shell with `scripts/auth-login.sh`.
- Prefer `ndjson` for exports. Use `json` only when the result set is small enough to hold in memory.
- Telegram chat folders are filters, not exclusive containers. A chat may match multiple folders. Archive is a separate scope.

## Quick Start

```bash
cd ~/agents/skills/telegram-telethon
./setup.sh
```

Open a separate shell and authenticate once:

```bash
~/agents/skills/telegram-telethon/scripts/auth-login.sh
```

After login, use the installed CLI from anywhere:

```bash
tg-telethon profiles current
tg-telethon profiles list --format table
tg-telethon profiles use work
tg-telethon folders list --format table
tg-telethon chats list --format table
tg-telethon chats list --folder-id 3 --format table
tg-telethon export messages --chat -1001234567890 --since 2026-03-01 --output chat.ndjson
```

`api_id` and `api_hash` come from `https://my.telegram.org` under API Development Tools.

## Primary Use Cases

- Bootstrap local Telegram access once and keep credentials in Keychain.
- List Telegram chat folders with their filter IDs and rules.
- List all dialogs, or only dialogs matching a specific folder filter.
- Find a stable dialog ID before export.
- Export 1:1 or group chat history since a specific date or over the full accessible history.

## Commands

Bootstrap and auth:

```bash
./setup.sh
scripts/auth-login.sh
scripts/auth-login.sh --profile work
scripts/auth-logout.sh --profile work
tg-telethon profiles list --format table
tg-telethon profiles current
tg-telethon profiles use work
tg-telethon profiles rename work xflow
tg-telethon auth status
tg-telethon auth logout
tg-telethon auth logout --all
tg-telethon --profile work auth status
```

Folder and chat discovery:

```bash
tg-telethon folders list --format table
tg-telethon folders list --format json
tg-telethon chats list --format table
tg-telethon chats list --query project --format table
tg-telethon chats list --folder-id 3 --archived exclude --format table
TG_TELETHON_PROFILE=work tg-telethon chats list --format table
```

History export:

```bash
tg-telethon export messages --chat -1001234567890 --output all.ndjson
tg-telethon export messages --chat "My Group" --since 2026-03-01 --output from-date.ndjson
tg-telethon export messages --chat @channelusername --since 2026-03-01T09:00:00+04:00 --until 2026-03-10 --format json --schema full --output slice.json
```

## Output Notes

- `folders list` returns folder filter metadata. The `id` field is the value to pass into `chats list --folder-id`.
- `chats list` returns Telegram peer IDs that can be passed into `export messages --chat`.
- `profiles list` returns registered profile names, phone identifiers, and whether a profile is currently pinned active.
- `profiles rename <old> <new>` moves stored Keychain credentials and the registry label to a new profile name without re-login.
- `export messages` supports:
  - `--format ndjson`: one JSON object per line, best for large exports
  - `--format json`: a single JSON array
  - `--schema minimal`: compact export
  - `--schema full`: keeps a normalized raw Telethon payload under `raw`

## Agent Workflow

1. Ensure the skill has been bootstrapped with `./setup.sh`.
2. If auth is missing, instruct the user to run `scripts/auth-login.sh` in a separate shell.
3. Resolve the profile context first:
   - use `tg-telethon profiles current` to inspect the pinned active profile
   - use `tg-telethon profiles use <name>` to pin a different default profile
   - or set `TG_TELETHON_PROFILE=<name>` for the current shell/agent run without changing the pinned default
4. Use `tg-telethon folders list` and `tg-telethon chats list` to find the target peer ID.
5. Export with `tg-telethon export messages`, usually to `ndjson`.
6. If the user needs richer downstream analysis, rerun export with `--schema full`.
