# Implementation Specification: Server Watchdog & Platform Startup System

## Overview

Two new capabilities for amplifier-distro:

1. **Watchdog** (`server/watchdog.py`): A standalone lightweight process that polls the server health endpoint and restarts the server after sustained downtime (default 5 minutes).
2. **Platform Service** (`service.py`): Cross-platform install/uninstall of OS boot-time services (systemd on Linux, launchd on macOS).

The watchdog is the boot service. `amp-distro service install` registers the watchdog as the thing the OS starts on boot. The watchdog starts the server if it's not running, then monitors it.

```
Boot -> OS Service -> Watchdog Process -> Starts & Monitors Server
                                        -> Restarts after 5min downtime
```

**Working directory**: `/home/samschillace/dev/ANext/amplifier-distro`
**Test command**: `uv run python -m pytest tests/ -x -q`
**Current tests passing**: 755

---

## Implementation Order

1. `src/amplifier_distro/conventions.py` (modify — add 4 constants)
2. `src/amplifier_distro/schema.py` (modify — add WatchdogConfig)
3. `src/amplifier_distro/server/watchdog.py` (CREATE)
4. `src/amplifier_distro/service.py` (CREATE)
5. `src/amplifier_distro/server/cli.py` (modify — add watchdog subgroup)
6. `src/amplifier_distro/cli.py` (modify — add service subgroup)
7. `scripts/amplifier-distro.service` (modify — add Environment line)
8. `tests/test_watchdog.py` (CREATE)
9. `tests/test_service.py` (CREATE)
10. `tests/test_conventions.py` (modify — add 4 pinning tests)
11. Run `uv run python -m pytest tests/ -x -q` — all 755 existing + ~50 new must pass

---

## File 1: `src/amplifier_distro/conventions.py` (MODIFY)

**What to change**: Insert new constants after line 72 (`SLACK_SESSIONS_FILENAME`), before line 74 (`# --- Interface Registry ---`).

**Exact text to insert between line 72 and line 74:**

```python

# --- Watchdog ---
WATCHDOG_PID_FILE = "watchdog.pid"  # relative to SERVER_DIR
WATCHDOG_LOG_FILE = "watchdog.log"  # relative to SERVER_DIR

# --- Platform Service ---
SERVICE_NAME = "amplifier-distro"  # systemd unit name
LAUNCHD_LABEL = "com.amplifier.distro"  # macOS launchd job label
```

**Result**: conventions.py gains 4 new constants. No functions, no classes, no imports. The existing `TestModulePurity` tests in `test_conventions.py` will continue to pass because these are all `str` type.

**Full list of new constants:**
| Constant | Value | Type |
|----------|-------|------|
| `WATCHDOG_PID_FILE` | `"watchdog.pid"` | `str` |
| `WATCHDOG_LOG_FILE` | `"watchdog.log"` | `str` |
| `SERVICE_NAME` | `"amplifier-distro"` | `str` |
| `LAUNCHD_LABEL` | `"com.amplifier.distro"` | `str` |

---

## File 2: `src/amplifier_distro/schema.py` (MODIFY)

**What to change**: Add `WatchdogConfig` class before `DistroConfig` (before line 91), and add a `watchdog` field to `DistroConfig`.

**Insert before line 91 (`class DistroConfig(BaseModel):`):**

```python
class WatchdogConfig(BaseModel):
    """Watchdog settings for server health monitoring.

    The watchdog is a lightweight process that polls the server health
    endpoint and restarts the server after sustained downtime.
    """

    check_interval_seconds: int = 30
    restart_after_seconds: int = 300  # 5 minutes of sustained downtime
    max_restarts: int = 5  # per watchdog session; 0 = unlimited


```

**Add to `DistroConfig` after line 101 (`voice: VoiceConfig = ...`):**

```python
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
```

**Result**: `DistroConfig` gains an optional `watchdog:` section in distro.yaml. Defaults mean existing configs work unchanged.

---

## File 3: `src/amplifier_distro/server/watchdog.py` (CREATE)

**Full file contents:**

```python
"""Server watchdog: health monitoring and automatic restart.

A lightweight standalone process that monitors the distro server by polling
its health endpoint. If the server is unresponsive for a sustained period
(default 5 minutes), the watchdog restarts it.

The watchdog is separate from the server process -- if the server crashes,
the watchdog survives. All paths are from conventions.py.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from amplifier_distro import conventions
from amplifier_distro.server.daemon import (
    cleanup_pid,
    daemonize,
    is_running,
    pid_file_path,
    read_pid,
    server_dir,
    stop_process,
    write_pid,
)

logger = logging.getLogger(__name__)

# Module-level shutdown flag, set by signal handlers
_shutdown = False


# ---------------------------------------------------------------------------
# Path helpers (mirror daemon.py pattern exactly)
# ---------------------------------------------------------------------------


def watchdog_pid_file_path() -> Path:
    """Return the watchdog PID file path, constructed from conventions."""
    return server_dir() / conventions.WATCHDOG_PID_FILE


def watchdog_log_file_path() -> Path:
    """Return the watchdog log file path, constructed from conventions."""
    return server_dir() / conventions.WATCHDOG_LOG_FILE


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def check_health(url: str, timeout: float = 5.0) -> bool:
    """Check if the server health endpoint responds with HTTP 200.

    Uses stdlib urllib to avoid adding dependencies to the watchdog.

    Args:
        url: Full URL to the health endpoint
             (e.g., ``http://127.0.0.1:8400/api/health``).
        timeout: Request timeout in seconds.

    Returns:
        True if the endpoint returns HTTP 200.
    """
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)  # noqa: S310
        return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Watchdog loop
# ---------------------------------------------------------------------------


def _setup_watchdog_logging() -> None:
    """Configure logging for the watchdog process.

    Logs to both the watchdog log file and stderr. Uses a simple format
    (not JSON) since the watchdog is a lightweight monitor.
    """
    log_file = watchdog_log_file_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(str(log_file))
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


def _signal_handler(signum: int, frame: object) -> None:
    """Handle SIGTERM/SIGINT by setting the shutdown flag."""
    global _shutdown  # noqa: PLW0603
    _shutdown = True
    logger.info("Received signal %d, shutting down...", signum)


def run_watchdog_loop(
    *,
    host: str = "127.0.0.1",
    port: int = conventions.SERVER_DEFAULT_PORT,
    check_interval: int = 30,
    restart_after: int = 300,
    max_restarts: int = 5,
    apps_dir: str | None = None,
    dev: bool = False,
) -> None:
    """Run the watchdog loop in the foreground (blocking).

    Monitors the server health endpoint and restarts the server if it has
    been continuously unresponsive for ``restart_after`` seconds.

    Handles SIGTERM/SIGINT for clean shutdown. Writes its own PID file.

    Args:
        host: Server bind host (for health URL and restart).
        port: Server bind port.
        check_interval: Seconds between health checks.
        restart_after: Seconds of sustained downtime before restart.
        max_restarts: Maximum restarts per watchdog session (0 = unlimited).
        apps_dir: Optional server apps directory.
        dev: Server dev mode flag.
    """
    global _shutdown  # noqa: PLW0603
    _shutdown = False

    # Register signal handlers
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Write our own PID file
    wd_pid_file = watchdog_pid_file_path()
    write_pid(wd_pid_file)

    health_url = f"http://{host}:{port}/api/health"
    logger.info(
        "Watchdog started (PID %d), monitoring %s every %ds",
        os.getpid(),
        health_url,
        check_interval,
    )
    logger.info(
        "Will restart server after %ds of sustained downtime (max_restarts=%d)",
        restart_after,
        max_restarts,
    )

    first_failure_time: float | None = None
    restart_count = 0

    try:
        while not _shutdown:
            time.sleep(check_interval)
            if _shutdown:
                break

            healthy = check_health(health_url)

            if healthy:
                if first_failure_time is not None:
                    elapsed = time.monotonic() - first_failure_time
                    logger.info(
                        "Server recovered after %ds of downtime", int(elapsed)
                    )
                    first_failure_time = None
                continue

            # Server is unhealthy
            if first_failure_time is None:
                first_failure_time = time.monotonic()
                logger.warning("Server health check failed, monitoring...")
                continue

            elapsed = time.monotonic() - first_failure_time
            if elapsed < restart_after:
                logger.warning(
                    "Server unhealthy for %ds (threshold: %ds)",
                    int(elapsed),
                    restart_after,
                )
                continue

            # Threshold exceeded -- restart
            if max_restarts > 0 and restart_count >= max_restarts:
                logger.error(
                    "Max restarts (%d) reached, watchdog giving up",
                    max_restarts,
                )
                break

            logger.warning(
                "Server down for %ds (>= %ds threshold), restarting... "
                "(restart %d/%s)",
                int(elapsed),
                restart_after,
                restart_count + 1,
                str(max_restarts) if max_restarts > 0 else "unlimited",
            )
            _restart_server(host, port, apps_dir, dev)
            restart_count += 1
            first_failure_time = None  # Reset after restart attempt
    finally:
        cleanup_pid(wd_pid_file)
        logger.info("Watchdog stopped (restarts performed: %d)", restart_count)


def _restart_server(
    host: str,
    port: int,
    apps_dir: str | None,
    dev: bool,
) -> None:
    """Stop the server (if running) and start a fresh instance.

    Uses daemon.stop_process for graceful shutdown (SIGTERM then SIGKILL),
    then daemon.daemonize to spawn a new process.

    Args:
        host: Server bind host.
        port: Server bind port.
        apps_dir: Optional apps directory.
        dev: Dev mode flag.
    """
    server_pid = pid_file_path()

    # Stop existing server if running
    if is_running(server_pid):
        logger.info("Stopping existing server...")
        stop_process(server_pid)
        # Brief pause for port release
        time.sleep(2)

    # Start fresh server
    pid = daemonize(host=host, port=port, apps_dir=apps_dir, dev=dev)
    logger.info("Server restarted (PID %d)", pid)


# ---------------------------------------------------------------------------
# Watchdog process management (called from CLI)
# ---------------------------------------------------------------------------


def start_watchdog(
    *,
    host: str = "127.0.0.1",
    port: int = conventions.SERVER_DEFAULT_PORT,
    check_interval: int = 30,
    restart_after: int = 300,
    max_restarts: int = 5,
    apps_dir: str | None = None,
    dev: bool = False,
) -> int:
    """Spawn the watchdog as a detached background process.

    Follows the same pattern as daemon.daemonize(): uses subprocess.Popen
    with start_new_session=True, writes PID file.

    Args:
        host: Server host to monitor.
        port: Server port to monitor.
        check_interval: Seconds between health checks.
        restart_after: Seconds of sustained downtime before restart.
        max_restarts: Max restarts per session (0 = unlimited).
        apps_dir: Optional server apps directory.
        dev: Server dev mode flag.

    Returns:
        The PID of the spawned watchdog process.
    """
    cmd = [
        sys.executable,
        "-m",
        "amplifier_distro.server.watchdog",
        "--host",
        host,
        "--port",
        str(port),
        "--check-interval",
        str(check_interval),
        "--restart-after",
        str(restart_after),
        "--max-restarts",
        str(max_restarts),
    ]
    if apps_dir:
        cmd.extend(["--apps-dir", apps_dir])
    if dev:
        cmd.append("--dev")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    wd_pid_file = watchdog_pid_file_path()
    write_pid(wd_pid_file, process.pid)
    return process.pid


def stop_watchdog() -> bool:
    """Stop the running watchdog process.

    Returns:
        True if the watchdog was stopped (or was already gone).
        False if the PID file was missing/unreadable.
    """
    return stop_process(watchdog_pid_file_path())


def is_watchdog_running() -> bool:
    """Check if the watchdog process is alive."""
    return is_running(watchdog_pid_file_path())


# ---------------------------------------------------------------------------
# Module entry point (for background spawning via python -m)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Amplifier Distro Server Watchdog")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=conventions.SERVER_DEFAULT_PORT)
    parser.add_argument("--check-interval", type=int, default=30)
    parser.add_argument("--restart-after", type=int, default=300)
    parser.add_argument("--max-restarts", type=int, default=5)
    parser.add_argument("--apps-dir", default=None)
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()

    _setup_watchdog_logging()
    run_watchdog_loop(
        host=args.host,
        port=args.port,
        check_interval=args.check_interval,
        restart_after=args.restart_after,
        max_restarts=args.max_restarts,
        apps_dir=args.apps_dir,
        dev=args.dev,
    )
```

