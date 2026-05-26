from __future__ import annotations

import getpass
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from backend.auth.passwords import hash_password


def run(
    argv: Sequence[str] | None = None,
    *,
    password_reader: Callable[[str], str] = getpass.getpass,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("This tool does not accept password arguments. Enter the password at the hidden prompt.", file=stderr)
        return 2

    password = password_reader("Password: ")
    if not password:
        print("Password must not be empty.", file=stderr)
        return 2

    confirmation = password_reader("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.", file=stderr)
        return 2

    print(hash_password(password), file=stdout)
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
