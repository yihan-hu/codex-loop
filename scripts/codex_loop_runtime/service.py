from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
import subprocess
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .environment import build_exec_env
from .command_safety import assess as assess_command
from .process_manager import (
    DEFAULT_MAX_OUTPUT_BYTES, MAX_MANAGED_PROCESSES, MAX_PENDING_DELTA_BYTES,
    MAX_STDIN_BYTES, ManagedProcess, managed_session_capability,
)
from .state import StateStore, open_store, service_token, state_dir_for, validate_task_id
from .workspace import ensure_inside_workspace

# JSON ensure_ascii=True can expand one UTF-8 input byte to as much as six ASCII
# bytes (for example a control character as \u00XX). Include fixed structural
# headroom and the accepted request body in the response budget because process
# state echoes argv/cwd in addition to bounded output and delta frames.
JSON_WIRE_EXPANSION = 6
WIRE_STRUCTURAL_HEADROOM = 256 * 1024
MAX_REQUEST_WIRE_BYTES = JSON_WIRE_EXPANSION * MAX_STDIN_BYTES + WIRE_STRUCTURAL_HEADROOM
MAX_RESPONSE_WIRE_BYTES = (
    MAX_REQUEST_WIRE_BYTES
    + JSON_WIRE_EXPANSION * (DEFAULT_MAX_OUTPUT_BYTES + MAX_PENDING_DELTA_BYTES)
    + WIRE_STRUCTURAL_HEADROOM
)


class ProcessRegistry:
    def __init__(self, cwd: Path, task_id: str, token: str):
        self.cwd = cwd.resolve()
        self.task_id = validate_task_id(task_id)
        self.token = token
        self.store = open_store(self.cwd, self.task_id)
        self.processes: dict[str, ManagedProcess] = {}
        self.completed: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def _remember_completed(self, result: dict[str, Any], state: str) -> None:
        summary = dict(result)
        # Delta frames are delivery events, not durable process state. Keep aggregate
        # output/transcript metadata but do not retain already-delivered frame lists.
        summary["output_delta_frames"] = []
        self.completed[str(result["handle"])] = summary
        self.completed.move_to_end(str(result["handle"]))
        while len(self.completed) > MAX_MANAGED_PROCESSES:
            self.completed.popitem(last=False)
        self.processes.pop(str(result["handle"]), None)
        if state == "exited":
            self.store.prune_successful_processes(MAX_MANAGED_PROCESSES)

    def _status(self, proc: ManagedProcess) -> tuple[dict[str, Any], str]:
        result = proc.poll()
        if result.get("failure_message"):
            state = "failed" if result.get("has_exited") and result.get("output_drained") else "draining"
        elif result.get("has_exited") and result.get("output_drained"):
            state = "exited"
        elif result.get("has_exited"):
            state = "draining"
        else:
            state = "running"
        self.store.upsert_process(
            proc.handle, int(result["pid"]), proc.argv, str(proc.cwd), state,
            result.get("exit_code"), result.get("failure_message"),
        )
        if result.get("has_exited") and result.get("output_drained"):
            self._remember_completed(result, state)
        return result, state

    def dispatch(self, request: dict[str, Any]) -> Any:
        if request.get("token") != self.token:
            raise PermissionError("invalid runtime service capability token")
        if str(request.get("task_id") or "") != self.task_id:
            raise PermissionError("runtime service task identity mismatch")
        op = request.get("op")
        if op == "ping":
            return {"pong": True, "pid": os.getpid(), "task_id": self.task_id}
        if op == "spawn":
            self.store.ensure_active()
            argv = request.get("argv")
            if not (isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv)):
                raise ValueError("spawn requires a non-empty argv array of strings")
            safety = assess_command(argv)
            if safety.classification.value != "safe_known":
                raise PermissionError("runtime service only spawns narrow deterministic safe_known commands; use a host-visible execution path")
            active = 0
            for existing in list(self.processes.values()):
                result, _ = self._status(existing)
                if not (result.get("has_exited") and result.get("output_drained")):
                    active += 1
            if active >= MAX_MANAGED_PROCESSES:
                raise RuntimeError(f"runtime process limit reached ({MAX_MANAGED_PROCESSES})")
            cwd = ensure_inside_workspace(self.cwd, Path(str(request.get("cwd") or self.cwd)))
            proc = ManagedProcess(
                list(argv), cwd,
                transcript_dir=self.store.path.parent / "process-transcripts",
            )
            self.processes[proc.handle] = proc
            result, _ = self._status(proc)
            return result
        handle = str(request.get("handle") or "")
        if op in {"poll", "stdin", "interrupt", "terminate"}:
            proc = self.processes.get(handle)
            if proc is None:
                completed = self.completed.get(handle)
                if completed is not None and op == "poll":
                    return dict(completed)
                if completed is not None:
                    raise RuntimeError(f"managed process is already terminal: {handle}")
                raise KeyError(f"unknown process handle for this helper instance: {handle}")
            if op == "stdin":
                self.store.ensure_active()
                data = request.get("data", "")
                if not isinstance(data, str):
                    raise ValueError("stdin data must be text")
                proc.write(data.encode("utf-8"))
            elif op == "interrupt":
                proc.interrupt()
            elif op == "terminate":
                if not proc.terminate():
                    self._status(proc)
                    raise RuntimeError("managed process termination was not confirmed")
            result, _ = self._status(proc)
            return result
        if op == "shutdown":
            failures: list[str] = []
            for proc in list(self.processes.values()):
                if not proc.terminate():
                    failures.append(proc.handle)
                self._status(proc)
            if failures:
                raise RuntimeError(f"runtime service could not confirm termination for: {', '.join(failures)}")
            return {"shutdown": True}
        raise ValueError(f"unsupported operation: {op}")