**Key design decisions:**
- **stdlib-only HTTP**: Uses `urllib.request` instead of httpx — zero additional dependencies.
- **Time-based threshold, not count-based**: Tracks `first_failure_time` monotonic timestamp. Restarts when `elapsed >= restart_after`. Resets on recovery.
- **Safety valve**: `max_restarts=5` prevents infinite restart loops. When exhausted, watchdog exits.
- **Signal handling**: Catches SIGTERM/SIGINT via a module-level `_shutdown` flag. The `try/finally` ensures PID cleanup.
- **Mirrors daemon.py pattern exactly**: Same import style, same path helpers, same `subprocess.Popen` + `start_new_session=True` + `write_pid` pattern.

---

## File 4: `src/amplifier_distro/service.py` (CREATE)

**Full file contents:**

```python
"""Platform service registration: auto-start on boot.

Installs/uninstalls OS-level services that start the amplifier-distro
watchdog (or server directly) on boot.

Supported platforms:
- Linux (including WSL2): systemd user service
- macOS: launchd user agent

All templates are generated in code -- no external template files needed.
All paths are constructed from conventions.py constants.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from pydantic import BaseModel, Field

from amplifier_distro import conventions


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class ServiceResult(BaseModel):
    """Outcome of a service install/uninstall/status operation."""

    success: bool
    platform: str
    message: str
    details: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def detect_platform() -> str:
    """Detect the current platform for service registration.

    Returns:
        One of: ``'linux'``, ``'macos'``, or ``'unsupported'``.
        WSL2 is detected as ``'linux'`` (systemd works on modern WSL2).
    """
    system = platform.system()
    if system == "Linux":
        return "linux"
    if system == "Darwin":
        return "macos"
    return "unsupported"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install_service(include_watchdog: bool = True) -> ServiceResult:
    """Install platform service for auto-start on boot.

    Args:
        include_watchdog: If True (default), the boot service runs the
            watchdog which manages the server. If False, the boot service
            runs the server directly (systemd/launchd handle restarts).

    Returns:
        ServiceResult with success status and details.
    """
    plat = detect_platform()
    if plat == "linux":
        return _install_systemd(include_watchdog)
    if plat == "macos":
        return _install_launchd(include_watchdog)
    return ServiceResult(
        success=False,
        platform=plat,
        message="Unsupported platform for automatic service installation.",
        details=[
            "Supported: Linux (systemd), macOS (launchd).",
            "For Windows, use Task Scheduler to run: amp-distro-server start",
        ],
    )


def uninstall_service() -> ServiceResult:
    """Remove platform service.

    Returns:
        ServiceResult with success status and details.
    """
    plat = detect_platform()
    if plat == "linux":
        return _uninstall_systemd()
    if plat == "macos":
        return _uninstall_launchd()
    return ServiceResult(
        success=False,
        platform=plat,
        message="Unsupported platform.",
    )


def service_status() -> ServiceResult:
    """Check if the platform service is installed and running.

    Returns:
        ServiceResult with status information.
    """
    plat = detect_platform()
    if plat == "linux":
        return _status_systemd()
    if plat == "macos":
        return _status_launchd()
    return ServiceResult(
        success=True,
        platform=plat,
        message="No service support on this platform.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_server_binary() -> str | None:
    """Find the amp-distro-server binary on PATH."""
    return shutil.which("amp-distro-server")


def _find_python_binary() -> str:
    """Return the current Python interpreter path."""
    return sys.executable


def _run_cmd(cmd: list[str], timeout: int = 10) -> tuple[bool, str]:
    """Run a command and return (success, output).

    Args:
        cmd: Command and arguments.
        timeout: Maximum seconds to wait.

    Returns:
        Tuple of (success: bool, combined stdout+stderr: str).
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, f"Command timed out: {' '.join(cmd)}"


# ===========================================================================
# Linux: systemd (user service)
# ===========================================================================

# Paths:
#   Server:   ~/.config/systemd/user/amplifier-distro.service
#   Watchdog: ~/.config/systemd/user/amplifier-distro-watchdog.service


def _systemd_dir() -> Path:
    """Return the systemd user service directory."""
    return Path.home() / ".config" / "systemd" / "user"


def _systemd_server_unit_path() -> Path:
    """Return path for the server systemd unit file."""
    return _systemd_dir() / f"{conventions.SERVICE_NAME}.service"


def _systemd_watchdog_unit_path() -> Path:
    """Return path for the watchdog systemd unit file."""
    return _systemd_dir() / f"{conventions.SERVICE_NAME}-watchdog.service"


def _generate_systemd_server_unit(server_bin: str) -> str:
    """Generate the systemd unit file for the server.

    Args:
        server_bin: Absolute path to the amp-distro-server binary.

    Returns:
        Complete systemd unit file content as a string.
    """
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    port = conventions.SERVER_DEFAULT_PORT
    return dedent(f"""\
        [Unit]
        Description=Amplifier Distro Server
        After=network.target

        [Service]
        Type=simple
        ExecStart={server_bin} --host 127.0.0.1 --port {port}
        Restart=on-failure
        RestartSec=5
        WorkingDirectory=%h
        Environment=PATH={path_env}

        [Install]
        WantedBy=default.target
    """)


def _generate_systemd_watchdog_unit(server_bin: str) -> str:
    """Generate the systemd unit file for the watchdog.

    The watchdog unit uses ``Restart=always`` so it is always running.
    It depends on the server unit via ``Wants=`` and ``After=``.

    Args:
        server_bin: Absolute path to the amp-distro-server binary.
            Used to locate the Python interpreter from the same
            virtual environment.

    Returns:
        Complete systemd unit file content as a string.
    """
    python_bin = _find_python_binary()
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    port = conventions.SERVER_DEFAULT_PORT
    service_name = conventions.SERVICE_NAME
    return dedent(f"""\
        [Unit]
        Description=Amplifier Distro Watchdog
        After={service_name}.service
        Wants={service_name}.service

        [Service]
        Type=simple
        ExecStart={python_bin} -m amplifier_distro.server.watchdog --host 127.0.0.1 --port {port}
        Restart=always
        RestartSec=10
        WorkingDirectory=%h
        Environment=PATH={path_env}

        [Install]
        WantedBy=default.target
    """)


def _install_systemd(include_watchdog: bool) -> ServiceResult:
    """Install systemd user services.

    Steps:
    1. Find amp-distro-server binary via shutil.which.
    2. Create ~/.config/systemd/user/ directory.
    3. Generate and write server unit file.
    4. If include_watchdog: generate and write watchdog unit file.
    5. Run: systemctl --user daemon-reload.
    6. Enable and start server service.
    7. If include_watchdog: enable and start watchdog service.

    Args:
        include_watchdog: Whether to also install the watchdog service.

    Returns:
        ServiceResult with outcome details.
    """
    server_bin = _find_server_binary()
    if server_bin is None:
        return ServiceResult(
            success=False,
            platform="linux",
            message="amp-distro-server not found on PATH.",
            details=["Install amplifier-distro first: uv pip install amplifier-distro"],
        )

    details: list[str] = []

    # Create directory
    systemd_dir = _systemd_dir()
    systemd_dir.mkdir(parents=True, exist_ok=True)

    # Write server unit
    server_unit_path = _systemd_server_unit_path()
    server_unit_path.write_text(_generate_systemd_server_unit(server_bin))
    details.append(f"Wrote {server_unit_path}")

    # Write watchdog unit
    if include_watchdog:
        watchdog_unit_path = _systemd_watchdog_unit_path()
        watchdog_unit_path.write_text(
            _generate_systemd_watchdog_unit(server_bin)
        )
        details.append(f"Wrote {watchdog_unit_path}")

    # Reload systemd
    ok, output = _run_cmd(["systemctl", "--user", "daemon-reload"])
    if not ok:
        return ServiceResult(
            success=False,
            platform="linux",
            message="systemctl daemon-reload failed.",
            details=[*details, output],
        )
    details.append("Reloaded systemd daemon")

    # Enable and start server
    service_name = conventions.SERVICE_NAME
    ok, output = _run_cmd(
        ["systemctl", "--user", "enable", "--now", f"{service_name}.service"]
    )
    if ok:
        details.append(f"Enabled and started {service_name}.service")
    else:
        details.append(f"Warning: could not enable {service_name}.service: {output}")

    # Enable and start watchdog
    if include_watchdog:
        ok, output = _run_cmd(
            [
                "systemctl",
                "--user",
                "enable",
                "--now",
                f"{service_name}-watchdog.service",
            ]
        )
        if ok:
            details.append(f"Enabled and started {service_name}-watchdog.service")
        else:
            details.append(
                f"Warning: could not enable {service_name}-watchdog.service: {output}"
            )

    return ServiceResult(
        success=True,
        platform="linux",
        message="Service installed.",
        details=details,
    )


def _uninstall_systemd() -> ServiceResult:
    """Uninstall systemd user services.

    Steps:
    1. Stop and disable both services (watchdog first, then server).
    2. Remove unit files.
    3. Reload systemd daemon.

    Returns:
        ServiceResult with outcome details.
    """
    details: list[str] = []
    service_name = conventions.SERVICE_NAME

    # Stop and disable watchdog (ignore errors if not installed)
    for unit in [f"{service_name}-watchdog.service", f"{service_name}.service"]:
        _run_cmd(["systemctl", "--user", "stop", unit])
        _run_cmd(["systemctl", "--user", "disable", unit])
        details.append(f"Stopped and disabled {unit}")

    # Remove unit files
    for path in [_systemd_watchdog_unit_path(), _systemd_server_unit_path()]:
        if path.exists():
            path.unlink()
            details.append(f"Removed {path}")

    # Reload
    _run_cmd(["systemctl", "--user", "daemon-reload"])
    details.append("Reloaded systemd daemon")

    return ServiceResult(
        success=True,
        platform="linux",
        message="Service removed.",
        details=details,
    )


def _status_systemd() -> ServiceResult:
    """Check systemd service status.

    Returns:
        ServiceResult with details about installed/running state.
    """
    details: list[str] = []
    service_name = conventions.SERVICE_NAME

    # Check server
    server_unit = _systemd_server_unit_path()
    if server_unit.exists():
        ok, output = _run_cmd(
            ["systemctl", "--user", "is-active", f"{service_name}.service"]
        )
        state = output.strip() if ok else output.strip()
        details.append(f"Server service: installed ({state})")
    else:
        details.append("Server service: not installed")

    # Check watchdog
    watchdog_unit = _systemd_watchdog_unit_path()
    if watchdog_unit.exists():
        ok, output = _run_cmd(
            [
                "systemctl",
                "--user",
                "is-active",
                f"{service_name}-watchdog.service",
            ]
        )
        state = output.strip() if ok else output.strip()
        details.append(f"Watchdog service: installed ({state})")
    else:
        details.append("Watchdog service: not installed")

    installed = server_unit.exists() or watchdog_unit.exists()
    return ServiceResult(
        success=True,
        platform="linux",
        message="Installed" if installed else "Not installed",
        details=details,
    )


# ===========================================================================
# macOS: launchd (user agent)
# ===========================================================================

# Paths:
#   Server:   ~/Library/LaunchAgents/com.amplifier.distro.plist
#   Watchdog: ~/Library/LaunchAgents/com.amplifier.distro.watchdog.plist


def _launchd_dir() -> Path:
    """Return the launchd user agents directory."""
    return Path.home() / "Library" / "LaunchAgents"


def _launchd_server_plist_path() -> Path:
    """Return path for the server launchd plist."""
    return _launchd_dir() / f"{conventions.LAUNCHD_LABEL}.plist"


def _launchd_watchdog_plist_path() -> Path:
    """Return path for the watchdog launchd plist."""
    return _launchd_dir() / f"{conventions.LAUNCHD_LABEL}.watchdog.plist"


def _generate_launchd_server_plist(server_bin: str) -> str:
    """Generate a launchd plist for the server.

    The plist uses ``RunAtLoad`` for boot-time start and ``KeepAlive``
    with ``SuccessfulExit=false`` so launchd restarts on crash.

    Args:
        server_bin: Absolute path to the amp-distro-server binary.

    Returns:
        Complete plist XML content as a string.
    """
    label = conventions.LAUNCHD_LABEL
    port = conventions.SERVER_DEFAULT_PORT
    home = str(Path.home())
    srv_dir = str(
        Path(conventions.AMPLIFIER_HOME).expanduser() / conventions.SERVER_DIR
    )
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{label}</string>
            <key>ProgramArguments</key>
            <array>
                <string>{server_bin}</string>
                <string>--host</string>
                <string>127.0.0.1</string>
                <string>--port</string>
                <string>{port}</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <dict>
                <key>SuccessfulExit</key>
                <false/>
            </dict>
            <key>WorkingDirectory</key>
            <string>{home}</string>
            <key>StandardOutPath</key>
            <string>{srv_dir}/launchd-stdout.log</string>
            <key>StandardErrorPath</key>
            <string>{srv_dir}/launchd-stderr.log</string>
            <key>EnvironmentVariables</key>
            <dict>
                <key>PATH</key>
                <string>{path_env}</string>
            </dict>
        </dict>
        </plist>
    """)


def _generate_launchd_watchdog_plist(python_bin: str) -> str:
    """Generate a launchd plist for the watchdog.

    Uses ``KeepAlive=true`` so the watchdog always restarts if it exits.

    Args:
        python_bin: Absolute path to the Python interpreter.

    Returns:
        Complete plist XML content as a string.
    """
    label = f"{conventions.LAUNCHD_LABEL}.watchdog"
    port = conventions.SERVER_DEFAULT_PORT
    home = str(Path.home())
    srv_dir = str(
        Path(conventions.AMPLIFIER_HOME).expanduser() / conventions.SERVER_DIR
    )
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{label}</string>
            <key>ProgramArguments</key>
            <array>
                <string>{python_bin}</string>
                <string>-m</string>
                <string>amplifier_distro.server.watchdog</string>
                <string>--host</string>
                <string>127.0.0.1</string>
                <string>--port</string>
                <string>{port}</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>WorkingDirectory</key>
            <string>{home}</string>
            <key>StandardOutPath</key>
            <string>{srv_dir}/watchdog-launchd-stdout.log</string>
            <key>StandardErrorPath</key>
            <string>{srv_dir}/watchdog-launchd-stderr.log</string>
            <key>EnvironmentVariables</key>
            <dict>
                <key>PATH</key>
                <string>{path_env}</string>
            </dict>
        </dict>
        </plist>
    """)


def _install_launchd(include_watchdog: bool) -> ServiceResult:
    """Install launchd user agents.

    Steps:
    1. Find amp-distro-server binary.
    2. Create ~/Library/LaunchAgents/ if needed.
    3. Generate and write server plist.
    4. Load server plist via launchctl.
    5. If include_watchdog: generate, write, and load watchdog plist.

    Args:
        include_watchdog: Whether to also install the watchdog agent.

    Returns:
        ServiceResult with outcome details.
    """
    server_bin = _find_server_binary()
    if server_bin is None:
        return ServiceResult(
            success=False,
            platform="macos",
            message="amp-distro-server not found on PATH.",
            details=["Install amplifier-distro first: uv pip install amplifier-distro"],
        )

    details: list[str] = []

    # Create directory
    launchd_dir = _launchd_dir()
    launchd_dir.mkdir(parents=True, exist_ok=True)

    # Write and load server plist
    server_plist = _launchd_server_plist_path()
    server_plist.write_text(_generate_launchd_server_plist(server_bin))
    details.append(f"Wrote {server_plist}")

    ok, output = _run_cmd(["launchctl", "load", "-w", str(server_plist)])
    if ok:
        details.append("Loaded server agent")
    else:
        details.append(f"Warning: launchctl load failed: {output}")

    # Write and load watchdog plist
    if include_watchdog:
        python_bin = _find_python_binary()
        watchdog_plist = _launchd_watchdog_plist_path()
        watchdog_plist.write_text(_generate_launchd_watchdog_plist(python_bin))
        details.append(f"Wrote {watchdog_plist}")

        ok, output = _run_cmd(["launchctl", "load", "-w", str(watchdog_plist)])
        if ok:
            details.append("Loaded watchdog agent")
        else:
            details.append(f"Warning: launchctl load failed: {output}")

    return ServiceResult(
        success=True,
        platform="macos",
        message="Service installed.",
        details=details,
    )


def _uninstall_launchd() -> ServiceResult:
    """Uninstall launchd user agents.

    Steps:
    1. Unload both plists via launchctl.
    2. Remove plist files.

    Returns:
        ServiceResult with outcome details.
    """
    details: list[str] = []

    for plist_path in [_launchd_watchdog_plist_path(), _launchd_server_plist_path()]:
        if plist_path.exists():
            _run_cmd(["launchctl", "unload", str(plist_path)])
            plist_path.unlink()
            details.append(f"Unloaded and removed {plist_path}")

    return ServiceResult(
        success=True,
        platform="macos",
        message="Service removed.",
        details=details,
    )


def _status_launchd() -> ServiceResult:
    """Check launchd service status.

    Returns:
        ServiceResult with installed/running details.
    """
    details: list[str] = []
    label = conventions.LAUNCHD_LABEL

    # Check server
    server_plist = _launchd_server_plist_path()
    if server_plist.exists():
        ok, output = _run_cmd(["launchctl", "list", label])
        if ok:
            details.append("Server agent: installed (loaded)")
        else:
            details.append("Server agent: installed (not loaded)")
    else:
        details.append("Server agent: not installed")

    # Check watchdog
    watchdog_plist = _launchd_watchdog_plist_path()
    if watchdog_plist.exists():
        ok, output = _run_cmd(["launchctl", "list", f"{label}.watchdog"])
        if ok:
            details.append("Watchdog agent: installed (loaded)")
        else:
            details.append("Watchdog agent: installed (not loaded)")
    else:
        details.append("Watchdog agent: not installed")

    installed = server_plist.exists() or watchdog_plist.exists()
    return ServiceResult(
        success=True,
        platform="macos",
        message="Installed" if installed else "Not installed",
        details=details,
    )
```

