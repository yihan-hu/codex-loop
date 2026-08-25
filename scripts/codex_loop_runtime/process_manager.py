from __future__ import annotations

import errno
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .command_safety import SafetyClass, assess as assess_command
from .environment import build_exec_env
from .output_buffer import HeadTailBuffer
from .output_stream import OutputDeltaFramer
from .process_state import ProcessState
from .workspace import repo_root

DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024
DEFAULT_MAX_TRANSCRIPT_BYTES = 4 * 1024 * 1024
DEFAULT_ONESHOT_TIMEOUT_SECONDS = 30.0
MAX_ONESHOT_TIMEOUT_SECONDS = 300.0
MAX_PENDING_DELTA_BYTES = 512 * 1024
READ_CHUNK_BYTES = 8192
MAX_STDIN_BYTES = 1024 * 1024
MAX_MANAGED_PROCESSES = 64




def managed_session_capability(platform_name: str | None = None) -> dict[str, object]:
    platform_name = os.name if platform_name is None else str(platform_name)
    if platform_name == "nt":
        return {
            "supported": False,
            "reason": "Windows managed-session process-group/interrupt semantics are not implemented faithfully; keep interactive/background execution host-visible",
        }
    return {"supported": True, "reason": None}

def _trusted_system_path() -> str:
    if os.name != "nt":
        return os.defpath
    root = os.environ.get("SystemRoot")
    return os.pathsep.join([str(Path(root) / "System32"), root]) if root else ""


def _secure_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        st = path.lstat()
        if os.path.islink(path) or not path.is_dir():
            raise RuntimeError(f"runtime transcript path is not a real directory: {path}")
        if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
            raise PermissionError(f"runtime transcript directory is not owned by current user: {path}")
        os.chmod(path, 0o700)
    except OSError:
        raise


def _local_exec_argv(argv: list[str], cwd: Path) -> list[str]:
    if not argv:
        raise ValueError("empty argv")
    safety = assess_command(argv)
    if safety.classification != SafetyClass.SAFE_KNOWN:
        raise PermissionError(f"local process layer refuses {safety.classification.value} command; keep it host-visible")
    raw = str(argv[0])
    if "/" in raw or "\\" in raw:
        raise PermissionError("path-qualified executable must remain host-visible")
    found = shutil.which(raw, path=_trusted_system_path())
    if not found:
        raise PermissionError(f"no trusted system executable found for local primitive: {raw}")
    executable = Path(found).resolve()
    workspace = repo_root(cwd).resolve()
    if executable == workspace or executable.is_relative_to(workspace):
        raise PermissionError(f"local executable resolves inside workspace and must remain host-visible: {executable}")
    return [str(executable), *[str(x) for x in argv[1:]]]


class _BoundedTranscript:
    def __init__(self, path: Path, max_bytes: int):
        if max_bytes < 0:
            raise ValueError("max transcript bytes must be non-negative")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.path = path
        self.handle = os.fdopen(fd, "wb", buffering=0)
        self.max_bytes = int(max_bytes)
        self.written_bytes = 0
        self.omitted_bytes = 0
        self.closed = False
        _secure_file(path)

    def write(self, data: bytes) -> None:
        if self.closed:
            return
        remaining = max(0, self.max_bytes - self.written_bytes)
        if remaining:
            chunk = data[:remaining]
            self.handle.write(chunk)
            self.written_bytes += len(chunk)
        self.omitted_bytes += max(0, len(data) - remaining)

    def close(self) -> None:
        if not self.closed:
            self.handle.close()
            self.closed = True


def _prepare_transcript(directory: Path | None, stem: str, max_bytes: int) -> tuple[str | None, _BoundedTranscript | None]:
    if directory is None:
        return None, None
    _secure_dir(directory)
    path = directory / stem
    transcript = _BoundedTranscript(path, max_bytes)
    return str(path), transcript


