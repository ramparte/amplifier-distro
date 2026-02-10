"""Server startup utilities: structured logging, key export, pre-flight checks.

Handles server initialization tasks that run before the main event loop:
- Structured logging (JSON to file, human-readable to console)
- API key export from keys.yaml into the environment
- Pre-flight health checks with result logging
- Server version and configuration logging

All paths are constructed from conventions.py constants — no hardcoded paths.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from amplifier_distro import conventions


def log_file_path() -> Path:
    """Return the server log file path, constructed from conventions."""
    return (
        Path(conventions.AMPLIFIER_HOME).expanduser()
        / conventions.SERVER_DIR
        / conventions.SERVER_LOG_FILE
    )


def keys_file_path() -> Path:
    """Return the keys.yaml path, constructed from conventions."""
    return Path(conventions.AMPLIFIER_HOME).expanduser() / conventions.KEYS_FILENAME


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured file logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string."""
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=UTC
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    """Configure structured logging: JSON to file, human-readable to console.

    Args:
        log_file: Path for the JSON log file. Uses convention default if None.
        level: Logging level for both handlers.
    """
    if log_file is None:
        log_file = log_file_path()

    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # Console handler: human-readable
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(console_handler)

    # File handler: JSON structured
    file_handler = logging.FileHandler(str(log_file))
    file_handler.setFormatter(JSONFormatter())
    root.addHandler(file_handler)


def export_keys(keys_file: Path | None = None) -> list[str]:
    """Export keys from keys.yaml as environment variables.

    Reads the keys file and sets each key-value pair as an environment
    variable using ``os.environ.setdefault`` so that existing env vars
    take precedence.

    Args:
        keys_file: Path to keys.yaml. Uses convention default if None.

    Returns:
        List of exported environment variable names (values are not
        included for security).
    """
    import yaml

    if keys_file is None:
        keys_file = keys_file_path()

    if not keys_file.exists():
        return []

    try:
        data = yaml.safe_load(keys_file.read_text())
    except Exception:
        return []

    if not isinstance(data, dict):
        return []

    exported: list[str] = []
    for key, value in data.items():
        if isinstance(value, str) and value:
            env_name = str(key)
            os.environ.setdefault(env_name, value)
            exported.append(env_name)

    return exported


def log_startup_info(
    *,
    host: str,
    port: int,
    apps: list[str],
    dev_mode: bool,
    logger: logging.Logger,
) -> None:
    """Log server version, port, and loaded apps at startup.

    Args:
        host: Bind host address.
        port: Bind port number.
        apps: List of loaded app names.
        dev_mode: Whether the server is running in dev mode.
        logger: Logger instance to write to.
    """
    try:
        from importlib.metadata import version as pkg_version

        version = pkg_version("amplifier-distro")
    except Exception:
        version = "0.1.0"

    logger.info("Amplifier Distro Server v%s", version)
    logger.info("Bind: %s:%d (dev_mode=%s)", host, port, dev_mode)
    if apps:
        logger.info("Loaded apps: %s", ", ".join(apps))
    else:
        logger.info("No apps loaded")


def run_startup_checks(logger: logging.Logger) -> None:
    """Run pre-flight checks and log results.

    Does not block server startup — issues are logged as warnings.

    Args:
        logger: Logger instance to write to.
    """
    try:
        from amplifier_distro.preflight import run_preflight

        report = run_preflight()

        for check in report.checks:
            if check.passed:
                logger.info("Preflight %-20s OK: %s", check.name, check.message)
            elif check.severity == "warning":
                logger.warning("Preflight %-20s WARN: %s", check.name, check.message)
            else:
                logger.error("Preflight %-20s FAIL: %s", check.name, check.message)

        if report.passed:
            logger.info("Pre-flight checks passed")
        else:
            logger.warning("Pre-flight checks have failures (server will continue)")
    except Exception:
        logger.exception("Pre-flight checks could not run")