class _Handler(socketserver.StreamRequestHandler):
    registry: ProcessRegistry
    server_ref: socketserver.BaseServer

    def handle(self) -> None:
        line = self.rfile.readline(MAX_REQUEST_WIRE_BYTES + 1)
        try:
            if len(line) > MAX_REQUEST_WIRE_BYTES:
                raise ValueError(f"runtime request exceeds derived wire budget ({MAX_REQUEST_WIRE_BYTES} bytes)")
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("runtime request must be a JSON object")
            data = self.registry.dispatch(request)
            response = {"ok": True, "data": data}
            shutdown = request.get("op") == "shutdown"
        except Exception as exc:
            response = {"ok": False, "error": {"message": str(exc), "type": type(exc).__name__}}
            shutdown = False
        encoded = (json.dumps(response, ensure_ascii=True) + "\n").encode("ascii")
        if len(encoded) > MAX_RESPONSE_WIRE_BYTES:
            encoded = (json.dumps({"ok": False, "error": {"message": "runtime response exceeds derived wire budget", "type": "RuntimeError"}}, ensure_ascii=True) + "\n").encode("ascii")
        self.wfile.write(encoded)
        self.wfile.flush()
        if shutdown:
            self.server_ref.shutdown()


def _endpoint_path(cwd: Path, task_id: str, *, create: bool) -> Path:
    return state_dir_for(cwd, task_id, create=create) / "service.json"


