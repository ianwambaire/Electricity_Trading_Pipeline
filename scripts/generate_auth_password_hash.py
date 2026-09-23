#!/usr/bin/env python3
"""Generate a PowerFlow authentication password hash without storing a password."""

from __future__ import annotations

import getpass
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from auth import generate_password_hash  # noqa: E402


def main() -> None:
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not password or password != confirmation:
        raise SystemExit("Passwords did not match or were empty; no hash was generated.")
    print(generate_password_hash(password))


if __name__ == "__main__":
    main()