---

## File 5: `src/amplifier_distro/server/cli.py` (MODIFY)

**What to change**: Add a `watchdog` subcommand group to the existing `serve` Click group. Also update the module docstring.

### Change 1: Update module docstring

**Replace lines 1-10** with:

```python
"""CLI entry point for the distro server.

Usage:
    amp-distro-server [OPTIONS]                # foreground mode (default)
    amp-distro-server start [OPTIONS]          # start as background daemon
    amp-distro-server stop                     # stop background daemon
    amp-distro-server restart [OPTIONS]        # restart background daemon
    amp-distro-server status                   # check daemon status
    amp-distro-server watchdog start           # start health watchdog
    amp-distro-server watchdog stop            # stop health watchdog
    amp-distro-server watchdog status          # check watchdog status
    python -m amplifier_distro.server [OPTIONS]  # via module (foreground)
"""
```

### Change 2: Add watchdog commands after `_check_port` function

**Insert after line 186 (the end of `_check_port`), before line 189 (`def _run_foreground`).** Add this entire block:

```python

# ---------------------------------------------------------------------------
# Watchdog subcommands
# ---------------------------------------------------------------------------


@serve.group("watchdog", invoke_without_command=True)
@click.pass_context
def watchdog_group(ctx: click.Context) -> None:
    """Manage the server health watchdog."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(watchdog_status)


@watchdog_group.command("start")
@click.option(
    "--host",
    default="127.0.0.1",
    help="Server host to monitor",
)
@click.option(
    "--port",
    default=conventions.SERVER_DEFAULT_PORT,
    type=int,
    help="Server port to monitor",
)
@click.option(
    "--check-interval",
    default=30,
    type=int,
    help="Seconds between health checks",
)
@click.option(
    "--restart-after",
    default=300,
    type=int,
    help="Seconds of sustained downtime before restart",
)
@click.option(
    "--max-restarts",
    default=5,
    type=int,
    help="Max restart attempts (0 = unlimited)",
)
@click.option("--apps-dir", default=None, help="Server apps directory")
@click.option("--dev", is_flag=True, help="Server dev mode")
def watchdog_start(
    host: str,
    port: int,
    check_interval: int,
    restart_after: int,
    max_restarts: int,
    apps_dir: str | None,
    dev: bool,
) -> None:
    """Start the watchdog as a background process."""
    from amplifier_distro.server.watchdog import is_watchdog_running, start_watchdog

    if is_watchdog_running():
        click.echo("Watchdog is already running.", err=True)
        raise SystemExit(1)

    pid = start_watchdog(
        host=host,
        port=port,
        check_interval=check_interval,
        restart_after=restart_after,
        max_restarts=max_restarts,
        apps_dir=apps_dir,
        dev=dev,
    )
    click.echo(f"Watchdog started (PID {pid})")
    click.echo(f"  Monitoring: http://{host}:{port}/api/health")
    click.echo(f"  Check interval: {check_interval}s")
    click.echo(f"  Restart after: {restart_after}s downtime")


@watchdog_group.command("stop")
def watchdog_stop() -> None:
    """Stop the running watchdog."""
    from amplifier_distro.server.daemon import read_pid
    from amplifier_distro.server.watchdog import stop_watchdog, watchdog_pid_file_path

    wd_pid_file = watchdog_pid_file_path()
    pid = read_pid(wd_pid_file)
    if pid is None:
        click.echo("No watchdog PID file found — watchdog may not be running.")
        return

    click.echo(f"Stopping watchdog (PID {pid})...")
    stopped = stop_watchdog()
    if stopped:
        click.echo("Watchdog stopped.")
    else:
        click.echo("Could not stop watchdog.", err=True)
        raise SystemExit(1)


@watchdog_group.command("status")
def watchdog_status() -> None:
    """Check watchdog status."""
    from amplifier_distro.server.daemon import cleanup_pid, read_pid
    from amplifier_distro.server.watchdog import (
        is_watchdog_running,
        watchdog_pid_file_path,
    )

    wd_pid_file = watchdog_pid_file_path()
    pid = read_pid(wd_pid_file)
    running = is_watchdog_running()

    if running and pid is not None:
        click.echo(f"Watchdog is running (PID {pid})")
    elif pid is not None:
        click.echo(f"Watchdog is NOT running (stale PID file for PID {pid})")
        click.echo("  Cleaning up stale PID file...")
        cleanup_pid(wd_pid_file)
    else:
        click.echo("Watchdog is not running (no PID file)")
```

