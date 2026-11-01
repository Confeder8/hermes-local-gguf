#!/usr/bin/env python3
"""Portable gateway control for launch.bat.

Uses only the bundled Python runtime and Hermes' own on-disk state; never a
Windows service manager, Scheduled Task, PowerShell, tasklist or taskkill.
"""
from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PORTABLE_ROOT = SCRIPT_DIR.parent
SRC_DIR = PORTABLE_ROOT / "src" / "hermes-agent"
HOME = Path(os.environ.get("HERMES_HOME") or PORTABLE_ROOT / "data")

PID_FILE = HOME / "gateway.pid"
LOCK_FILE = HOME / "gateway.lock"
STATE_FILE = HOME / "gateway_state.json"
STOP_MARKER = HOME / ".gateway-planned-stop.json"
LOG_FILE = HOME / "logs" / "gateway.log"
STDIO_LOG = HOME / "logs" / "gateway-stdio.log"

STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
FILETIME_TO_UNIX_CENTISECONDS = 116_444_736_000_000_000
GET_PROCESS_TIMES_DIVISOR = 100_000


def _open_process(pid: int, access: int) -> int | None:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    return kernel32.OpenProcess(access, False, pid)


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_process_start_time(pid: int) -> int | None:
    """Process creation time as Unix centiseconds, matching Hermes' psutil fingerprint.

    Uses the Win32 API directly because the portable launcher's Python does not
    ship psutil; without this the PID-reuse guard silently disabled itself and a
    recycled PID from a stale gateway.pid could be killed (closing the launcher).
    """
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None
        filetime = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return (filetime - FILETIME_TO_UNIX_CENTISECONDS) // GET_PROCESS_TIMES_DIVISOR
    finally:
        kernel32.CloseHandle(handle)


def _linux_process_start_time(pid: int) -> int | None:
    try:
        stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)
        return int(stat_fields[1].split()[19])
    except (OSError, IndexError, ValueError):
        return None


def process_start_time(pid: int) -> int | None:
    if os.name == "nt":
        return _windows_process_start_time(pid)
    if sys.platform.startswith("linux"):
        value = _linux_process_start_time(pid)
        if value is not None:
            return value
    try:
        import psutil

        return round(psutil.Process(pid).create_time() * 100)
    except Exception:
        return None


def start_times_match(recorded: object, current: object, tolerance: int = 200) -> bool:
    try:
        return abs(int(current) - int(recorded)) <= tolerance
    except (TypeError, ValueError):
        return False


def read_pid_record() -> dict | None:
    try:
        record = json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = record.get("pid")
    if not isinstance(pid, int) or not pid_alive(pid):
        return None
    recorded_start = record.get("start_time")
    current_start = process_start_time(pid)
    if (
        recorded_start is not None
        and current_start is not None
        and not start_times_match(recorded_start, current_start)
    ):
        return None
    return record


def read_pid() -> int | None:
    record = read_pid_record()
    return record["pid"] if record else None


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cleanup_stale() -> None:
    if read_pid() is not None:
        return
    for path in (PID_FILE, LOCK_FILE):
        try:
            path.unlink()
        except OSError:
            pass


def cmd_status() -> int:
    pid = read_pid()
    if pid is None:
        print("STOPPED")
        return 1
    print(f"RUNNING {pid}")
    return 0


