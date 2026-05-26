from __future__ import annotations

import io
import unittest

from backend.auth.password_hash_cli import run
from backend.auth.passwords import verify_password


class PasswordHashCliTest(unittest.TestCase):
    def test_generates_verifiable_hash_without_echoing_password(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        reader = PasswordReader("correct horse battery staple", "correct horse battery staple")

        exit_code = run([], password_reader=reader, stdout=stdout, stderr=stderr)

        password_hash = stdout.getvalue().strip()
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("correct horse battery staple", stdout.getvalue())
        self.assertEqual(reader.prompts, ["Password: ", "Confirm password: "])
        self.assertTrue(verify_password("correct horse battery staple", password_hash))

    def test_rejects_mismatched_confirmation(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run([], password_reader=PasswordReader("first", "second"), stdout=stdout, stderr=stderr)

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Passwords do not match.", stderr.getvalue())

    def test_rejects_empty_password(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        reader = PasswordReader("")

        exit_code = run([], password_reader=reader, stdout=stdout, stderr=stderr)

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(reader.prompts, ["Password: "])
        self.assertIn("Password must not be empty.", stderr.getvalue())

    def test_rejects_password_as_command_line_argument(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        reader = PasswordReader("unused", "unused")

        exit_code = run(["secret"], password_reader=reader, stdout=stdout, stderr=stderr)

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(reader.prompts, [])
        self.assertIn("does not accept password arguments", stderr.getvalue())


class PasswordReader:
    def __init__(self, *passwords: str) -> None:
        self._passwords = list(passwords)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._passwords:
            raise AssertionError("Unexpected password prompt")
        return self._passwords.pop(0)


if __name__ == "__main__":
    unittest.main()