**Note**: All imports inside function bodies (lazy), matching the existing pattern in `start`, `stop`, `server_status`.

---

## File 6: `src/amplifier_distro/cli.py` (MODIFY)

### Change 1: Update EPILOG

**Replace line 41** (`  amp-distro update      Self-update to the latest release"""`)
with:

```python
  amp-distro update      Self-update to the latest release
  amp-distro service     Manage auto-start service (install/uninstall)"""
```

### Change 2: Add service command group

**Insert after line 331** (end of `update` function, before `# —— Internal helpers ——`), add this entire block:

```python

# —— Service commands ————————————————————————————————————————


@main.group("service")
def service_group() -> None:
    """Manage platform auto-start service (systemd/launchd)."""


@service_group.command("install")
@click.option(
    "--no-watchdog",
    is_flag=True,
    help="Install server only, without the health watchdog.",
)
def service_install(no_watchdog: bool) -> None:
    """Install the platform service for auto-start on boot."""
    from .service import install_service

    result = install_service(include_watchdog=not no_watchdog)
    if result.success:
        click.echo(f"Service installed ({result.platform})")
        for detail in result.details:
            click.echo(f"  {detail}")
    else:
        click.echo(f"Failed: {result.message}", err=True)
        for detail in result.details:
            click.echo(f"  {detail}", err=True)
        raise SystemExit(1)


@service_group.command("uninstall")
def service_uninstall() -> None:
    """Remove the platform auto-start service."""
    from .service import uninstall_service

    result = uninstall_service()
    if result.success:
        click.echo(f"Service removed ({result.platform})")
        for detail in result.details:
            click.echo(f"  {detail}")
    else:
        click.echo(f"Failed: {result.message}", err=True)
        raise SystemExit(1)


@service_group.command("status")
def service_cmd_status() -> None:
    """Check platform service status."""
    from .service import service_status

    result = service_status()
    click.echo(f"Platform: {result.platform}")
    click.echo(f"Status: {result.message}")
    for detail in result.details:
        click.echo(f"  {detail}")
```