def _expected_unix_socket(cwd: Path, task_id: str, *, create: bool) -> Path:
    return state_dir_for(cwd, task_id, create=create) / "runtime.sock"


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=True, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _acquire_owner_lock(directory: Path, *, nonblocking: bool) -> int | None:
    lock_path = directory / "service-owner.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    try:
        if os.name != "nt":
            import fcntl
            flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
            try:
                fcntl.flock(fd, flags)
            except BlockingIOError:
                os.close(fd)
                return None
        else:
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            mode = msvcrt.LK_NBLCK if nonblocking else msvcrt.LK_LOCK
            try:
                msvcrt.locking(fd, mode, 1)
            except OSError:
                os.close(fd)
                return None
        return fd
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _release_owner_lock(fd: int) -> None:
    try:
        if os.name != "nt":
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def serve(cwd: Path, task_id: str, token: str) -> None:
    capability = managed_session_capability()
    if not capability["supported"]:
        raise RuntimeError(str(capability["reason"]))
    cwd = cwd.resolve()
    task_id = validate_task_id(task_id)
    directory = state_dir_for(cwd, task_id, create=False)
    owner_lock_fd = _acquire_owner_lock(directory, nonblocking=True)
    if owner_lock_fd is None:
        raise RuntimeError("another runtime helper already owns this task")
    endpoint_path = directory / "service.json"
    registry = ProcessRegistry(cwd, task_id, token)
    registry.store.mark_running_processes_orphaned("previous helper ownership was lost before new service startup")

    if os.name != "nt":
        socket_path = _expected_unix_socket(cwd, task_id, create=False)
        try:
            socket_st = socket_path.lstat()
        except FileNotFoundError:
            socket_st = None
        if socket_st is not None:
            raise RuntimeError("runtime socket path already exists; refusing to replace an endpoint from inside the helper")
        try:
            server = socketserver.ThreadingUnixStreamServer(str(socket_path), _Handler)
            os.chmod(socket_path, 0o600)
            actual: dict[str, Any] = {"kind": "unix", "path": str(socket_path)}
        except OSError as exc:
            if "AF_UNIX path too long" not in str(exc):
                raise
            server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
            host, port = server.server_address
            actual = {"kind": "tcp", "host": host, "port": int(port), "fallback": "unix_path_too_long"}
    else:
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
        host, port = server.server_address
        actual = {"kind": "tcp", "host": host, "port": int(port)}
    server.daemon_threads = True
    _Handler.registry = registry
    _Handler.server_ref = server
    _write_private_json(endpoint_path, {**actual, "pid": os.getpid(), "task_id": task_id, "token": token})
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        try:
            endpoint_path.unlink()
        except FileNotFoundError:
            pass
        if actual["kind"] == "unix":
            try:
                Path(actual["path"]).unlink()
            except FileNotFoundError:
                pass
        _release_owner_lock(owner_lock_fd)


def _read_endpoint(cwd: Path, task_id: str) -> dict[str, Any]:
    task_id = validate_task_id(task_id)
    path = _endpoint_path(cwd, task_id, create=False)
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("runtime service is not running") from exc
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("runtime service endpoint metadata is invalid")
    if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
        raise PermissionError("runtime service endpoint is not owned by current user")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("task_id") != task_id or not isinstance(data.get("token"), str):
        raise RuntimeError("runtime service endpoint metadata failed identity validation")
    if data.get("kind") == "unix":
        expected = _expected_unix_socket(cwd, task_id, create=False)
        socket_path = Path(str(data.get("path")))
        if socket_path.resolve() != expected.resolve():
            raise RuntimeError("runtime service socket path does not match task-private endpoint")
        try:
            socket_st = socket_path.lstat()
        except FileNotFoundError as exc:
            raise RuntimeError("runtime service socket is missing") from exc
        if stat.S_ISLNK(socket_st.st_mode) or not stat.S_ISSOCK(socket_st.st_mode):
            raise RuntimeError("runtime service endpoint is not a real Unix socket")
        if hasattr(os, "geteuid") and socket_st.st_uid != os.geteuid():
            raise PermissionError("runtime service socket is not owned by current user")
    elif data.get("kind") == "tcp":
        if data.get("host") not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("runtime TCP endpoint is not loopback-only")
    else:
        raise RuntimeError("unsupported runtime endpoint kind")
    return data