def wait_for_ready(timeout: float) -> tuple[int | None, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = read_pid()
        state = str(read_state().get("gateway_state") or "")
        if pid is not None and state in {"running", "degraded"}:
            return pid, state
        if state == "startup_failed":
            return None, "startup_failed"
        time.sleep(1)
    return None, "timeout"


def cmd_wait(timeout: float) -> int:
    pid, state = wait_for_ready(timeout)
    if pid is not None:
        print(f"READY {pid} {state}")
        return 0
    if state == "startup_failed":
        reason = read_state().get("exit_reason") or "startup_failed"
        print(f"FAILED {reason}")
        return 1
    print("TIMEOUT")
    return 1


def spawn_gateway() -> subprocess.Popen:
    STDIO_LOG.parent.mkdir(parents=True, exist_ok=True)
    flags = 0
    if os.name == "nt":
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    with open(STDIO_LOG, "ab") as log:
        return subprocess.Popen(
            [sys.executable, "-c", "from hermes_cli.main import main; main()", "gateway"],
            cwd=str(SRC_DIR),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            close_fds=True,
        )


def cmd_start() -> int:
    pid = read_pid()
    if pid is not None:
        print(f"ALREADY RUNNING {pid}")
        return 0
    cleanup_stale()
    child = spawn_gateway()
    print(f"STARTED {child.pid}")
    return 0


def cmd_ensure(timeout: float) -> int:
    """Start the gateway if needed and wait until it can serve sessions."""
    pid = read_pid()
    if pid is not None:
        print(f"RUNNING {pid}")
        return 0
    cleanup_stale()
    print("Starting gateway ...", flush=True)
    spawn_gateway()
    pid, state = wait_for_ready(timeout)
    if pid is None:
        if state == "startup_failed":
            reason = read_state().get("exit_reason") or "startup_failed"
            print(f"FAILED {reason}")
        else:
            print("TIMEOUT")
        return 1
    print(f"READY {pid} {state}")
    return 0


def write_stop_marker(pid: int) -> bool:
    pid_record = read_pid_record()
    target_start = (
        pid_record.get("start_time")
        if pid_record and pid_record.get("pid") == pid
        else None
    )
    record = {
        "target_pid": pid,
        "target_start_time": target_start,
        "stopper_pid": os.getpid(),
        "written_at": datetime.now(UTC).isoformat(),
    }
    try:
        STOP_MARKER.parent.mkdir(parents=True, exist_ok=True)
        temporary = STOP_MARKER.with_name(STOP_MARKER.name + ".tmp")
        temporary.write_text(json.dumps(record), encoding="utf-8")
        os.replace(temporary, STOP_MARKER)
        return True
    except OSError as exc:
        print(f"WARN could not write stop marker: {exc}")
        return False


def stop_pid(pid: int, timeout: float) -> bool:
    if not pid_alive(pid):
        return True
    write_stop_marker(pid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.5)
    pid_record = read_pid_record()
    if pid_record is None or pid_record.get("pid") != pid:
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"FAILED {exc}")
        return False
    for _ in range(20):
        if not pid_alive(pid):
            return True
        time.sleep(0.25)
    return False


def cmd_chat(extra: list[str]) -> int:
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    return subprocess.call(
        [sys.executable, "-c", "from hermes_cli.main import main; main()", *extra],
        cwd=str(SRC_DIR),
        env=os.environ.copy(),
        creationflags=flags,
    )


def spawn_guardian(run_pid: int, gateway_pid: int) -> None:
    flags = 0
    if os.name == "nt":
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "guard",
            str(run_pid),
            str(gateway_pid),
        ],
        cwd=str(PORTABLE_ROOT),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def cmd_guard(run_pid: int, gateway_pid: int) -> int:
    while pid_alive(run_pid):
        time.sleep(0.5)
    if read_pid() == gateway_pid:
        stop_pid(gateway_pid, 35.0)
    return 0


def spawn_session_guardian(run_pid: int) -> None:
    flags = 0
    if os.name == "nt":
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "guard-session",
            str(run_pid),
        ],
        cwd=str(PORTABLE_ROOT),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def cmd_guard_session(run_pid: int) -> int:
    expected = None
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if not pid_alive(run_pid):
            break
        pid = read_pid()
        if pid is not None:
            expected = pid
            break
        time.sleep(0.2)
    while pid_alive(run_pid):
        time.sleep(0.5)
    if expected is None:
        grace = time.monotonic() + 15
        while time.monotonic() < grace:
            pid = read_pid()
            if pid is not None:
                expected = pid
                break
            time.sleep(0.5)
    if expected is not None and read_pid() == expected:
        stop_pid(expected, 35.0)
    return 0