---

## File 7: `scripts/amplifier-distro.service` (MODIFY)

**Replace the entire file with:**

```ini
[Unit]
Description=Amplifier Distro Server
After=network.target

[Service]
Type=simple
ExecStart=amp-distro-server --host 127.0.0.1 --port 8400
Restart=on-failure
RestartSec=5
WorkingDirectory=%h
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
```

**Only change**: Added `Environment=PATH=...` on line 11. This is the reference template; `install_service()` generates the actual unit with resolved paths at install time.

**Important for existing tests**: `TestSystemdServiceFile` in `test_daemon.py` tests this file. The existing tests check for `Unit`, `Service`, `Install` sections, `Restart=on-failure`, `After=network.target`, and `amp-distro-server` in `ExecStart`. All of these are preserved. The only addition is the `Environment` line which no existing test checks.

---

## File 8: `tests/test_watchdog.py` (CREATE)

**Full file contents:**

```python
"""Tests for server watchdog: health monitoring and automatic restart.

Tests cover:
1. Health check function (mocked HTTP)
2. Watchdog path construction from conventions
3. Watchdog loop logic (mocked time and daemon calls)
4. Watchdog start/stop process management
5. Watchdog CLI subcommands (mocked)
"""

import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from amplifier_distro import conventions
from amplifier_distro.server.daemon import write_pid
from amplifier_distro.server.watchdog import (
    check_health,
    is_watchdog_running,
    start_watchdog,
    stop_watchdog,
    watchdog_log_file_path,
    watchdog_pid_file_path,
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestCheckHealth:
    """Verify HTTP health check function."""

    @patch("amplifier_distro.server.watchdog.urllib.request.urlopen")
    def test_returns_true_for_200(self, mock_urlopen: MagicMock) -> None:
        """Health check succeeds when endpoint returns 200."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp
        assert check_health("http://127.0.0.1:8400/api/health") is True

    @patch("amplifier_distro.server.watchdog.urllib.request.urlopen")
    def test_returns_false_for_non_200(self, mock_urlopen: MagicMock) -> None:
        """Health check fails for non-200 status codes."""
        mock_resp = MagicMock()
        mock_resp.status = 503
        mock_urlopen.return_value = mock_resp
        assert check_health("http://127.0.0.1:8400/api/health") is False

    @patch("amplifier_distro.server.watchdog.urllib.request.urlopen")
    def test_returns_false_on_connection_error(self, mock_urlopen: MagicMock) -> None:
        """Health check fails when server is unreachable."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        assert check_health("http://127.0.0.1:8400/api/health") is False

    @patch("amplifier_distro.server.watchdog.urllib.request.urlopen")
    def test_returns_false_on_timeout(self, mock_urlopen: MagicMock) -> None:
        """Health check fails on socket timeout."""
        mock_urlopen.side_effect = OSError("timed out")
        assert check_health("http://127.0.0.1:8400/api/health") is False

    def test_returns_false_for_invalid_url(self) -> None:
        """Health check fails gracefully for malformed URL."""
        assert check_health("not-a-url") is False


# ---------------------------------------------------------------------------
# Path construction from conventions
# ---------------------------------------------------------------------------


class TestWatchdogPaths:
    """Verify watchdog paths are built from conventions, not hardcoded."""

    def test_watchdog_pid_file_uses_conventions(self) -> None:
        p = watchdog_pid_file_path()
        assert p.name == conventions.WATCHDOG_PID_FILE
        assert p.parent.name == conventions.SERVER_DIR

    def test_watchdog_log_file_uses_conventions(self) -> None:
        p = watchdog_log_file_path()
        assert p.name == conventions.WATCHDOG_LOG_FILE
        assert p.parent.name == conventions.SERVER_DIR

    def test_watchdog_pid_is_sibling_of_server_pid(self) -> None:
        """Watchdog PID file lives in the same directory as the server PID file."""
        from amplifier_distro.server.daemon import pid_file_path

        assert watchdog_pid_file_path().parent == pid_file_path().parent


# ---------------------------------------------------------------------------
# Watchdog loop logic
# ---------------------------------------------------------------------------


class TestWatchdogLoop:
    """Verify watchdog monitoring and restart logic.

    All tests mock time.monotonic, time.sleep, and daemon functions to
    exercise the loop logic without real delays or processes.
    """

    @patch("amplifier_distro.server.watchdog.cleanup_pid")
    @patch("amplifier_distro.server.watchdog.write_pid")
    @patch("amplifier_distro.server.watchdog._restart_server")
    @patch("amplifier_distro.server.watchdog.check_health")
    @patch("amplifier_distro.server.watchdog.time.monotonic")
    @patch("amplifier_distro.server.watchdog.time.sleep")
    def test_restarts_after_threshold(
        self,
        mock_sleep: MagicMock,
        mock_monotonic: MagicMock,
        mock_health: MagicMock,
        mock_restart: MagicMock,
        mock_write_pid: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """Server is restarted after restart_after seconds of sustained downtime."""
        # All health checks fail
        mock_health.return_value = False

        # Simulate time: first_failure at t=100, then check at t=200 (100s > 15s threshold)
        # monotonic calls: first_failure_time=100, elapsed check=200, reset (None),
        # then max_restarts=1 reached on second cycle
        mock_monotonic.side_effect = [100, 200, 300, 400]
        mock_sleep.return_value = None

        from amplifier_distro.server.watchdog import run_watchdog_loop

        run_watchdog_loop(
            check_interval=1,
            restart_after=15,
            max_restarts=1,
        )

        mock_restart.assert_called_once()

    @patch("amplifier_distro.server.watchdog.cleanup_pid")
    @patch("amplifier_distro.server.watchdog.write_pid")
    @patch("amplifier_distro.server.watchdog._restart_server")
    @patch("amplifier_distro.server.watchdog.check_health")
    @patch("amplifier_distro.server.watchdog.time.monotonic")
    @patch("amplifier_distro.server.watchdog.time.sleep")
    def test_resets_on_recovery(
        self,
        mock_sleep: MagicMock,
        mock_monotonic: MagicMock,
        mock_health: MagicMock,
        mock_restart: MagicMock,
        mock_write_pid: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """Failure timer resets when server recovers before threshold."""
        # fail, fail, success, fail, fail — then KeyboardInterrupt to exit
        mock_health.side_effect = [False, False, True, False, False, KeyboardInterrupt()]
        # Times: first fail sets t=100, second fail elapsed=110 (<300),
        # success resets, new fail sets t=200, second fail elapsed=210 (<300)
        mock_monotonic.side_effect = [100, 110, 200, 210]
        mock_sleep.return_value = None

        from amplifier_distro.server.watchdog import run_watchdog_loop

        try:
            run_watchdog_loop(check_interval=1, restart_after=300, max_restarts=5)
        except KeyboardInterrupt:
            pass

        mock_restart.assert_not_called()

    @patch("amplifier_distro.server.watchdog.cleanup_pid")
    @patch("amplifier_distro.server.watchdog.write_pid")
    @patch("amplifier_distro.server.watchdog._restart_server")
    @patch("amplifier_distro.server.watchdog.check_health")
    @patch("amplifier_distro.server.watchdog.time.monotonic")
    @patch("amplifier_distro.server.watchdog.time.sleep")
    def test_stops_after_max_restarts(
        self,
        mock_sleep: MagicMock,
        mock_monotonic: MagicMock,
        mock_health: MagicMock,
        mock_restart: MagicMock,
        mock_write_pid: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """Watchdog exits when max_restarts is exhausted."""
        mock_health.return_value = False
        mock_sleep.return_value = None
        # Each pair: first_failure_time, then elapsed check exceeds threshold
        mock_monotonic.side_effect = [0, 100, 200, 300, 400, 500, 600, 700]

        from amplifier_distro.server.watchdog import run_watchdog_loop

        run_watchdog_loop(check_interval=1, restart_after=1, max_restarts=3)

        assert mock_restart.call_count == 3

    @patch("amplifier_distro.server.watchdog.cleanup_pid")
    @patch("amplifier_distro.server.watchdog.write_pid")
    @patch("amplifier_distro.server.watchdog._restart_server")
    @patch("amplifier_distro.server.watchdog.check_health")
    @patch("amplifier_distro.server.watchdog.time.monotonic")
    @patch("amplifier_distro.server.watchdog.time.sleep")
    def test_healthy_server_no_restarts(
        self,
        mock_sleep: MagicMock,
        mock_monotonic: MagicMock,
        mock_health: MagicMock,
        mock_restart: MagicMock,
        mock_write_pid: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        """A consistently healthy server is never restarted."""
        # 3 healthy checks then KeyboardInterrupt
        mock_health.side_effect = [True, True, True, KeyboardInterrupt()]
        mock_sleep.return_value = None

        from amplifier_distro.server.watchdog import run_watchdog_loop

        try:
            run_watchdog_loop(check_interval=1, restart_after=300, max_restarts=5)
        except KeyboardInterrupt:
            pass

        mock_restart.assert_not_called()


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------


class TestStartWatchdog:
    """Verify watchdog background process spawning."""

    @patch("amplifier_distro.server.watchdog.subprocess.Popen")
    def test_spawns_background_process(
        self, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """start_watchdog returns the PID and writes a PID file."""
        mock_process = MagicMock()
        mock_process.pid = 99999
        mock_popen.return_value = mock_process
        pid_file = tmp_path / "watchdog.pid"

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=pid_file,
        ):
            pid = start_watchdog()

        assert pid == 99999
        assert pid_file.exists()
        assert pid_file.read_text().strip() == "99999"
        # Verify Popen was called with start_new_session
        call_kwargs = mock_popen.call_args
        assert call_kwargs.kwargs.get("start_new_session") is True

    @patch("amplifier_distro.server.watchdog.subprocess.Popen")
    def test_passes_all_options(self, mock_popen: MagicMock, tmp_path: Path) -> None:
        """start_watchdog passes all options through to the command."""
        mock_process = MagicMock()
        mock_process.pid = 11111
        mock_popen.return_value = mock_process

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=tmp_path / "watchdog.pid",
        ):
            start_watchdog(
                host="0.0.0.0",
                port=9000,
                check_interval=60,
                restart_after=600,
                max_restarts=10,
                apps_dir="/tmp/apps",
                dev=True,
            )

        cmd = mock_popen.call_args[0][0]
        assert "--host" in cmd
        assert "0.0.0.0" in cmd
        assert "--port" in cmd
        assert "9000" in cmd
        assert "--check-interval" in cmd
        assert "60" in cmd
        assert "--restart-after" in cmd
        assert "600" in cmd
        assert "--max-restarts" in cmd
        assert "10" in cmd
        assert "--apps-dir" in cmd
        assert "/tmp/apps" in cmd
        assert "--dev" in cmd


class TestStopWatchdog:
    """Verify watchdog stopping."""

    def test_returns_false_for_no_pid_file(self, tmp_path: Path) -> None:
        """stop_watchdog returns False when no PID file exists."""
        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=tmp_path / "nonexistent.pid",
        ):
            assert stop_watchdog() is False


class TestIsWatchdogRunning:
    """Verify watchdog liveness checking."""

    def test_returns_true_for_live_process(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "watchdog.pid"
        write_pid(pid_file)  # Write current process PID

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=pid_file,
        ):
            assert is_watchdog_running() is True

    def test_returns_false_for_no_pid_file(self, tmp_path: Path) -> None:
        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=tmp_path / "nonexistent.pid",
        ):
            assert is_watchdog_running() is False

    def test_returns_false_for_dead_pid(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "watchdog.pid"
        pid_file.write_text("4999999")

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=pid_file,
        ):
            assert is_watchdog_running() is False


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------


class TestWatchdogCli:
    """Verify watchdog CLI subcommands via CliRunner."""

    def test_watchdog_status_not_running(self, tmp_path: Path) -> None:
        """'watchdog status' reports when no watchdog is running."""
        pid_file = tmp_path / "watchdog.pid"

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=pid_file,
        ):
            from amplifier_distro.server.cli import serve

            runner = CliRunner()
            result = runner.invoke(serve, ["watchdog", "status"])

        assert result.exit_code == 0
        assert "not running" in result.output

    def test_watchdog_status_stale_pid_cleaned(self, tmp_path: Path) -> None:
        """'watchdog status' cleans up stale PID file."""
        pid_file = tmp_path / "watchdog.pid"
        pid_file.write_text("4999999")  # Dead PID

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=pid_file,
        ):
            from amplifier_distro.server.cli import serve

            runner = CliRunner()
            result = runner.invoke(serve, ["watchdog", "status"])

        assert "stale PID" in result.output
        assert not pid_file.exists()

    @patch("amplifier_distro.server.watchdog.subprocess.Popen")
    def test_watchdog_start(self, mock_popen: MagicMock, tmp_path: Path) -> None:
        """'watchdog start' spawns the watchdog and reports PID."""
        mock_process = MagicMock()
        mock_process.pid = 88888
        mock_popen.return_value = mock_process
        pid_file = tmp_path / "watchdog.pid"

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=pid_file,
        ):
            from amplifier_distro.server.cli import serve

            runner = CliRunner()
            result = runner.invoke(serve, ["watchdog", "start"])

        assert result.exit_code == 0
        assert "88888" in result.output
        assert "Monitoring" in result.output

    def test_watchdog_start_rejects_when_running(self, tmp_path: Path) -> None:
        """'watchdog start' fails if watchdog is already running."""
        pid_file = tmp_path / "watchdog.pid"
        write_pid(pid_file)  # Current process = "running"

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=pid_file,
        ):
            from amplifier_distro.server.cli import serve

            runner = CliRunner()
            result = runner.invoke(serve, ["watchdog", "start"])

        assert result.exit_code != 0
        assert "already running" in result.output

    def test_watchdog_stop_no_pid(self, tmp_path: Path) -> None:
        """'watchdog stop' reports when no PID file exists."""
        pid_file = tmp_path / "watchdog.pid"

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=pid_file,
        ):
            from amplifier_distro.server.cli import serve

            runner = CliRunner()
            result = runner.invoke(serve, ["watchdog", "stop"])

        assert result.exit_code == 0
        assert "No watchdog PID file" in result.output

    def test_watchdog_default_shows_status(self, tmp_path: Path) -> None:
        """'watchdog' without subcommand shows status."""
        pid_file = tmp_path / "watchdog.pid"

        with patch(
            "amplifier_distro.server.watchdog.watchdog_pid_file_path",
            return_value=pid_file,
        ):
            from amplifier_distro.server.cli import serve

            runner = CliRunner()
            result = runner.invoke(serve, ["watchdog"])

        assert result.exit_code == 0
        assert "not running" in result.output
```

