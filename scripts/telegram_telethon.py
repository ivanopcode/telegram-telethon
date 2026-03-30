#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telethon import TelegramClient, functions, utils
from telethon.sessions import StringSession
from telethon.tl.types import DialogFilter, DialogFilterChatlist, DialogFilterDefault


SERVICE_PREFIX = "telegram-telethon"
DEFAULT_PROFILE = "default"
PROFILE_ENV_VAR = "TG_TELETHON_PROFILE"
STATE_PATH = Path.home() / ".config" / SERVICE_PREFIX / "state.json"
LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc


class CLIError(RuntimeError):
    pass


def ensure_macos_keychain() -> None:
    if sys.platform != "darwin":
        raise CLIError("This skill currently supports only macOS Keychain-backed auth.")
    if not shutil_which("security"):
        raise CLIError("macOS security CLI is unavailable.")


def shutil_which(binary: str) -> str | None:
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(path) / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def keychain_service(profile: str) -> str:
    return f"{SERVICE_PREFIX}:{profile}"


def keychain_label(profile: str, key: str) -> str:
    return f"{SERVICE_PREFIX}:{profile}:{key}"


def security_run(*args: str) -> str:
    completed = subprocess.run(
        ["security", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        raise CLIError(output or f"security {' '.join(args)} failed")
    return output


def keychain_get(profile: str, key: str) -> str | None:
    ensure_macos_keychain()
    completed = subprocess.run(
        ["security", "find-generic-password", "-s", keychain_service(profile), "-a", key, "-w"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return (completed.stdout or "").strip() or None
    output = (completed.stderr or completed.stdout or "").strip().lower()
    if "could not be found" in output:
        return None
    raise CLIError(output or f"Failed to read {key} from Keychain.")


def keychain_put(profile: str, key: str, value: str) -> None:
    ensure_macos_keychain()
    subprocess.run(
        ["security", "delete-generic-password", "-s", keychain_service(profile), "-a", key],
        check=False,
        capture_output=True,
        text=True,
    )
    security_run(
        "add-generic-password",
        "-a",
        key,
        "-s",
        keychain_service(profile),
        "-l",
        keychain_label(profile, key),
        "-w",
        value,
    )


def keychain_delete(profile: str, key: str) -> bool:
    ensure_macos_keychain()
    completed = subprocess.run(
        ["security", "delete-generic-password", "-s", keychain_service(profile), "-a", key],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return True
    output = (completed.stderr or completed.stdout or "").strip().lower()
    if "could not be found" in output:
        return False
    raise CLIError(output or f"Failed to delete {key} from Keychain.")


def load_state() -> dict[str, Any]:
    state: dict[str, Any] = {"active_profile": None, "profiles": []}
    if STATE_PATH.exists():
        try:
            loaded = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CLIError(f"State file is invalid JSON: {STATE_PATH}") from exc
        if isinstance(loaded, dict):
            profiles = loaded.get("profiles", [])
            if isinstance(profiles, list):
                state["profiles"] = [str(item).strip() for item in profiles if str(item).strip()]
            active_profile = loaded.get("active_profile")
            if isinstance(active_profile, str) and active_profile.strip():
                state["active_profile"] = active_profile.strip()

    normalized_profiles: list[str] = []
    for profile in state["profiles"]:
        if profile not in normalized_profiles:
            normalized_profiles.append(profile)
    state["profiles"] = normalized_profiles
    return state


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_profile": state.get("active_profile"),
        "profiles": state.get("profiles", []),
    }
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def profile_has_any_credentials(profile: str) -> bool:
    return any(keychain_get(profile, key) for key in ("api_id", "api_hash", "phone", "session"))


def ensure_registry_bootstrap() -> dict[str, Any]:
    state = load_state()
    changed = False
    if DEFAULT_PROFILE not in state["profiles"] and profile_has_any_credentials(DEFAULT_PROFILE):
        state["profiles"].append(DEFAULT_PROFILE)
        changed = True
    if not state["active_profile"] and profile_has_any_credentials(DEFAULT_PROFILE):
        state["active_profile"] = DEFAULT_PROFILE
        changed = True
    if changed:
        save_state(state)
    return state


def register_profile(profile: str) -> None:
    state = ensure_registry_bootstrap()
    if profile not in state["profiles"]:
        state["profiles"].append(profile)
        save_state(state)


def unregister_profile(profile: str) -> None:
    state = ensure_registry_bootstrap()
    if profile in state["profiles"]:
        state["profiles"] = [item for item in state["profiles"] if item != profile]
    if state.get("active_profile") == profile:
        state["active_profile"] = state["profiles"][0] if state["profiles"] else None
    save_state(state)


def set_active_profile(profile: str | None) -> None:
    state = ensure_registry_bootstrap()
    if profile is not None and profile not in state["profiles"]:
        state["profiles"].append(profile)
    state["active_profile"] = profile
    save_state(state)


def get_active_profile() -> str | None:
    return ensure_registry_bootstrap().get("active_profile")


def sync_profile_registry(profile: str) -> None:
    if profile_has_any_credentials(profile):
        register_profile(profile)


def profile_exists(profile: str) -> bool:
    state = ensure_registry_bootstrap()
    return profile in state.get("profiles", []) or profile_has_any_credentials(profile)


def resolve_profile(cli_profile: str | None) -> tuple[str, str]:
    if cli_profile:
        return cli_profile, "flag"
    env_profile = os.environ.get(PROFILE_ENV_VAR, "").strip()
    if env_profile:
        return env_profile, "env"
    active_profile = get_active_profile()
    if active_profile:
        return active_profile, "active"
    return DEFAULT_PROFILE, "default"


def profile_record(profile: str, *, selected: bool = False) -> dict[str, Any]:
    api_id = keychain_get(profile, "api_id")
    api_hash = keychain_get(profile, "api_hash")
    phone = keychain_get(profile, "phone")
    session = keychain_get(profile, "session")
    return {
        "profile": profile,
        "phone": phone,
        "has_api_id": bool(api_id),
        "has_api_hash": bool(api_hash),
        "has_phone": bool(phone),
        "has_session": bool(session),
        "ready": bool(api_id and api_hash and session),
        "active": get_active_profile() == profile,
        "selected": selected,
    }


def prompt_text(prompt: str, *, secret: bool = False) -> str:
    if not sys.stdin.isatty():
        raise CLIError("This command requires an interactive TTY.")
    if secret:
        return getpass.getpass(prompt).strip()
    return input(prompt).strip()


def required_secret(profile: str, key: str) -> str:
    value = keychain_get(profile, key)
    if not value:
        raise CLIError(
            f"Missing Keychain value '{key}' for profile '{profile}'. "
            f"Run scripts/auth-login.sh in a separate shell first."
        )
    return value


def print_json(data: Any) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"_type": "bytes", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize(v) for v in value]
    if hasattr(value, "to_dict"):
        return normalize(value.to_dict())
    return str(value)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CLIError(
            f"Unsupported datetime '{value}'. Use ISO 8601 like 2026-03-01 or 2026-03-01T09:30:00+04:00."
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc)


def as_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def title_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = getattr(value, "text", None)
    if text is not None:
        return text
    return str(value)


def peer_ids(peers: list[Any] | None) -> list[int]:
    results: list[int] = []
    for peer in peers or []:
        try:
            results.append(utils.get_peer_id(peer))
        except Exception:
            continue
    return results


def dialog_kind(dialog: Any) -> str:
    entity = dialog.entity
    if dialog.is_user and getattr(entity, "bot", False):
        return "bot"
    if dialog.is_user:
        return "user"
    if dialog.is_group:
        return "group"
    if dialog.is_channel:
        return "channel"
    return type(entity).__name__


def is_dialog_muted(dialog: Any) -> bool:
    settings = getattr(dialog.dialog, "notify_settings", None)
    mute_until = getattr(settings, "mute_until", None)
    if mute_until is None:
        return False
    if mute_until.tzinfo is None:
        mute_until = mute_until.replace(tzinfo=timezone.utc)
    return mute_until > datetime.now(timezone.utc)


def dialog_matches_filter(dialog: Any, folder: Any) -> bool:
    dialog_id = dialog.id
    pinned_ids = set(peer_ids(getattr(folder, "pinned_peers", None)))
    include_ids = set(peer_ids(getattr(folder, "include_peers", None)))
    exclude_ids = set(peer_ids(getattr(folder, "exclude_peers", None)))

    if dialog_id in exclude_ids:
        return False

    included = dialog_id in pinned_ids or dialog_id in include_ids

    if isinstance(folder, DialogFilter):
        entity = dialog.entity
        if getattr(folder, "contacts", False) and dialog.is_user and not getattr(entity, "bot", False) and getattr(entity, "contact", False):
            included = True
        if getattr(folder, "non_contacts", False) and dialog.is_user and not getattr(entity, "bot", False) and not getattr(entity, "contact", False):
            included = True
        if getattr(folder, "groups", False) and dialog.is_group:
            included = True
        if getattr(folder, "broadcasts", False) and dialog.is_channel and not getattr(entity, "megagroup", False):
            included = True
        if getattr(folder, "bots", False) and getattr(entity, "bot", False):
            included = True
        if getattr(folder, "exclude_muted", False) and is_dialog_muted(dialog):
            return False
        if getattr(folder, "exclude_read", False) and dialog.unread_count == 0 and dialog.unread_mentions_count == 0:
            return False
        if getattr(folder, "exclude_archived", False) and dialog.archived:
            return False
    elif isinstance(folder, DialogFilterChatlist):
        return included

    return included


def folder_to_record(folder: Any) -> dict[str, Any]:
    if isinstance(folder, DialogFilterDefault):
        return {"kind": "default"}

    base = {
        "id": getattr(folder, "id", None),
        "kind": type(folder).__name__,
        "title": title_to_text(getattr(folder, "title", None)),
        "emoticon": getattr(folder, "emoticon", None),
        "color": getattr(folder, "color", None),
        "pinned_peer_ids": peer_ids(getattr(folder, "pinned_peers", None)),
        "include_peer_ids": peer_ids(getattr(folder, "include_peers", None)),
    }

    if isinstance(folder, DialogFilter):
        base.update(
            {
                "exclude_peer_ids": peer_ids(getattr(folder, "exclude_peers", None)),
                "rules": {
                    "contacts": bool(getattr(folder, "contacts", False)),
                    "non_contacts": bool(getattr(folder, "non_contacts", False)),
                    "groups": bool(getattr(folder, "groups", False)),
                    "broadcasts": bool(getattr(folder, "broadcasts", False)),
                    "bots": bool(getattr(folder, "bots", False)),
                    "exclude_muted": bool(getattr(folder, "exclude_muted", False)),
                    "exclude_read": bool(getattr(folder, "exclude_read", False)),
                    "exclude_archived": bool(getattr(folder, "exclude_archived", False)),
                },
            }
        )
    elif isinstance(folder, DialogFilterChatlist):
        base.update({"has_my_invites": bool(getattr(folder, "has_my_invites", False))})

    return base


def folder_table(records: list[dict[str, Any]]) -> None:
    print("id\ttitle\tkind\temoticon\tinclude_peers\texclude_peers")
    for record in records:
        print(
            "\t".join(
                [
                    str(record.get("id", "")),
                    str(record.get("title", "") or ""),
                    str(record.get("kind", "") or ""),
                    str(record.get("emoticon", "") or ""),
                    str(len(record.get("include_peer_ids", []) or [])),
                    str(len(record.get("exclude_peer_ids", []) or [])),
                ]
            )
        )


def chat_table(records: list[dict[str, Any]]) -> None:
    print("id\ttitle\ttype\tusername\tarchived\tfolders\tunread")
    for record in records:
        print(
            "\t".join(
                [
                    str(record.get("id", "")),
                    str(record.get("title", "") or ""),
                    str(record.get("kind", "") or ""),
                    str(record.get("username", "") or ""),
                    "yes" if record.get("archived") else "no",
                    ",".join(str(folder_id) for folder_id in record.get("folder_ids", [])),
                    str(record.get("unread_count", 0)),
                ]
            )
        )


def profile_table(records: list[dict[str, Any]]) -> None:
    print("active\tselected\tprofile\tphone\tready\thas_session")
    for record in records:
        print(
            "\t".join(
                [
                    "*" if record.get("active") else "",
                    ">" if record.get("selected") else "",
                    str(record.get("profile", "")),
                    str(record.get("phone", "") or ""),
                    "yes" if record.get("ready") else "no",
                    "yes" if record.get("has_session") else "no",
                ]
            )
        )


async def authorized_client(profile: str) -> TelegramClient:
    api_id = int(required_secret(profile, "api_id"))
    api_hash = required_secret(profile, "api_hash")
    session = required_secret(profile, "session")
    client = TelegramClient(StringSession(session), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise CLIError(
            f"Profile '{profile}' has a stored session but it is no longer authorized. "
            f"Run scripts/auth-login.sh in a separate shell again."
        )
    return client


async def auth_login(args: argparse.Namespace) -> None:
    profile = args.profile
    api_id = args.api_id or keychain_get(profile, "api_id") or prompt_text("Telegram api_id: ")
    api_hash = args.api_hash or keychain_get(profile, "api_hash") or prompt_text("Telegram api_hash: ", secret=True)
    phone = args.phone or keychain_get(profile, "phone") or prompt_text("Telegram phone (+...): ")
    existing_session = None if args.force else keychain_get(profile, "session")

    client = TelegramClient(StringSession(existing_session or ""), int(api_id), api_hash)
    try:
        await client.start(
            phone=lambda: phone,
            password=lambda: getpass.getpass("Telegram 2FA password: "),
            code_callback=lambda: prompt_text("Telegram login code: "),
            max_attempts=3,
        )
        me = await client.get_me()
        if me is None:
            raise CLIError("Telegram login completed but account info was not returned.")
        session_string = StringSession.save(client.session)
    finally:
        await client.disconnect()

    keychain_put(profile, "api_id", str(api_id))
    keychain_put(profile, "api_hash", api_hash)
    keychain_put(profile, "phone", phone)
    keychain_put(profile, "session", session_string)
    register_profile(profile)
    set_active_profile(profile)

    print_json(
        {
            "profile": profile,
            "profile_source": getattr(args, "profile_source", None),
            "authorized": True,
            "user": {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "phone": me.phone,
            },
        }
    )


async def auth_status(args: argparse.Namespace) -> None:
    profile = args.profile
    sync_profile_registry(profile)
    status = {
        "profile": profile,
        "profile_source": getattr(args, "profile_source", None),
        "has_api_id": bool(keychain_get(profile, "api_id")),
        "has_api_hash": bool(keychain_get(profile, "api_hash")),
        "has_phone": bool(keychain_get(profile, "phone")),
        "has_session": bool(keychain_get(profile, "session")),
        "active": get_active_profile() == profile,
        "authorized": False,
        "user": None,
    }

    if not status["has_api_id"] or not status["has_api_hash"] or not status["has_session"]:
        print_json(status)
        return

    client = await authorized_client(profile)
    try:
        me = await client.get_me()
        status["authorized"] = me is not None
        if me is not None:
            status["user"] = {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "phone": me.phone,
            }
    finally:
        await client.disconnect()

    print_json(status)


async def auth_logout(args: argparse.Namespace) -> None:
    profile = args.profile
    keys = ["session"]
    if args.all:
        keys = ["session", "phone", "api_hash", "api_id"]

    removed = {key: keychain_delete(profile, key) for key in keys}
    if args.all:
        unregister_profile(profile)
    print_json({"profile": profile, "removed": removed})


async def profiles_list(args: argparse.Namespace) -> None:
    state = ensure_registry_bootstrap()
    selected_profile = args.profile
    profiles = state.get("profiles", [])
    if selected_profile not in profiles and profile_has_any_credentials(selected_profile):
        register_profile(selected_profile)
        state = ensure_registry_bootstrap()
        profiles = state.get("profiles", [])

    records = [profile_record(profile, selected=profile == selected_profile) for profile in profiles]
    if args.format == "table":
        profile_table(records)
        return
    print_json(records)


async def profiles_current(args: argparse.Namespace) -> None:
    sync_profile_registry(args.profile)
    record = profile_record(args.profile, selected=True)
    record["profile_source"] = getattr(args, "profile_source", None)
    print_json(record)


async def profiles_use(args: argparse.Namespace) -> None:
    target = args.target
    if not profile_has_any_credentials(target):
        raise CLIError(
            f"Profile '{target}' has no stored Telegram credentials. "
            f"Login first with 'scripts/auth-login.sh --profile {target}'."
        )
    register_profile(target)
    set_active_profile(target)
    record = profile_record(target, selected=True)
    record["profile_source"] = "active"
    print_json(record)


async def profiles_rename(args: argparse.Namespace) -> None:
    source = args.source.strip()
    target = args.target.strip()
    if not source or not target:
        raise CLIError("Source and target profile names are required.")
    if source == target:
        record = profile_record(source, selected=(get_active_profile() == source))
        record["renamed"] = False
        print_json(record)
        return
    if not profile_exists(source):
        raise CLIError(f"Profile '{source}' was not found.")
    if profile_exists(target):
        raise CLIError(f"Profile '{target}' already exists.")

    keys = ("api_id", "api_hash", "phone", "session")
    values = {key: keychain_get(source, key) for key in keys}
    if not any(values.values()):
        raise CLIError(f"Profile '{source}' has no stored credentials to rename.")

    for key, value in values.items():
        if value:
            keychain_put(target, key, value)

    for key, value in values.items():
        if value:
            keychain_delete(source, key)

    state = ensure_registry_bootstrap()
    profiles = [target if item == source else item for item in state.get("profiles", [])]
    if source not in state.get("profiles", []) and target not in profiles:
        profiles.append(target)

    deduped_profiles: list[str] = []
    for profile in profiles:
        if profile not in deduped_profiles:
            deduped_profiles.append(profile)
    state["profiles"] = deduped_profiles

    if state.get("active_profile") == source:
        state["active_profile"] = target
    save_state(state)

    record = profile_record(target, selected=(state.get("active_profile") == target))
    record["renamed"] = True
    record["from"] = source
    print_json(record)


async def load_folder_records(client: TelegramClient) -> tuple[list[Any], list[dict[str, Any]]]:
    raw_filters = await client(functions.messages.GetDialogFiltersRequest())
    filter_items = getattr(raw_filters, "filters", raw_filters)
    usable_filters = [folder for folder in filter_items if isinstance(folder, (DialogFilter, DialogFilterChatlist))]
    records = [folder_to_record(folder) for folder in usable_filters]
    return usable_filters, records


async def folders_list(args: argparse.Namespace) -> None:
    client = await authorized_client(args.profile)
    try:
        _, records = await load_folder_records(client)
    finally:
        await client.disconnect()

    if args.format == "table":
        folder_table(records)
        return
    print_json(records)


def dialog_to_record(dialog: Any, folder_matches: list[dict[str, Any]]) -> dict[str, Any]:
    entity = dialog.entity
    return {
        "id": dialog.id,
        "title": dialog.title,
        "kind": dialog_kind(dialog),
        "username": getattr(entity, "username", None),
        "archived": dialog.archived,
        "pinned": dialog.pinned,
        "folder_ids": [match["id"] for match in folder_matches],
        "folders": folder_matches,
        "unread_count": dialog.unread_count,
        "unread_mentions_count": dialog.unread_mentions_count,
        "muted": is_dialog_muted(dialog),
        "top_message_date": as_iso(dialog.date),
    }


async def chats_list(args: argparse.Namespace) -> None:
    client = await authorized_client(args.profile)
    try:
        folders, folder_records = await load_folder_records(client)
        folder_map = {record["id"]: folder for folder, record in zip(folders, folder_records)}
        folder_title_map = {record["id"]: record["title"] for record in folder_records}
        dialogs = await client.get_dialogs(limit=None)
    finally:
        await client.disconnect()

    requested_folder = None
    if args.folder_id is not None:
        requested_folder = folder_map.get(args.folder_id)
        if requested_folder is None:
            raise CLIError(f"Folder id {args.folder_id} was not found. Run 'tg-telethon folders list' first.")

    query = (args.query or "").strip().lower()
    results: list[dict[str, Any]] = []
    for dialog in dialogs:
        if args.archived == "only" and not dialog.archived:
            continue
        if args.archived == "exclude" and dialog.archived:
            continue

        title = dialog.title or ""
        username = getattr(dialog.entity, "username", "") or ""
        if query and query not in title.lower() and query not in username.lower():
            continue

        matches = []
        for record in folder_records:
            folder = folder_map[record["id"]]
            if dialog_matches_filter(dialog, folder):
                matches.append({"id": record["id"], "title": folder_title_map[record["id"]]})

        if requested_folder is not None and not any(match["id"] == args.folder_id for match in matches):
            continue

        results.append(dialog_to_record(dialog, matches))

    if args.limit is not None:
        results = results[: args.limit]

    if args.format == "table":
        chat_table(results)
        return
    print_json(results)


async def resolve_chat(client: TelegramClient, chat_spec: str) -> tuple[Any, dict[str, Any]]:
    dialogs = await client.get_dialogs(limit=None)
    raw = chat_spec.strip()

    if raw.lstrip("-").isdigit():
        peer_id = int(raw)
        for dialog in dialogs:
            if dialog.id == peer_id:
                return dialog.input_entity, {"id": dialog.id, "title": dialog.title}

    lowered = raw.lower()
    exact_matches = []
    fuzzy_matches = []
    for dialog in dialogs:
        username = (getattr(dialog.entity, "username", "") or "").lower()
        title = (dialog.title or "").lower()
        if lowered == title or lowered == username or lowered == f"@{username}":
            exact_matches.append(dialog)
        elif lowered in title or (username and lowered in username):
            fuzzy_matches.append(dialog)

    if len(exact_matches) == 1:
        dialog = exact_matches[0]
        return dialog.input_entity, {"id": dialog.id, "title": dialog.title}

    if len(exact_matches) > 1:
        raise CLIError(
            "More than one dialog matched exactly. Use the numeric dialog id from 'tg-telethon chats list'."
        )

    if len(fuzzy_matches) == 1:
        dialog = fuzzy_matches[0]
        return dialog.input_entity, {"id": dialog.id, "title": dialog.title}

    if len(fuzzy_matches) > 1:
        suggestions = [{"id": dialog.id, "title": dialog.title} for dialog in fuzzy_matches[:10]]
        raise CLIError(
            "More than one dialog matched the query. Use a numeric dialog id. "
            f"Candidates: {json.dumps(suggestions, ensure_ascii=False)}"
        )

    try:
        entity = await client.get_input_entity(raw)
        return entity, {"id": raw, "title": raw}
    except Exception as exc:
        raise CLIError(
            f"Could not resolve chat '{chat_spec}'. Run 'tg-telethon chats list --format table' to find the dialog id."
        ) from exc


def message_media_summary(message: Any) -> dict[str, Any] | None:
    media = getattr(message, "media", None)
    file = getattr(message, "file", None)
    if media is None and file is None:
        return None
    return {
        "kind": type(media).__name__ if media is not None else None,
        "file_name": getattr(file, "name", None),
        "mime_type": getattr(file, "mime_type", None),
        "size": getattr(file, "size", None),
        "duration": getattr(file, "duration", None),
        "width": getattr(file, "width", None),
        "height": getattr(file, "height", None),
    }


def minimal_message_record(message: Any) -> dict[str, Any]:
    reply_to = getattr(message, "reply_to", None)
    return {
        "id": message.id,
        "date": as_iso(message.date),
        "edit_date": as_iso(getattr(message, "edit_date", None)),
        "chat_id": message.chat_id,
        "sender_id": message.sender_id,
        "reply_to_msg_id": getattr(reply_to, "reply_to_msg_id", None),
        "text": message.text,
        "post_author": getattr(message, "post_author", None),
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "grouped_id": getattr(message, "grouped_id", None),
        "media": message_media_summary(message),
    }


def full_message_record(message: Any) -> dict[str, Any]:
    record = minimal_message_record(message)
    record["raw"] = normalize(message.to_dict())
    return record


def emit_json_records(records: list[dict[str, Any]], output: Path | None) -> None:
    payload = json.dumps(records, ensure_ascii=False, indent=2)
    if output is None:
        sys.stdout.write(payload)
        sys.stdout.write("\n")
        return
    output.write_text(payload + "\n", encoding="utf-8")


async def export_messages(args: argparse.Namespace) -> None:
    since = parse_datetime(args.since)
    until = parse_datetime(args.until)
    if since and until and since > until:
        raise CLIError("--since must be earlier than or equal to --until.")

    client = await authorized_client(args.profile)
    try:
        entity, chat_meta = await resolve_chat(client, args.chat)
        serializer = full_message_record if args.schema == "full" else minimal_message_record
        output_path = Path(args.output).expanduser() if args.output else None
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)

        record_count = 0
        json_records: list[dict[str, Any]] = []
        ndjson_handle = None
        if args.format == "ndjson":
            ndjson_handle = sys.stdout if output_path is None else output_path.open("w", encoding="utf-8")

        try:
            async for message in client.iter_messages(entity, limit=args.limit, reverse=True, offset_date=since):
                if since and message.date and message.date < since:
                    continue
                if until and message.date and message.date > until:
                    break

                record = serializer(message)
                if args.format == "json":
                    json_records.append(record)
                else:
                    assert ndjson_handle is not None
                    ndjson_handle.write(json.dumps(record, ensure_ascii=False))
                    ndjson_handle.write("\n")
                record_count += 1
        finally:
            if output_path is not None and ndjson_handle is not None:
                ndjson_handle.close()
    finally:
        await client.disconnect()

    if args.format == "json":
        emit_json_records(json_records, output_path)

    summary = {
        "chat": chat_meta,
        "messages_exported": record_count,
        "format": args.format,
        "schema": args.schema,
        "since": as_iso(since),
        "until": as_iso(until),
        "output": str(output_path) if output_path is not None else "stdout",
    }
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tg-telethon")
    parser.add_argument(
        "--profile",
        help=f"Profile name. Precedence: flag > {PROFILE_ENV_VAR} > pinned active profile > {DEFAULT_PROFILE}.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profiles_parser = subparsers.add_parser("profiles", help="List and pin Telegram profiles")
    profiles_subparsers = profiles_parser.add_subparsers(dest="profiles_command", required=True)

    profiles_list_parser = profiles_subparsers.add_parser("list", help="List known profiles")
    profiles_list_parser.add_argument("--format", choices=["json", "table"], default="json")
    profiles_list_parser.set_defaults(handler=profiles_list)

    profiles_current_parser = profiles_subparsers.add_parser("current", help="Show the currently selected profile")
    profiles_current_parser.set_defaults(handler=profiles_current)

    profiles_use_parser = profiles_subparsers.add_parser("use", help="Pin a profile as the active default")
    profiles_use_parser.add_argument("target", help="Profile name to pin as active.")
    profiles_use_parser.set_defaults(handler=profiles_use)

    profiles_rename_parser = profiles_subparsers.add_parser("rename", help="Rename a stored profile label")
    profiles_rename_parser.add_argument("source", help="Existing profile name.")
    profiles_rename_parser.add_argument("target", help="New profile name.")
    profiles_rename_parser.set_defaults(handler=profiles_rename)

    auth_parser = subparsers.add_parser("auth", help="Telegram auth and Keychain session management")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)

    auth_login_parser = auth_subparsers.add_parser("login", help="Interactive one-time login stored in Keychain")
    auth_login_parser.add_argument("--api-id", help="Telegram api_id. If omitted, read from Keychain or prompt.")
    auth_login_parser.add_argument("--api-hash", help="Telegram api_hash. If omitted, read from Keychain or prompt.")
    auth_login_parser.add_argument("--phone", help="Telegram phone number. If omitted, read from Keychain or prompt.")
    auth_login_parser.add_argument("--force", action="store_true", help="Ignore any existing session and re-login.")
    auth_login_parser.set_defaults(handler=auth_login)

    auth_status_parser = auth_subparsers.add_parser("status", help="Show whether the profile is authenticated")
    auth_status_parser.set_defaults(handler=auth_status)

    auth_logout_parser = auth_subparsers.add_parser("logout", help="Remove session from Keychain")
    auth_logout_parser.add_argument("--all", action="store_true", help="Also remove api_id, api_hash and phone.")
    auth_logout_parser.set_defaults(handler=auth_logout)

    folders_parser = subparsers.add_parser("folders", help="List Telegram chat folders")
    folders_subparsers = folders_parser.add_subparsers(dest="folders_command", required=True)
    folders_list_parser = folders_subparsers.add_parser("list", help="List Telegram chat folders")
    folders_list_parser.add_argument("--format", choices=["json", "table"], default="json")
    folders_list_parser.set_defaults(handler=folders_list)

    chats_parser = subparsers.add_parser("chats", help="List accessible dialogs")
    chats_subparsers = chats_parser.add_subparsers(dest="chats_command", required=True)
    chats_list_parser = chats_subparsers.add_parser("list", help="List dialogs and their ids")
    chats_list_parser.add_argument("--folder-id", type=int, help="Return only dialogs matching the given Telegram folder id.")
    chats_list_parser.add_argument(
        "--archived",
        choices=["all", "only", "exclude"],
        default="all",
        help="Filter by archived scope. Default: all.",
    )
    chats_list_parser.add_argument("--query", help="Optional substring filter on title or username.")
    chats_list_parser.add_argument("--limit", type=int, help="Optional maximum number of dialogs to print.")
    chats_list_parser.add_argument("--format", choices=["json", "table"], default="json")
    chats_list_parser.set_defaults(handler=chats_list)

    export_parser = subparsers.add_parser("export", help="Export Telegram history")
    export_subparsers = export_parser.add_subparsers(dest="export_command", required=True)
    export_messages_parser = export_subparsers.add_parser("messages", help="Export messages from a dialog")
    export_messages_parser.add_argument("--chat", required=True, help="Dialog id, username, or exact dialog title.")
    export_messages_parser.add_argument("--since", help="Inclusive start datetime in ISO 8601.")
    export_messages_parser.add_argument("--until", help="Inclusive end datetime in ISO 8601.")
    export_messages_parser.add_argument("--limit", type=int, help="Optional maximum number of messages.")
    export_messages_parser.add_argument("--output", help="Output file path. Omit for stdout.")
    export_messages_parser.add_argument("--format", choices=["ndjson", "json"], default="ndjson")
    export_messages_parser.add_argument("--schema", choices=["minimal", "full"], default="minimal")
    export_messages_parser.set_defaults(handler=export_messages)

    return parser


async def async_main() -> int:
    ensure_macos_keychain()
    parser = build_parser()
    args = parser.parse_args()
    args.profile, args.profile_source = resolve_profile(getattr(args, "profile", None))
    sync_profile_registry(args.profile)
    await args.handler(args)
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except CLIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