def cmd_session(extra: list[str]) -> int:
    started_here = read_pid() is None
    if started_here:
        spawn_session_guardian(os.getpid())
        print("Starting gateway ...", flush=True)
        spawn_gateway()
        ready_pid, state = wait_for_ready(90)
        if ready_pid is None:
            print("Gateway did not become ready.", flush=True)
            print("Last gateway log lines:", flush=True)
            cmd_logs(20)
            pid = read_pid()
            if pid is not None:
                stop_pid(pid, 10.0)
                cleanup_stale()
            return 1
        print(f"Gateway is ready (PID {ready_pid}).", flush=True)
    print("Opening Hermes Chat ...", flush=True)
    try:
        # A dedicated console keeps the launcher menu visible and gives the
        # interactive CLI a real TTY (the menu console must never be replaced).
        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        code = subprocess.call(
            [sys.executable, "-c", "from hermes_cli.main import main; main()", "chat", *extra],
            cwd=str(SRC_DIR),
            env=os.environ.copy(),
            creationflags=flags,
        )
    except KeyboardInterrupt:
        code = 130
    if started_here:
        pid = read_pid()
        if pid is not None:
            print("Chat closed - stopping gateway ...", flush=True)
            stop_pid(pid, 35.0)
            cleanup_stale()
            print("Gateway stopped.", flush=True)
    return code


def cmd_run(stop_on_exit: bool, extra: list[str]) -> int:
    gateway_pid = read_pid()
    if stop_on_exit and gateway_pid is not None:
        spawn_guardian(os.getpid(), gateway_pid)
    try:
        code = subprocess.call(
            [sys.executable, "-c", "from hermes_cli.main import main; main()", "chat", *extra],
            cwd=str(SRC_DIR),
            env=os.environ.copy(),
        )
    except KeyboardInterrupt:
        code = 130
    if stop_on_exit and gateway_pid is not None and read_pid() == gateway_pid:
        stop_pid(gateway_pid, 35.0)
        cleanup_stale()
    return code


def cmd_stop(timeout: float) -> int:
    pid = read_pid()
    if pid is None:
        cleanup_stale()
        try:
            STOP_MARKER.unlink()
        except OSError:
            pass
        print("STOPPED")
        return 0
    if stop_pid(pid, timeout):
        cleanup_stale()
        print("STOPPED")
        return 0
    print("FAILED still running")
    return 1


def cmd_logs(lines: int) -> int:
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as handle:
            tail = deque(handle, maxlen=max(1, lines))
    except OSError:
        print("No gateway log yet.")
        return 1
    for line in tail:
        print(line.rstrip("\n"))
    return 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if len(argv) < 2:
        print(
            "usage: gateway_control.py "
            "{status|start|wait|ensure|session|run|chat|stop|logs|guard|guard-session} [args]"
        )
        return 2
    command = argv[1].lower()
    if command == "status":
        return cmd_status()
    if command == "start":
        return cmd_start()
    if command == "wait":
        return cmd_wait(float(argv[2]) if len(argv) > 2 else 90.0)
    if command == "ensure":
        return cmd_ensure(float(argv[2]) if len(argv) > 2 else 90.0)
    if command == "chat":
        return cmd_chat(argv[2:])
    if command == "session":
        return cmd_session(argv[2:])
    if command == "run":
        extra = argv[2:]
        stop_on_exit = False
        if extra and extra[0] == "--stop-on-exit":
            stop_on_exit = True
            extra = extra[1:]
        return cmd_run(stop_on_exit, extra)
    if command == "guard":
        return cmd_guard(int(argv[2]), int(argv[3]))
    if command == "guard-session":
        return cmd_guard_session(int(argv[2]))
    if command == "stop":
        return cmd_stop(float(argv[2]) if len(argv) > 2 else 35.0)
    if command == "logs":
        return cmd_logs(int(argv[2]) if len(argv) > 2 else 20)
    print(f"unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
