from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
import os
import re
import socket
import signal
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit

from backend.snapshot.models import SnapshotBuildError


DEFAULT_ALLOWED_REPOSITORY_HOSTS = frozenset({"github.com", "www.github.com"})


@dataclass(frozen=True)
class GitTreeEntry:
    mode: str
    kind: str
    oid: str
    size: int | None
    path: str


@dataclass(frozen=True)
class GitCommandRunner:
    max_output_bytes: int = 262_144
    max_tree_output_bytes: int = 67_108_864
    allowed_repository_hosts: frozenset[str] = DEFAULT_ALLOWED_REPOSITORY_HOSTS

    def clone_mirror(self, repository_url: str, mirror_path: Path, *, timeout_seconds: int) -> None:
        _reject_unsafe_repository_url(repository_url, allowed_hosts=self.allowed_repository_hosts, require_url=True)
        self.run(["clone", "--mirror", repository_url, str(mirror_path)], timeout_seconds=timeout_seconds)

    def resolve_commit(self, mirror_path: Path, ref: str, *, timeout_seconds: int) -> str:
        return self.run(["-C", str(mirror_path), "rev-parse", f"{ref}^{{commit}}"], timeout_seconds=timeout_seconds).strip()

    def resolve_tree(self, mirror_path: Path, commit_sha: str, *, timeout_seconds: int) -> str:
        return self.run(["-C", str(mirror_path), "rev-parse", f"{commit_sha}^{{tree}}"], timeout_seconds=timeout_seconds).strip()

    def list_tree(self, mirror_path: Path, commit_sha: str, *, timeout_seconds: int) -> list[GitTreeEntry]:
        output = self.run(
            ["-C", str(mirror_path), "ls-tree", "-r", "-z", "--long", commit_sha],
            timeout_seconds=timeout_seconds,
            max_output_bytes=self.max_tree_output_bytes,
        )
        entries: list[GitTreeEntry] = []
        for raw_entry in output.split("\0"):
            if not raw_entry:
                continue
            metadata, path = raw_entry.split("\t", 1)
            mode, kind, oid, size_text = metadata.split(maxsplit=3)
            entries.append(
                GitTreeEntry(
                    mode=mode,
                    kind=kind,
                    oid=oid,
                    size=None if size_text == "-" else int(size_text.strip()),
                    path=path.replace("\\", "/"),
                )
            )
        return entries

    def create_bundle(self, mirror_path: Path, commit_sha: str, output_path: Path, *, timeout_seconds: int) -> None:
        ref_name = "refs/deepdive/snapshot"
        self.run(["-C", str(mirror_path), "update-ref", ref_name, commit_sha], timeout_seconds=timeout_seconds)
        try:
            self.run(
                ["-C", str(mirror_path), "bundle", "create", str(output_path), ref_name],
                timeout_seconds=timeout_seconds,
            )
        finally:
            self.run(["-C", str(mirror_path), "update-ref", "-d", ref_name], timeout_seconds=timeout_seconds)

    def create_archive(self, mirror_path: Path, commit_sha: str, output_path: Path, *, timeout_seconds: int) -> None:
        self.run(
            ["-C", str(mirror_path), "archive", "--format=tar", "--output", str(output_path), commit_sha],
            timeout_seconds=timeout_seconds,
        )

    def cat_file_blob(self, mirror_path: Path, oid: str, *, timeout_seconds: int, max_output_bytes: int | None = None) -> bytes:
        return self.run_bytes(
            ["-C", str(mirror_path), "cat-file", "blob", oid],
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    def run(self, args: list[str], *, timeout_seconds: int, max_output_bytes: int | None = None) -> str:
        return self.run_bytes(args, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes).decode("utf-8", errors="replace")

    def run_bytes(self, args: list[str], *, timeout_seconds: int, max_output_bytes: int | None = None) -> bytes:
        _reject_url_credentials(args, allowed_hosts=self.allowed_repository_hosts)
        output_limit = max_output_bytes if max_output_bytes is not None else self.max_output_bytes
        with tempfile.TemporaryDirectory(prefix="deepdive-git-home-") as git_home:
            process = subprocess.Popen(
                _git_command(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_git_env(git_home),
                **_process_group_kwargs(),
            )
            return _run_git_process(
                process,
                timeout_seconds=timeout_seconds,
                stdout_limit=output_limit,
                stderr_limit=self.max_output_bytes,
            )


def _run_git_process(process, *, timeout_seconds: int, stdout_limit: int, stderr_limit: int) -> bytes:
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    output_too_large = False
    lock = threading.Lock()

    def read_stdout() -> None:
        nonlocal output_too_large
        if process.stdout is None:
            return
        while True:
            chunk = process.stdout.read1(8192)
            if not chunk:
                return
            with lock:
                remaining = max(0, stdout_limit - len(stdout_buffer))
                if remaining:
                    stdout_buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    output_too_large = True
                    break
        if process.poll() is None:
            process.terminate()

    def read_stderr() -> None:
        if process.stderr is None:
            return
        while True:
            chunk = process.stderr.read1(4096)
            if not chunk:
                return
            with lock:
                remaining = max(0, stderr_limit - len(stderr_buffer))
                if remaining:
                    stderr_buffer.extend(chunk[:remaining])

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        if process.poll() is None:
            _kill_process_tree(process)
        _join_and_close(process, stdout_thread, stderr_thread)
        raise SnapshotBuildError("GitCommandTimeout", f"git command timed out after {timeout_seconds}s") from exc
    _join_and_close(process, stdout_thread, stderr_thread)
    if output_too_large:
        raise SnapshotBuildError("GitOutputTooLarge", f"git command output exceeded {stdout_limit} bytes")
    if returncode != 0:
        stderr = bytes(stderr_buffer).decode("utf-8", errors="replace")
        stdout = bytes(stdout_buffer).decode("utf-8", errors="replace")
        message = _sanitize_git_error(stderr or stdout or "git command failed", max_output_bytes=stderr_limit)
        raise SnapshotBuildError("GitCommandFailed", message)
    return bytes(stdout_buffer)


def _git_command(args: list[str]) -> list[str]:
    return [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "core.askPass=",
        "-c",
        "http.extraHeader=",
        "-c",
        "protocol.file.allow=never",
        *args,
    ]


def _git_env(git_home: str) -> dict[str, str]:
    passthrough_keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "GIT_SSL_CAINFO",
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "SystemRoot": os.environ.get("SystemRoot", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "HOME": git_home,
        "USERPROFILE": git_home,
        "XDG_CONFIG_HOME": git_home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
        "GCM_INTERACTIVE": "never",
    }
    for key in passthrough_keys:
        if key in os.environ:
            env[key] = os.environ[key]
    return {key: value for key, value in env.items() if value is not None}


def _sanitize_git_error(message: str, *, max_output_bytes: int = 4096) -> str:
    message = _redact_url_credentials(message.strip())[:max(1, max_output_bytes)]
    return message.replace("\r", " ").replace("\n", " ")


def _join_and_close(process, stdout_thread: threading.Thread, stderr_thread: threading.Thread) -> None:
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    for pipe in (process.stdout, process.stderr):
        if pipe is not None and not getattr(pipe, "closed", False):
            pipe.close()


def _process_group_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_process_tree(process) -> None:
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=2)
            return
        except Exception:
            pass
        if process.poll() is None:
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except Exception:
        if process.poll() is None:
            process.kill()


def _reject_url_credentials(args: list[str], *, allowed_hosts: frozenset[str]) -> None:
    for arg in args:
        if _has_url_credentials(arg):
            raise SnapshotBuildError("RepositoryUrlContainsCredentials", "repository URL credentials are not allowed")
        _reject_unsafe_repository_url(arg, allowed_hosts=allowed_hosts)


def _has_url_credentials(value: str) -> bool:
    parsed = urlsplit(value)
    return _is_url_like(value, parsed.scheme) and parsed.scheme in {"http", "https", "ssh", "git"} and bool(parsed.username or parsed.password)


def _reject_unsafe_repository_url(value: str, *, allowed_hosts: frozenset[str], require_url: bool = False) -> None:
    parsed = urlsplit(value)
    if not _is_url_like(value, parsed.scheme):
        if require_url:
            raise SnapshotBuildError("RepositoryUrlSchemeNotAllowed", "repository URL must use HTTPS")
        return
    if parsed.scheme != "https":
        raise SnapshotBuildError("RepositoryUrlSchemeNotAllowed", "repository URL must use HTTPS")
    if parsed.query or parsed.fragment:
        raise SnapshotBuildError("RepositoryUrlQueryOrFragmentNotAllowed", "repository URL query or fragment is not allowed")
    host = parsed.hostname
    if not host:
        raise SnapshotBuildError("RepositoryUrlHostInvalid", "repository URL host is required")
    host = host.strip().lower().rstrip(".")
    if host in {"localhost"} or host.endswith(".localhost"):
        raise SnapshotBuildError("RepositoryUrlPrivateOrLocal", "repository URL private or local hosts are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if allowed_hosts and host not in allowed_hosts:
            raise SnapshotBuildError("RepositoryUrlHostNotAllowed", "repository URL host is not allowed")
        _reject_private_resolved_addresses(host)
        return
    if _is_private_or_local_address(address):
        raise SnapshotBuildError("RepositoryUrlPrivateOrLocal", "repository URL private or local hosts are not allowed")
    if allowed_hosts and host not in allowed_hosts:
        raise SnapshotBuildError("RepositoryUrlHostNotAllowed", "repository URL host is not allowed")


def _reject_private_resolved_addresses(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SnapshotBuildError("RepositoryUrlHostUnresolved", "repository URL host could not be resolved") from exc
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_private_or_local_address(address):
            raise SnapshotBuildError("RepositoryUrlPrivateOrLocal", "repository URL private or local hosts are not allowed")


def _is_private_or_local_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _is_url_like(value: str, scheme: str) -> bool:
    if not scheme:
        return False
    return "://" in value or scheme in {"http", "https", "ssh", "git"}


def _redact_url_credentials(message: str) -> str:
    return re.sub(
        r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^@\s/'\"]+)@",
        r"\g<scheme>***@",
        message,
    )