def _process_group_exists(pgid: int) -> bool:
    if os.name == "nt":
        return False
    try:
        os.killpg(int(pgid), 0)
        live = _linux_process_group_has_live_members(int(pgid))
        return True if live is None else live
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _linux_process_group_has_live_members(pgid: int) -> bool | None:
    proc_root = Path("/proc")
    if os.name == "nt" or not proc_root.is_dir():
        return None
    saw_member = False
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(errors="replace")
            close = raw.rfind(")")
            if close < 0:
                continue
            fields = raw[close + 2 :].split()
            if len(fields) < 3:
                continue
            state = fields[0]
            pgrp = int(fields[2])
        except (OSError, ValueError):
            continue
        if pgrp != int(pgid):
            continue
        saw_member = True
        if state != "Z":
            return True
    return False if saw_member else False


def _wait_process_group_gone(pgid: int, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not _process_group_exists(pgid):
            return True
        live = _linux_process_group_has_live_members(pgid)
        if live is False:
            # Linux containers can retain reparented zombies when PID 1 is slow to reap them.
            # They cannot execute or retain runtime-owned file descriptors, so ownership is settled.
            return True
        time.sleep(0.02)
    if not _process_group_exists(pgid):
        return True
    return _linux_process_group_has_live_members(pgid) is False


def _terminate_process(
    proc: subprocess.Popen[bytes],
    *,
    grace: float = 1.0,
    kill_group_if_leader_exited: bool = False,
) -> bool:
    leader_exited = proc.poll() is not None
    if os.name == "nt":
        if leader_exited:
            return True
        try:
            proc.terminate()
        except ProcessLookupError:
            return proc.poll() is not None
        except OSError:
            return False
        try:
            proc.wait(timeout=grace)
            return True
        except subprocess.TimeoutExpired:
            pass
        try:
            proc.kill()
            proc.wait(timeout=grace)
            return True
        except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
            return proc.poll() is not None

    # Every local POSIX process is started in its own session. If its leader exited while
    # descendants still hold the PTY/pipes, the process group remains runtime-owned and must
    # still be terminated before ownership can be considered settled.
    if leader_exited and not kill_group_if_leader_exited:
        return True
    pgid = int(proc.pid)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return proc.poll() is not None
    except OSError:
        return False
    if not leader_exited:
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
    if _wait_process_group_gone(pgid, grace):
        if proc.poll() is None:
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                return False
        return proc.poll() is not None
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        return False
    if not _wait_process_group_gone(pgid, grace):
        return False
    if proc.poll() is None:
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            return False
    return proc.poll() is not None


class _PipeCapture:
    def __init__(self, stream: BinaryIO, max_bytes: int, transcript: _BoundedTranscript | None):
        self.stream = stream
        self.buffer = HeadTailBuffer(max_bytes)
        self.transcript = transcript
        self.total = 0
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            while True:
                chunk = self.stream.read(READ_CHUNK_BYTES)
                if not chunk:
                    break
                self.total += len(chunk)
                self.buffer.push_chunk(chunk)
                if self.transcript is not None:
                    self.transcript.write(chunk)
        except BaseException as exc:  # surfaced to caller, never silently swallowed
            self.error = exc
        finally:
            if self.transcript is not None:
                try:
                    self.transcript.close()
                except OSError:
                    pass
            try:
                self.stream.close()
            except OSError:
                pass


@dataclass(frozen=True)
class ExecResult:
    argv: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    aggregated_output: str
    duration_seconds: float
    timed_out: bool
    stdout_total_bytes: int
    stderr_total_bytes: int
    transcript_stdout: str | None = None
    transcript_stderr: str | None = None
    transcript_stdout_omitted_bytes: int = 0
    transcript_stderr_omitted_bytes: int = 0


def run_one_shot(
    argv: list[str],
    cwd: Path,
    *,
    timeout: float | None = None,
    env_overlay: dict[str, str] | None = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    transcript_dir: Path | None = None,
    stdin_data: bytes | None = None,
    max_transcript_bytes: int = DEFAULT_MAX_TRANSCRIPT_BYTES,
) -> ExecResult:
    cwd = Path(cwd).resolve()
    timeout = DEFAULT_ONESHOT_TIMEOUT_SECONDS if timeout is None else float(timeout)
    if timeout <= 0 or timeout > MAX_ONESHOT_TIMEOUT_SECONDS:
        raise ValueError(f"local one-shot timeout must be >0 and <= {MAX_ONESHOT_TIMEOUT_SECONDS:g} seconds")
    exec_argv = _local_exec_argv(argv, cwd)
    env = build_exec_env(overlay=env_overlay)
    if stdin_data is not None and len(stdin_data) > MAX_STDIN_BYTES:
        raise ValueError("local stdin payload exceeds 1 MiB")
    out_path, out_handle = _prepare_transcript(transcript_dir, f"oneshot-{uuid.uuid4().hex}-stdout.log", max_transcript_bytes)
    err_path, err_handle = _prepare_transcript(transcript_dir, f"oneshot-{uuid.uuid4().hex}-stderr.log", max_transcript_bytes)
    started = time.monotonic()
    proc = subprocess.Popen(
        exec_argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    assert proc.stdout is not None and proc.stderr is not None
    out = _PipeCapture(proc.stdout, max_output_bytes, out_handle)
    err = _PipeCapture(proc.stderr, max_output_bytes, err_handle)
    threads = [threading.Thread(target=out.run, daemon=True), threading.Thread(target=err.run, daemon=True)]
    for thread in threads:
        thread.start()
    if stdin_data is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_data)
            proc.stdin.close()
        except BrokenPipeError:
            pass
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if not _terminate_process(proc):
            raise RuntimeError("timed-out local process could not be terminated; ownership is uncertain")
    for thread in threads:
        thread.join(timeout=5)
    if any(thread.is_alive() for thread in threads):
        raise RuntimeError("local process output reader did not drain after process exit")
    if out.error:
        raise RuntimeError(f"stdout capture failed: {out.error}")
    if err.error:
        raise RuntimeError(f"stderr capture failed: {err.error}")
    code = proc.poll()
    if code is None:
        raise RuntimeError("local process exit was not confirmed")
    stdout = out.buffer.to_bytes_with_omission_marker().decode("utf-8", errors="replace")
    stderr = err.buffer.to_bytes_with_omission_marker().decode("utf-8", errors="replace")
    aggregated = stdout if not stderr else (stdout + ("\n" if stdout else "") + stderr)
    return ExecResult(
        list(map(str, argv)), str(cwd), int(code), stdout, stderr, aggregated,
        time.monotonic() - started, timed_out, out.total, err.total, out_path, err_path,
        out_handle.omitted_bytes if out_handle is not None else 0,
        err_handle.omitted_bytes if err_handle is not None else 0,
    )


class ManagedProcess:
    def __init__(
        self,
        argv: list[str],
        cwd: Path,
        *,
        env_overlay: dict[str, str] | None = None,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        transcript_dir: Path | None = None,
        max_transcript_bytes: int = DEFAULT_MAX_TRANSCRIPT_BYTES,
    ):
        self.handle = uuid.uuid4().hex
        self.argv = list(map(str, argv))
        self.cwd = Path(cwd).resolve()
        self.started_at = time.monotonic()
        self.output = HeadTailBuffer(max_output_bytes)
        self._delta_framer = OutputDeltaFramer(max_pending_bytes=MAX_PENDING_DELTA_BYTES)
        self._lock = threading.RLock()
        self.state = ProcessState()
        self._master_fd: int | None = None
        self._stdin: BinaryIO | None = None
        self._reader: threading.Thread | None = None
        self.transcript_path: Path | None = None
        self._transcript: _BoundedTranscript | None = None
        self._transcript_omitted_bytes = 0
        if transcript_dir is not None:
            _secure_dir(transcript_dir)
            self.transcript_path = transcript_dir / f"process-{self.handle}.log"
            self._transcript = _BoundedTranscript(self.transcript_path, max_transcript_bytes)
        exec_env = build_exec_env(overlay=env_overlay)
        exec_argv = _local_exec_argv(self.argv, self.cwd)
        if os.name != "nt":
            import pty
            master, slave = pty.openpty()
            self._master_fd = master
            self.proc = subprocess.Popen(
                exec_argv, cwd=self.cwd, env=exec_env, stdin=slave, stdout=slave, stderr=slave,
                start_new_session=True, close_fds=True,
            )
            os.close(slave)
            self._reader = threading.Thread(target=self._read_pty, daemon=True)
        else:
            self.proc = subprocess.Popen(
                exec_argv, cwd=self.cwd, env=exec_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, close_fds=True,
            )
            self._stdin = self.proc.stdin
            self._reader = threading.Thread(target=self._read_pipe, daemon=True)
        self._reader.start()

    def _append(self, data: bytes) -> None:
        with self._lock:
            self.output.push_chunk(data)
            self._delta_framer.push(data)
            if self._transcript is not None:
                try:
                    self._transcript.write(data)
                except (OSError, ValueError) as exc:
                    try:
                        self._transcript.close()
                    except OSError:
                        pass
                    self._transcript_omitted_bytes = self._transcript.omitted_bytes
                    self._transcript = None
                    self.state = self.state.with_failure(f"transcript write failed: {exc}")

    def _mark_exit(self, *, drained: bool) -> None:
        code = self.proc.poll()
        with self._lock:
            state = self.state
            if code is not None:
                state = state.exited(code)
            if drained:
                state = state.drained()
                if self._transcript is not None:
                    try:
                        self._transcript.close()
                    except OSError:
                        pass
                    self._transcript_omitted_bytes = self._transcript.omitted_bytes
                    self._transcript = None
            self.state = state

    def _read_pty(self) -> None:
        assert self._master_fd is not None
        try:
            while True:
                try:
                    data = os.read(self._master_fd, READ_CHUNK_BYTES)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    self.state = self.state.with_failure(f"PTY read failed: {exc}")
                    break
                if not data:
                    break
                self._append(data)
        finally:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
            self._mark_exit(drained=True)

    def _read_pipe(self) -> None:
        assert self.proc.stdout is not None
        try:
            while True:
                data = self.proc.stdout.read(READ_CHUNK_BYTES)
                if not data:
                    break
                self._append(data)
        finally:
            self._mark_exit(drained=True)

    def write(self, data: bytes) -> None:
        if len(data) > MAX_STDIN_BYTES:
            raise ValueError("stdin payload exceeds 1 MiB")
        if self.proc.poll() is not None:
            raise RuntimeError("process has exited")
        if self._master_fd is not None:
            os.write(self._master_fd, data)
        elif self._stdin is not None:
            self._stdin.write(data)
            self._stdin.flush()
        else:
            raise RuntimeError("stdin is unavailable")

    def interrupt(self) -> None:
        if self.proc.poll() is not None:
            return
        if os.name != "nt":
            os.killpg(self.proc.pid, signal.SIGINT)
        else:
            self.proc.send_signal(signal.CTRL_BREAK_EVENT)

    def terminate(self) -> bool:
        reader_alive_before = bool(self._reader is not None and self._reader.is_alive())
        confirmed = _terminate_process(
            self.proc,
            kill_group_if_leader_exited=reader_alive_before,
        )
        if self._reader is not None:
            self._reader.join(timeout=3)
        drained = bool(self._reader is None or not self._reader.is_alive())
        self._mark_exit(drained=drained)
        if not confirmed or self.proc.poll() is None or not drained:
            with self._lock:
                self.state = self.state.with_failure(
                    "process termination/output drain was not confirmed"
                )
            return False
        return True

    def poll(self) -> dict[str, object]:
        self._mark_exit(drained=False)
        with self._lock:
            output = self.output.to_bytes_with_omission_marker().decode("utf-8", errors="replace")
            state = self.state
            frames_raw, omitted = self._delta_framer.drain(final=bool(state.has_exited and state.output_drained))
        frames = [x.decode("utf-8", errors="replace") for x in frames_raw]
        return {
            "handle": self.handle,
            "pid": self.proc.pid,
            "argv": self.argv,
            "cwd": str(self.cwd),
            "has_exited": state.has_exited,
            "output_drained": state.output_drained,
            "exit_code": state.exit_code,
            "failure_message": state.failure_message,
            "output": output,
            "output_delta_frames": frames,
            "output_delta_omitted_bytes": omitted,
            "transcript_path": str(self.transcript_path) if self.transcript_path else None,
            "transcript_omitted_bytes": self._transcript.omitted_bytes if self._transcript is not None else self._transcript_omitted_bytes,
            "duration_seconds": time.monotonic() - self.started_at,
        }