---

## File 9: `tests/test_service.py` (CREATE)

**Full file contents:**

```python
"""Tests for platform service registration.

Tests cover:
1. Platform detection
2. Systemd unit file generation and INI validation
3. Launchd plist generation and XML validation
4. Install/uninstall dispatch (mocked subprocess)
5. Service status checking
6. Service CLI subcommands (mocked)
"""

import configparser
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from amplifier_distro import conventions
from amplifier_distro.service import (
    ServiceResult,
    detect_platform,
    install_service,
    service_status,
    uninstall_service,
)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


class TestDetectPlatform:
    """Verify platform detection returns correct platform strings."""

    @patch("amplifier_distro.service.platform.system", return_value="Linux")
    def test_detects_linux(self, _mock: MagicMock) -> None:
        assert detect_platform() == "linux"

    @patch("amplifier_distro.service.platform.system", return_value="Darwin")
    def test_detects_macos(self, _mock: MagicMock) -> None:
        assert detect_platform() == "macos"

    @patch("amplifier_distro.service.platform.system", return_value="Windows")
    def test_windows_returns_unsupported(self, _mock: MagicMock) -> None:
        assert detect_platform() == "unsupported"

    @patch("amplifier_distro.service.platform.system", return_value="FreeBSD")
    def test_unknown_returns_unsupported(self, _mock: MagicMock) -> None:
        assert detect_platform() == "unsupported"


# ---------------------------------------------------------------------------
# Systemd unit generation
# ---------------------------------------------------------------------------


class TestSystemdServerUnit:
    """Verify systemd server unit file generation."""

    def _generate(self, server_bin: str = "/usr/local/bin/amp-distro-server") -> str:
        from amplifier_distro.service import _generate_systemd_server_unit

        return _generate_systemd_server_unit(server_bin)

    def _parse(self, content: str) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        parser.read_string(content)
        return parser

    def test_valid_ini(self) -> None:
        """Generated unit is valid INI with all required sections."""
        parser = self._parse(self._generate())
        assert "Unit" in parser
        assert "Service" in parser
        assert "Install" in parser

    def test_restart_on_failure(self) -> None:
        parser = self._parse(self._generate())
        assert parser["Service"]["Restart"] == "on-failure"

    def test_after_network(self) -> None:
        parser = self._parse(self._generate())
        assert "network.target" in parser["Unit"]["After"]

    def test_correct_exec_start(self) -> None:
        content = self._generate("/my/custom/path/amp-distro-server")
        assert "/my/custom/path/amp-distro-server" in content

    def test_has_environment_path(self) -> None:
        content = self._generate()
        assert "Environment" in content
        assert "PATH=" in content

    def test_default_port(self) -> None:
        content = self._generate()
        assert str(conventions.SERVER_DEFAULT_PORT) in content

    def test_wanted_by_default_target(self) -> None:
        parser = self._parse(self._generate())
        assert parser["Install"]["WantedBy"] == "default.target"


class TestSystemdWatchdogUnit:
    """Verify systemd watchdog unit file generation."""

    def _generate(self, server_bin: str = "/usr/local/bin/amp-distro-server") -> str:
        from amplifier_distro.service import _generate_systemd_watchdog_unit

        return _generate_systemd_watchdog_unit(server_bin)

    def _parse(self, content: str) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        parser.read_string(content)
        return parser

    def test_valid_ini(self) -> None:
        parser = self._parse(self._generate())
        assert "Unit" in parser
        assert "Service" in parser
        assert "Install" in parser

    def test_restart_always(self) -> None:
        """Watchdog service must always restart -- it should never stay dead."""
        parser = self._parse(self._generate())
        assert parser["Service"]["Restart"] == "always"

    def test_depends_on_server(self) -> None:
        """Watchdog unit must declare After and Wants on the server unit."""
        parser = self._parse(self._generate())
        assert conventions.SERVICE_NAME in parser["Unit"]["After"]
        assert conventions.SERVICE_NAME in parser["Unit"]["Wants"]

    def test_runs_watchdog_module(self) -> None:
        content = self._generate()
        assert "amplifier_distro.server.watchdog" in content

    def test_has_environment_path(self) -> None:
        content = self._generate()
        assert "PATH=" in content


# ---------------------------------------------------------------------------
# Launchd plist generation
# ---------------------------------------------------------------------------


class TestLaunchdServerPlist:
    """Verify launchd server plist generation."""

    def _generate(self, server_bin: str = "/usr/local/bin/amp-distro-server") -> str:
        from amplifier_distro.service import _generate_launchd_server_plist

        return _generate_launchd_server_plist(server_bin)

    def test_valid_xml(self) -> None:
        """Generated plist must parse as valid XML."""
        ET.fromstring(self._generate())

    def test_correct_label(self) -> None:
        content = self._generate()
        assert conventions.LAUNCHD_LABEL in content

    def test_run_at_load(self) -> None:
        content = self._generate()
        assert "RunAtLoad" in content

    def test_correct_program(self) -> None:
        content = self._generate("/my/path/amp-distro-server")
        assert "/my/path/amp-distro-server" in content

    def test_keep_alive(self) -> None:
        content = self._generate()
        assert "KeepAlive" in content

    def test_default_port(self) -> None:
        content = self._generate()
        assert str(conventions.SERVER_DEFAULT_PORT) in content

    def test_has_environment_path(self) -> None:
        content = self._generate()
        assert "PATH" in content


class TestLaunchdWatchdogPlist:
    """Verify launchd watchdog plist generation."""

    def _generate(self, python_bin: str = "/usr/bin/python3") -> str:
        from amplifier_distro.service import _generate_launchd_watchdog_plist

        return _generate_launchd_watchdog_plist(python_bin)

    def test_valid_xml(self) -> None:
        ET.fromstring(self._generate())

    def test_watchdog_label(self) -> None:
        content = self._generate()
        assert f"{conventions.LAUNCHD_LABEL}.watchdog" in content

    def test_runs_watchdog_module(self) -> None:
        content = self._generate()
        assert "amplifier_distro.server.watchdog" in content

    def test_keep_alive_true(self) -> None:
        """Watchdog agent must use KeepAlive=true (always running)."""
        content = self._generate()
        assert "KeepAlive" in content

    def test_correct_python(self) -> None:
        content = self._generate("/my/venv/bin/python3")
        assert "/my/venv/bin/python3" in content


# ---------------------------------------------------------------------------
# Install/uninstall dispatch
# ---------------------------------------------------------------------------


class TestInstallDispatch:
    """Verify install_service dispatches to the correct platform handler."""

    @patch("amplifier_distro.service.detect_platform", return_value="unsupported")
    def test_unsupported_platform_returns_failure(self, _mock: MagicMock) -> None:
        result = install_service()
        assert result.success is False
        assert "Unsupported" in result.message

    @patch("amplifier_distro.service.detect_platform", return_value="linux")
    @patch("amplifier_distro.service._install_systemd")
    def test_linux_delegates_to_systemd(
        self, mock_install: MagicMock, _mock_plat: MagicMock
    ) -> None:
        mock_install.return_value = ServiceResult(
            success=True, platform="linux", message="OK"
        )
        install_service(include_watchdog=True)
        mock_install.assert_called_once_with(True)

    @patch("amplifier_distro.service.detect_platform", return_value="macos")
    @patch("amplifier_distro.service._install_launchd")
    def test_macos_delegates_to_launchd(
        self, mock_install: MagicMock, _mock_plat: MagicMock
    ) -> None:
        mock_install.return_value = ServiceResult(
            success=True, platform="macos", message="OK"
        )
        install_service(include_watchdog=False)
        mock_install.assert_called_once_with(False)


class TestUninstallDispatch:
    """Verify uninstall_service dispatches correctly."""

    @patch("amplifier_distro.service.detect_platform", return_value="unsupported")
    def test_unsupported_returns_failure(self, _mock: MagicMock) -> None:
        result = uninstall_service()
        assert result.success is False

    @patch("amplifier_distro.service.detect_platform", return_value="linux")
    @patch("amplifier_distro.service._uninstall_systemd")
    def test_linux_delegates_to_systemd(
        self, mock_uninstall: MagicMock, _mock_plat: MagicMock
    ) -> None:
        mock_uninstall.return_value = ServiceResult(
            success=True, platform="linux", message="Removed"
        )
        uninstall_service()
        mock_uninstall.assert_called_once()


class TestServiceStatus:
    """Verify service_status dispatches and returns."""

    @patch("amplifier_distro.service.detect_platform", return_value="unsupported")
    def test_unsupported_returns_info(self, _mock: MagicMock) -> None:
        result = service_status()
        assert result.success is True
        assert result.platform == "unsupported"


# ---------------------------------------------------------------------------
# Systemd install (mocked filesystem + subprocess)
# ---------------------------------------------------------------------------


class TestInstallSystemd:
    """Verify _install_systemd with mocked shutil.which and subprocess."""

    @patch("amplifier_distro.service._run_cmd", return_value=(True, ""))
    @patch(
        "amplifier_distro.service._find_server_binary",
        return_value="/usr/local/bin/amp-distro-server",
    )
    def test_install_creates_unit_files(
        self, _mock_bin: MagicMock, _mock_cmd: MagicMock, tmp_path: Path
    ) -> None:
        from amplifier_distro.service import _install_systemd

        with patch(
            "amplifier_distro.service._systemd_dir", return_value=tmp_path
        ):
            result = _install_systemd(include_watchdog=True)

        assert result.success is True
        # Check files were created
        server_file = tmp_path / f"{conventions.SERVICE_NAME}.service"
        watchdog_file = tmp_path / f"{conventions.SERVICE_NAME}-watchdog.service"
        assert server_file.exists()
        assert watchdog_file.exists()

    @patch("amplifier_distro.service._find_server_binary", return_value=None)
    def test_install_fails_without_binary(self, _mock_bin: MagicMock) -> None:
        from amplifier_distro.service import _install_systemd

        result = _install_systemd(include_watchdog=True)
        assert result.success is False
        assert "not found" in result.message

    @patch("amplifier_distro.service._run_cmd", return_value=(True, ""))
    @patch(
        "amplifier_distro.service._find_server_binary",
        return_value="/usr/local/bin/amp-distro-server",
    )
    def test_install_without_watchdog(
        self, _mock_bin: MagicMock, _mock_cmd: MagicMock, tmp_path: Path
    ) -> None:
        from amplifier_distro.service import _install_systemd

        with patch(
            "amplifier_distro.service._systemd_dir", return_value=tmp_path
        ):
            result = _install_systemd(include_watchdog=False)

        assert result.success is True
        watchdog_file = tmp_path / f"{conventions.SERVICE_NAME}-watchdog.service"
        assert not watchdog_file.exists()


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------


class TestServiceCli:
    """Verify service CLI subcommands via CliRunner."""

    @patch("amplifier_distro.service.install_service")
    def test_install_success(self, mock_install: MagicMock) -> None:
        mock_install.return_value = ServiceResult(
            success=True,
            platform="linux",
            message="Installed",
            details=["Server enabled", "Watchdog enabled"],
        )
        from amplifier_distro.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["service", "install"])

        assert result.exit_code == 0
        assert "installed" in result.output.lower()

    @patch("amplifier_distro.service.install_service")
    def test_install_failure(self, mock_install: MagicMock) -> None:
        mock_install.return_value = ServiceResult(
            success=False,
            platform="unsupported",
            message="Unsupported platform.",
        )
        from amplifier_distro.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["service", "install"])

        assert result.exit_code != 0

    @patch("amplifier_distro.service.install_service")
    def test_install_no_watchdog_flag(self, mock_install: MagicMock) -> None:
        mock_install.return_value = ServiceResult(
            success=True, platform="linux", message="OK"
        )
        from amplifier_distro.cli import main

        runner = CliRunner()
        runner.invoke(main, ["service", "install", "--no-watchdog"])

        mock_install.assert_called_once_with(include_watchdog=False)

    @patch("amplifier_distro.service.uninstall_service")
    def test_uninstall_success(self, mock_uninstall: MagicMock) -> None:
        mock_uninstall.return_value = ServiceResult(
            success=True, platform="linux", message="Removed"
        )
        from amplifier_distro.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["service", "uninstall"])

        assert result.exit_code == 0

    @patch("amplifier_distro.service.service_status")
    def test_status(self, mock_status: MagicMock) -> None:
        mock_status.return_value = ServiceResult(
            success=True,
            platform="linux",
            message="Installed",
            details=["Server: active", "Watchdog: active"],
        )
        from amplifier_distro.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["service", "status"])

        assert result.exit_code == 0
        assert "linux" in result.output.lower()
        assert "Server: active" in result.output


# ---------------------------------------------------------------------------
# ServiceResult model
# ---------------------------------------------------------------------------


class TestServiceResult:
    """Verify the ServiceResult Pydantic model."""

    def test_defaults(self) -> None:
        result = ServiceResult(success=True, platform="linux", message="OK")
        assert result.details == []

    def test_with_details(self) -> None:
        result = ServiceResult(
            success=True,
            platform="macos",
            message="Done",
            details=["step 1", "step 2"],
        )
        assert len(result.details) == 2
```