def request(cwd: Path, task_id: str, payload: dict[str, Any], timeout: float = 3.0) -> dict[str, Any]:
    endpoint = _read_endpoint(cwd, task_id)
    body = dict(payload)
    body["task_id"] = task_id
    body["token"] = endpoint["token"]
    if endpoint["kind"] == "unix":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        address: Any = endpoint["path"]
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        address = (endpoint["host"], int(endpoint["port"]))
    encoded = (json.dumps(body, ensure_ascii=True) + "\n").encode("ascii")
    if len(encoded) > MAX_REQUEST_WIRE_BYTES:
        raise ValueError(f"runtime request exceeds derived wire budget ({MAX_REQUEST_WIRE_BYTES} bytes)")
    sock.settimeout(timeout)
    with sock:
        sock.connect(address)
        sock.sendall(encoded)
        reader = sock.makefile("rb")
        line = reader.readline(MAX_RESPONSE_WIRE_BYTES + 1)
    if len(line) > MAX_RESPONSE_WIRE_BYTES:
        raise RuntimeError(f"runtime service response exceeds derived wire budget ({MAX_RESPONSE_WIRE_BYTES} bytes)")
    if not line:
        raise RuntimeError("runtime service closed connection without a response")
    response = json.loads(line.decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("runtime service returned an invalid response")
    return response




def _pid_is_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _existing_endpoint_pid(cwd: Path, task_id: str) -> int | None:
    path = _endpoint_path(cwd, task_id, create=False)
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise RuntimeError("runtime service endpoint metadata is invalid; refusing to replace it automatically")
    if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
        raise PermissionError("runtime service endpoint is not owned by current user")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("runtime service endpoint metadata is malformed; refusing to replace it automatically") from exc
    if not isinstance(data, dict) or data.get("task_id") != task_id:
        raise RuntimeError("runtime service endpoint metadata failed task identity validation")
    try:
        return int(data.get("pid"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("runtime service endpoint metadata has no valid helper pid") from exc


def _acquire_start_lock(directory: Path):
    lock_path = directory / "service-start.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    if os.name != "nt":
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
    else:
        import msvcrt
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    return fd


def _release_start_lock(fd: int) -> None:
    try:
        if os.name != "nt":
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def start(cwd: Path, task_id: str, cli_path: Path) -> dict[str, Any]:
    capability = managed_session_capability()
    if not capability["supported"]:
        raise RuntimeError(str(capability["reason"]))
    task_id = validate_task_id(task_id)
    directory = state_dir_for(cwd, task_id, create=False)
    lock_fd = _acquire_start_lock(directory)
    try:
        # Fail closed before touching stale endpoint/socket metadata. A cancelled or
        # otherwise inactive task must not mutate helper lifecycle state.
        store = open_store(cwd, task_id)
        store.ensure_active()
        endpoint_path = directory / "service.json"
        existing_pid = _existing_endpoint_pid(cwd, task_id)
        if existing_pid is not None:
            try:
                current = request(cwd, task_id, {"op": "ping"}, timeout=0.5)
                if current.get("ok"):
                    return current["data"]
            except Exception as exc:
                if _pid_is_alive(existing_pid):
                    raise RuntimeError(
                        f"runtime helper pid {existing_pid} is still alive but its endpoint is unresponsive; refusing to start a duplicate helper"
                    ) from exc
        probe_owner = _acquire_owner_lock(directory, nonblocking=True)
        if probe_owner is None:
            raise RuntimeError("a runtime helper still holds task ownership but is not reachable; refusing to start a duplicate helper")
        _release_owner_lock(probe_owner)
        if existing_pid is not None:
            # The recorded owner is dead and no helper holds the lifetime lock, so stale metadata may be replaced.
            try:
                endpoint_path.unlink()
            except FileNotFoundError:
                pass
            if os.name != "nt":
                socket_path = _expected_unix_socket(cwd, task_id, create=False)
                try:
                    socket_st = socket_path.lstat()
                except FileNotFoundError:
                    socket_st = None
                if socket_st is not None:
                    if stat.S_ISLNK(socket_st.st_mode) or not stat.S_ISSOCK(socket_st.st_mode):
                        raise RuntimeError("stale runtime socket path is not a real Unix socket")
                    if hasattr(os, "geteuid") and socket_st.st_uid != os.geteuid():
                        raise PermissionError("stale runtime socket path is not owned by current user")
                    socket_path.unlink()
        elif os.name != "nt":
            socket_path = _expected_unix_socket(cwd, task_id, create=False)
            if socket_path.exists() or socket_path.is_symlink():
                raise RuntimeError("runtime socket exists without endpoint metadata; refusing automatic replacement")
        store.mark_running_processes_orphaned("previous runtime helper ownership was confirmed lost before service restart")
        token = service_token()
        log_path = directory / "service.log"
        log_fd = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        env = build_exec_env()
        env["CODEX_LOOP_SERVICE_TOKEN"] = token
        try:
            subprocess.Popen(
                [sys.executable, str(cli_path), "_serve", "--cwd", str(cwd.resolve()), "--task-id", task_id],
                stdin=subprocess.DEVNULL,
                stdout=log_fd,
                stderr=log_fd,
                env=env,
                start_new_session=(os.name != "nt"),
                close_fds=True,
            )
        finally:
            os.close(log_fd)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                response = request(cwd, task_id, {"op": "ping"}, timeout=0.4)
                if response.get("ok"):
                    return response["data"]
            except Exception:
                time.sleep(0.05)
        raise RuntimeError(f"runtime service failed to start; inspect private log {log_path}")
    finally:
        _release_start_lock(lock_fd)
