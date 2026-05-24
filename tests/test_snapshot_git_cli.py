from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.snapshot.git_cli import GitCommandRunner
from backend.snapshot.models import SnapshotBuildError


class GitCommandRunnerTest(unittest.TestCase):
    def test_clone_mirror_rejects_repository_url_with_userinfo(self) -> None:
        runner = GitCommandRunner()

        with (
            patch("backend.snapshot.git_cli.subprocess.run") as run_mock,
            self.assertRaisesRegex(SnapshotBuildError, "credentials"),
        ):
            runner.clone_mirror(
                "https://token123@github.com/example/private.git",
                Path("repo.git"),
                timeout_seconds=30,
            )

        run_mock.assert_not_called()

    def test_run_rejects_repository_url_with_userinfo_before_git_is_spawned(self) -> None:
        runner = GitCommandRunner()

        with (
            patch("backend.snapshot.git_cli.subprocess.run") as run_mock,
            self.assertRaisesRegex(SnapshotBuildError, "credentials"),
        ):
            runner.run(
                ["clone", "https://token123@github.com/example/private.git", "repo.git"],
                timeout_seconds=30,
            )

        run_mock.assert_not_called()

    def test_clone_mirror_rejects_repository_url_query_and_fragment_before_git_is_spawned(self) -> None:
        runner = GitCommandRunner()

        for repository_url in (
            "https://github.com/example/private.git?token=secret",
            "https://github.com/example/private.git#access_token=secret",
        ):
            with (
                self.subTest(repository_url=repository_url),
                patch("backend.snapshot.git_cli.subprocess.Popen") as popen_mock,
                self.assertRaisesRegex(SnapshotBuildError, "query or fragment"),
            ):
                runner.clone_mirror(repository_url, Path("repo.git"), timeout_seconds=30)

                popen_mock.assert_not_called()

    def test_git_commands_run_with_isolated_config_and_no_prompt(self) -> None:
        runner = GitCommandRunner()

        with (
            patch.dict(
                os.environ,
                {
                    "PATH": os.environ.get("PATH", ""),
                    "HTTPS_PROXY": "http://localhost:10808",
                    "NO_PROXY": "localhost,127.0.0.1",
                    "SSL_CERT_FILE": "C:\\certs\\ca.pem",
                },
                clear=True,
            ),
            patch(
                "backend.snapshot.git_cli.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("140.82.112.4", 443))],
            ),
            patch(
                "backend.snapshot.git_cli.subprocess.Popen", return_value=FakeProcess(stdout=[b"ok\n"])
            ) as popen_mock,
        ):
            output = runner.run(["ls-remote", "https://github.com/example/project.git"], timeout_seconds=30)

        self.assertEqual(output, "ok\n")
        command = popen_mock.call_args.args[0]
        kwargs = popen_mock.call_args.kwargs
        env = kwargs["env"]
        self.assertEqual(
            command[:8],
            [
                "git",
                "-c",
                "credential.helper=",
                "-c",
                "core.askPass=",
                "-c",
                "http.extraHeader=",
                "-c",
            ],
        )
        self.assertIn("protocol.file.allow=never", command)
        self.assertNotIn("url.https://github.com/.insteadOf=", command)
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertIn("HOME", env)
        self.assertIn("USERPROFILE", env)
        self.assertIn("XDG_CONFIG_HOME", env)
        self.assertEqual(env["HTTPS_PROXY"], "http://localhost:10808")
        self.assertEqual(env["NO_PROXY"], "localhost,127.0.0.1")
        self.assertEqual(env["SSL_CERT_FILE"], "C:\\certs\\ca.pem")

    def test_clone_mirror_rejects_non_https_repository_url(self) -> None:
        runner = GitCommandRunner()

        with (
            patch("backend.snapshot.git_cli.subprocess.run") as run_mock,
            self.assertRaisesRegex(SnapshotBuildError, "HTTPS"),
        ):
            runner.clone_mirror(
                "http://github.com/example/project.git",
                Path("repo.git"),
                timeout_seconds=30,
            )

        run_mock.assert_not_called()

    def test_clone_mirror_rejects_scp_like_repository_url_before_git_is_spawned(self) -> None:
        runner = GitCommandRunner()

        for repository_url in (
            "git@github.com:example/project.git",
            "github.com:example/project.git",
            "git@internal.example:project.git",
        ):
            with (
                self.subTest(repository_url=repository_url),
                patch("backend.snapshot.git_cli.subprocess.Popen") as popen_mock,
                self.assertRaisesRegex(SnapshotBuildError, "HTTPS"),
            ):
                runner.clone_mirror(repository_url, Path("repo.git"), timeout_seconds=30)

                popen_mock.assert_not_called()

    def test_clone_mirror_rejects_localhost_repository_url(self) -> None:
        runner = GitCommandRunner()

        with (
            patch("backend.snapshot.git_cli.subprocess.run") as run_mock,
            self.assertRaisesRegex(SnapshotBuildError, "private or local"),
        ):
            runner.clone_mirror(
                "https://127.0.0.1/example/project.git",
                Path("repo.git"),
                timeout_seconds=30,
            )

        run_mock.assert_not_called()

    def test_clone_mirror_rejects_non_github_repository_url(self) -> None:
        runner = GitCommandRunner()

        with (
            patch("backend.snapshot.git_cli.subprocess.Popen") as popen_mock,
            self.assertRaisesRegex(SnapshotBuildError, "host is not allowed"),
        ):
            runner.clone_mirror(
                "https://internal.example/project.git",
                Path("repo.git"),
                timeout_seconds=30,
            )

        popen_mock.assert_not_called()

    def test_clone_mirror_rejects_dns_resolution_to_private_address(self) -> None:
        runner = GitCommandRunner()

        with (
            patch(
                "backend.snapshot.git_cli.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("10.0.0.7", 443))],
            ),
            patch("backend.snapshot.git_cli.subprocess.Popen") as popen_mock,
            self.assertRaisesRegex(SnapshotBuildError, "private or local"),
        ):
            runner.clone_mirror(
                "https://github.com/example/project.git",
                Path("repo.git"),
                timeout_seconds=30,
            )

        popen_mock.assert_not_called()

    def test_run_allows_windows_drive_paths_for_local_git_arguments(self) -> None:
        runner = GitCommandRunner()

        with patch(
            "backend.snapshot.git_cli.subprocess.Popen", return_value=FakeProcess(stdout=[b"ok\n"])
        ) as popen_mock:
            output = runner.run(["-C", "D:\\Development\\deepdive\\repo.git", "rev-parse", "HEAD"], timeout_seconds=30)

        self.assertEqual(output, "ok\n")
        popen_mock.assert_called_once()

    def test_git_error_message_redacts_credentials_and_tokens(self) -> None:
        runner = GitCommandRunner()

        with (
            patch(
                "backend.snapshot.git_cli.subprocess.Popen",
                return_value=FakeProcess(
                    stderr=[
                        b"fatal: Authentication failed for 'https://user:secret-token@github.com/example/private.git'\n"
                    ],
                    returncode=128,
                ),
            ),
            self.assertRaises(SnapshotBuildError) as raised,
        ):
            runner.run(["clone", "https://github.com/example/private.git", "repo.git"], timeout_seconds=30)

        message = raised.exception.message
        self.assertNotIn("secret-token", message)
        self.assertNotIn("user:", message)
        self.assertIn("https://***@github.com/example/private.git", message)

    def test_create_bundle_uses_temporary_ref_for_resolved_commit(self) -> None:
        calls: list[list[str]] = []

        def fake_popen(command, **kwargs):
            del kwargs
            calls.append(command)
            return FakeProcess()

        runner = GitCommandRunner()

        with patch("backend.snapshot.git_cli.subprocess.Popen", side_effect=fake_popen):
            runner.create_bundle(
                Path("repo.git"),
                "b" * 40,
                Path("snapshot.bundle"),
                timeout_seconds=30,
            )

        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][-5:], ["-C", "repo.git", "update-ref", "refs/deepdive/snapshot", "b" * 40])
        self.assertEqual(
            calls[1][-6:], ["-C", "repo.git", "bundle", "create", "snapshot.bundle", "refs/deepdive/snapshot"]
        )
        self.assertEqual(calls[2][-5:], ["-C", "repo.git", "update-ref", "-d", "refs/deepdive/snapshot"])

    def test_git_error_message_is_bounded_even_when_stderr_is_large(self) -> None:
        runner = GitCommandRunner(max_output_bytes=1024)

        with (
            patch(
                "backend.snapshot.git_cli.subprocess.Popen",
                return_value=FakeProcess(stderr=[("fatal: " + ("x" * 20000)).encode()], returncode=128),
            ),
            self.assertRaises(SnapshotBuildError) as raised,
        ):
            runner.run(["clone", "https://github.com/example/project.git", "repo.git"], timeout_seconds=30)

        self.assertLessEqual(len(raised.exception.message), 1200)

    def test_git_stdout_is_bounded_for_large_outputs(self) -> None:
        runner = GitCommandRunner(max_output_bytes=8)

        with (
            patch("backend.snapshot.git_cli.subprocess.Popen", return_value=FakeLargeStdoutProcess()),
            self.assertRaises(SnapshotBuildError) as raised,
        ):
            runner.run(["ls-tree"], timeout_seconds=30)

        self.assertEqual(raised.exception.code, "GitOutputTooLarge")

    def test_cat_file_blob_can_use_per_call_output_limit_for_allowed_file_size(self) -> None:
        runner = GitCommandRunner(max_output_bytes=8)

        with patch(
            "backend.snapshot.git_cli.subprocess.Popen",
            return_value=FakeProcess(stdout=[b"0123456789abcdef"]),
        ):
            content = runner.cat_file_blob(
                Path("repo.git"),
                "a" * 40,
                timeout_seconds=30,
                max_output_bytes=32,
            )

        self.assertEqual(content, b"0123456789abcdef")

    def test_list_tree_uses_dedicated_output_limit_for_medium_repositories(self) -> None:
        runner = GitCommandRunner(max_output_bytes=8, max_tree_output_bytes=256)
        tree_output = b"100644 blob " + (b"a" * 40) + b" 12\tbackend/app.py\0"

        with patch(
            "backend.snapshot.git_cli.subprocess.Popen",
            return_value=FakeProcess(stdout=[tree_output]),
        ):
            entries = runner.list_tree(Path("repo.git"), "b" * 40, timeout_seconds=30)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, "backend/app.py")

    def test_timeout_uses_process_group_cleanup(self) -> None:
        runner = GitCommandRunner()
        process = FakeTimeoutProcess()

        with (
            patch("backend.snapshot.git_cli.subprocess.Popen", return_value=process) as popen_mock,
            patch("backend.snapshot.git_cli._kill_process_tree") as kill_mock,
            self.assertRaisesRegex(SnapshotBuildError, "timed out"),
        ):
            runner.run(["ls-remote", "https://github.com/example/project.git"], timeout_seconds=1)

        popen_kwargs = popen_mock.call_args.kwargs
        self.assertTrue(popen_kwargs.get("start_new_session") or popen_kwargs.get("creationflags"))
        kill_mock.assert_called_once_with(process)


class FakePipe:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    def read1(self, size: int) -> bytes:
        del size
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeLargeStdoutProcess:
    def __init__(self) -> None:
        self.stdout = FakePipe([b"abcdef", b"ghijkl"])
        self.stderr = FakePipe([])
        self.returncode = 0
        self.terminated = False

    def wait(self, timeout=None):
        del timeout
        return self.returncode

    def poll(self):
        return None if self.terminated else self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: list[bytes] | None = None,
        stderr: list[bytes] | None = None,
        returncode: int = 0,
    ) -> None:
        self.stdout = FakePipe(stdout or [])
        self.stderr = FakePipe(stderr or [])
        self.returncode = returncode

    def wait(self, timeout=None):
        del timeout
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class FakeTimeoutProcess(FakeProcess):
    def __init__(self) -> None:
        super().__init__()
        self.returncode = None

    def wait(self, timeout=None):
        del timeout
        raise subprocess.TimeoutExpired(["git"], 1)

    def poll(self):
        return None


if __name__ == "__main__":
    unittest.main()