---

## File 10: `tests/test_conventions.py` (MODIFY)

**What to change**: Add 4 new pinning tests to the `TestCanonicalValues` class.

**Insert after line 93** (end of `test_server_default_port`), before line 95 (`test_interfaces_dir`):

```python
    def test_watchdog_pid_file(self):
        assert conventions.WATCHDOG_PID_FILE == "watchdog.pid"

    def test_watchdog_log_file(self):
        assert conventions.WATCHDOG_LOG_FILE == "watchdog.log"

    def test_service_name(self):
        assert conventions.SERVICE_NAME == "amplifier-distro"

    def test_launchd_label(self):
        assert conventions.LAUNCHD_LABEL == "com.amplifier.distro"
```

**Also add to `TestStringConstants.FILENAME_CONSTANTS`** list (after `"SERVER_PID_FILE"` on line 142):

```python
        "WATCHDOG_PID_FILE",
        "WATCHDOG_LOG_FILE",
        "SERVICE_NAME",
        "LAUNCHD_LABEL",
```

**Also add to `TestCrossModuleReferences`** (new test method after line 324):

```python
    def test_constants_used_by_watchdog(self):
        """server/watchdog.py uses WATCHDOG_PID_FILE and WATCHDOG_LOG_FILE."""
        assert hasattr(conventions, "WATCHDOG_PID_FILE")
        assert hasattr(conventions, "WATCHDOG_LOG_FILE")

    def test_constants_used_by_service(self):
        """service.py uses SERVICE_NAME and LAUNCHD_LABEL."""
        assert hasattr(conventions, "SERVICE_NAME")
        assert hasattr(conventions, "LAUNCHD_LABEL")
```

