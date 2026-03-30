# telegram-telethon

`telegram-telethon` is a local Telegram skill and CLI built on Python and Telethon.
It is designed for operator workflows that need structured access to Telegram dialogs and history from the terminal, while keeping credentials in macOS Keychain instead of session files or shell environment variables.

The repository contains two layers:

- an agent-facing skill in `SKILL.md`
- a local CLI that the skill uses for deterministic Telegram operations

## What It Can Do

- bootstrap a local Telethon environment
- authenticate one or more Telegram user accounts
- store `api_id`, `api_hash`, phone, and the Telethon `StringSession` in macOS Keychain
- list Telegram folders
- list dialogs across the account or within a specific folder
- export 1:1 or group chat history to `ndjson` or `json`
- manage multiple account labels through profile commands
- pin an active profile or override it per shell or per agent run

## Requirements

- macOS
- `python3`
- the macOS `security` CLI
- a Telegram user account
- a Telegram `api_id` and `api_hash` from `https://my.telegram.org/apps`

## Bootstrap

Clone the repository and run setup:

```bash
git clone git@github.com:ivanopcode/telegram-telethon.git
cd telegram-telethon
./setup.sh
```

`setup.sh` does the following:

- creates `.venv/`
- installs Python dependencies from `requirements.txt`
- installs local wrapper commands into `~/.local/bin`
- links the skill into `~/.claude/skills/` and `~/.codex/skills/`

Installed wrapper commands:

- `tg-telethon`
- `tg-telethon-auth-login`
- `tg-telethon-auth-logout`

## First-Time Authentication

Run the login helper in a real interactive shell:

```bash
./scripts/auth-login.sh --profile work
```

The helper prompts for:

- `api_id`
- `api_hash`
- phone number
- Telegram login code
- Telegram 2FA password, if enabled

Where to get this information:

- `api_id` and `api_hash`: create an application at `https://my.telegram.org/apps`
- phone number: the Telegram account that this profile should use
- login code: Telegram sends it to the logged-in account during sign-in
- 2FA password: only if Telegram cloud password is enabled on the account

Practical recommendation for `my.telegram.org/apps`:

- use a clean browser session with no extensions or privacy filters on the page
- if the form behaves inconsistently, retry in a different browser profile or a browser with extensions disabled
- keep field values simple and ASCII-only

Field values that have worked well in practice:

- `App title`: `SkillTelethon`
- `Short name`: `tgtelethon`
- `URL`: `https://example.com`
- `Platform`: `Desktop`
- `Description`: `Local Telegram export CLI`

Keep the following values in a reliable password manager:

- `api_id`
- `api_hash`
- the Telegram phone number used for the profile
- the local profile label you assign, for example `work` or `personal`

After a successful login, the tool stores credentials in macOS Keychain.
No Telethon SQLite session file is used.

Check the result:

```bash
tg-telethon profiles current
tg-telethon auth status
```

## Profile Model

A profile is a local label for one Telegram account session.

Examples:

- `work`
- `personal`
- `client-a`
- `research`

Profile selection precedence is:

1. `--profile <name>`
2. `TG_TELETHON_PROFILE=<name>`
3. pinned active profile
4. `default`

Common profile commands:

```bash
tg-telethon profiles list --format table
tg-telethon profiles current
tg-telethon profiles use work
tg-telethon profiles rename work xflow
tg-telethon --profile personal auth status
```

`profiles list` includes the profile label, phone identifier, readiness state, and active marker.

## Daily Usage

List folders:

```bash
tg-telethon folders list --format table
```

List dialogs:

```bash
tg-telethon chats list --format table
tg-telethon chats list --folder-id 247 --format table
tg-telethon chats list --folder-id 247 --archived exclude --format table
```

Export a chat:

```bash
tg-telethon export messages \
  --chat -5118756561 \
  --since 2026-02-17 \
  --output /tmp/xflow.ndjson
```

Export formats:

- `--format ndjson`: best for large histories
- `--format json`: single JSON array

Export schemas:

- `--schema minimal`: compact normalized fields
- `--schema full`: includes a normalized raw Telethon payload

## Agent Environment Examples

This is the recommended format for learning the tool and the skill.
It matches how an agent should discover profile context, find dialogs, and run exports with explicit shell commands.

Inspect the active profile:

```bash
tg-telethon profiles current
tg-telethon profiles list --format table
```

Pin a default profile for later agent runs:

```bash
tg-telethon profiles use work
```

Override the profile for a single shell or agent execution:

```bash
TG_TELETHON_PROFILE=personal tg-telethon chats list --format table
```

Typical discovery flow:

```bash
tg-telethon folders list --format table
tg-telethon chats list --folder-id 247 --format table
```

Typical export flow:

```bash
TG_TELETHON_PROFILE=work tg-telethon export messages \
  --chat -5118756561 \
  --since 2026-02-17 \
  --output /tmp/xflow.ndjson
```

## Logout

Remove only the session:

```bash
tg-telethon --profile work auth logout
```

Remove the entire stored profile:

```bash
tg-telethon --profile work auth logout --all
```

Or use the helper:

```bash
./scripts/auth-logout.sh --profile work --all
```

## Architecture

The repository is intentionally small.

### 1. Skill Layer

`SKILL.md` describes:

- when the skill should be used
- the standing rules for Telegram access
- the supported operator workflows
- the command patterns the agent should prefer

This is the agent-facing contract.

### 2. Bootstrap Layer

`setup.sh` is the only supported bootstrap entrypoint.
It creates the Python environment, installs dependencies, and publishes wrapper commands into the user environment.

### 3. CLI Layer

`scripts/telegram_telethon.py` is the main implementation.
It provides five command groups:

- `profiles`
- `auth`
- `folders`
- `chats`
- `export`

The CLI uses:

- Telethon for Telegram access
- macOS Keychain for secrets
- `~/.config/telegram-telethon/state.json` for non-secret local state such as the pinned active profile and the known profile registry

### 4. Helper Scripts

The shell helpers are thin wrappers:

- `scripts/auth-login.sh`
- `scripts/auth-logout.sh`
- `scripts/tg-telethon`

They exist to make interactive and agent-driven usage predictable.

## Open-Source Attribution

This repository depends on the following open-source software:

- [Telethon](https://github.com/LonamiWebs/Telethon) by Lonami Exo, licensed under the MIT License

The Python standard library is also used throughout the CLI implementation.

This repository is released under the MIT License. See `LICENSE`.

## Repository Layout

```text
telegram-telethon/
├── README.md
├── SKILL.md
├── requirements.txt
├── setup.sh
└── scripts/
    ├── auth-login.sh
    ├── auth-logout.sh
    ├── tg-telethon
    └── telegram_telethon.py
```

## Notes

- Telegram folders are filters, not exclusive containers.
- A dialog can appear in more than one folder.
- Archive is a separate scope.
- Use numeric dialog IDs for exports when possible.

## Development

Syntax checks:

```bash
bash -n setup.sh
bash -n scripts/auth-login.sh
bash -n scripts/auth-logout.sh
python3 -m py_compile scripts/telegram_telethon.py
```

Re-run setup after changing wrappers or dependencies:

```bash
./setup.sh
```
