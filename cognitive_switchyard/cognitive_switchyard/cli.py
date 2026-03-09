from __future__ import annotations

import argparse
from typing import Sequence

from . import BOOTSTRAP_VENV, PACKAGE_NAME, RUNTIME_HOME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PACKAGE_NAME,
        description="Cognitive Switchyard packet-00 scaffold.",
        epilog=(
            f"Canonical runtime home: {RUNTIME_HOME}\n"
            f"Canonical bootstrap venv: {BOOTSTRAP_VENV}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    paths_parser = subparsers.add_parser(
        "paths",
        help="Print canonical runtime paths for the scaffolded package.",
    )
    paths_parser.set_defaults(handler=handle_paths)
    return parser


def handle_paths(_: argparse.Namespace) -> int:
    print(f"package: {PACKAGE_NAME}")
    print(f"runtime home: {RUNTIME_HOME}")
    print(f"bootstrap venv: {BOOTSTRAP_VENV}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))