---

## Summary of All Changes

| # | File | Action | Est. Lines |
|---|------|--------|-----------|
| 1 | `src/amplifier_distro/conventions.py` | MODIFY: add 4 constants after line 72 | +7 |
| 2 | `src/amplifier_distro/schema.py` | MODIFY: add WatchdogConfig + field | +13 |
| 3 | `src/amplifier_distro/server/watchdog.py` | CREATE | ~300 |
| 4 | `src/amplifier_distro/service.py` | CREATE | ~420 |
| 5 | `src/amplifier_distro/server/cli.py` | MODIFY: add watchdog subgroup | +100 |
| 6 | `src/amplifier_distro/cli.py` | MODIFY: add service subgroup + epilog | +55 |
| 7 | `scripts/amplifier-distro.service` | MODIFY: add Environment line | +1 |
| 8 | `tests/test_watchdog.py` | CREATE | ~310 |
| 9 | `tests/test_service.py` | CREATE | ~310 |
| 10 | `tests/test_conventions.py` | MODIFY: add 4 pin tests + cross-ref | +18 |

---

## Success Criteria

1. `uv run python -m pytest tests/ -x -q` passes all 755 existing tests plus ~55 new tests
2. `amp-distro-server watchdog start` starts watchdog, writes PID, prints monitoring info
3. `amp-distro-server watchdog stop` stops watchdog, cleans PID
4. `amp-distro-server watchdog status` reports running/not-running/stale
5. `amp-distro-server watchdog` (no subcommand) shows status
6. `amp-distro service install` installs platform service, prints details
7. `amp-distro service install --no-watchdog` installs server-only service
8. `amp-distro service uninstall` removes platform service
9. `amp-distro service status` reports installed/not-installed state
10. All 4 new conventions are pinned in test_conventions.py
11. No new dependencies added (stdlib + pydantic only)
12. `uv run python -m pytest tests/test_watchdog.py -x -q` passes in isolation
13. `uv run python -m pytest tests/test_service.py -x -q` passes in isolation

---

## Patterns to Follow (Reference)

**Import style**: `from amplifier_distro import conventions` (not `from amplifier_distro.conventions import X`). Lazy imports inside CLI function bodies.

**Path construction**: Always `server_dir() / conventions.CONSTANT`, never hardcoded strings.

**CLI pattern**: Click commands with lazy imports:
```python
@serve.command()
def my_command() -> None:
    """Docstring."""
    from amplifier_distro.server.watchdog import some_function  # lazy
    # ... body
```

**Test pattern**: pytest classes, `tmp_path` fixture, `@patch` at module level, `CliRunner()`:
```python
class TestMyThing:
    """One-line description."""

    def test_specific_behavior(self, tmp_path: Path) -> None:
        # ... body with one assertion
```

**Mock pattern for PID files**: Patch `watchdog_pid_file_path` to return `tmp_path / "watchdog.pid"`.

**Mock pattern for subprocess**: Patch `amplifier_distro.server.watchdog.subprocess.Popen`.
