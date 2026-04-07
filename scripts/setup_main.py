#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from setup_support import (
    SUPPORTED_LOCALE_MODES,
    InstallResult,
    SetupError,
    perform_install,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make install",
        description="Install telegram-telethon into global agent environments.",
    )
    locale_help = (
        "Locale mode for installed metadata. "
        f"Supported: {', '.join(SUPPORTED_LOCALE_MODES)}. "
        "Required on first install, optional on reruns when an install manifest already exists."
    )
    parser.add_argument("--locale", help=locale_help)
    return parser


def print_result(result: InstallResult) -> None:
    print(f"Installed {result.skill_name}")
    print(f"  Source: {result.source_dir}")
    print(f"  Locale: {result.locale_mode}")
    print(f"  Managed copy: {result.runtime_dir}")
    print(f"  Claude skill link: {result.claude_link}")
    print(f"  Codex skill link: {result.codex_link}")
    print()
    print("Next step in a separate shell:")
    print(f"  {result.runtime_dir}/scripts/auth-login.sh")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    current_skill_dir = Path(__file__).resolve().parent.parent

    try:
        result = perform_install(
            source_dir=current_skill_dir,
            requested_locale=args.locale,
        )
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    print_result(result)


if __name__ == "__main__":
    main()
