"""Server startup utilities: structured logging, key export.

Handles server initialization tasks that run before the main event loop:
- Structured logging (JSON to file, human-readable to console)
- API key export from keys.yaml into the environment
- Server version and configuration logging

All paths are constructed from conventions.py constants.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from logging.handlers import RotatingFileHandler
from pathlib import Path

from amplifier_distro import conventions

logger = logging.getLogger(__name__)


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
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    """Configure structured logging: JSON to file, human-readable to console."""
    root = logging.getLogger()
    # Prevent duplicate handlers on uvicorn reload
    if root.handlers:
        return

    if log_file is None:
        log_file = log_file_path()

    log_file.parent.mkdir(parents=True, exist_ok=True)

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

    # File handler: JSON structured (with rotation)
    file_handler = RotatingFileHandler(
        str(log_file), maxBytes=10 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(JSONFormatter())
    root.addHandler(file_handler)


def env_file_paths() -> list[Path]:
    """Return .env file search paths in priority order."""
    paths = [Path(conventions.AMPLIFIER_HOME).expanduser() / ".env"]
    # Also check the distro project directory (editable install)
    try:
        import amplifier_distro

        pkg_dir = Path(amplifier_distro.__file__).parent.parent.parent
        project_env = pkg_dir / ".env"
        if project_env.exists():
            paths.append(project_env)
    except (AttributeError, TypeError, OSError):
        logger.debug(
            "Could not determine package directory for .env search", exc_info=True
        )
    return paths


def load_env_file(env_file: Path | None = None) -> list[str]:
    """Load environment variables from a .env file.

    Parses simple ``KEY=value`` lines (with optional quoting) and sets
    them via ``os.environ.setdefault`` so existing env vars take
    precedence.
    """
    files = [env_file] if env_file is not None else env_file_paths()
    loaded: list[str] = []

    for path in files:
        if path is None or not path.exists():
            continue
        try:
            for raw_line in path.read_text().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Strip matching quotes
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if key:
                    os.environ.setdefault(key, value)
                    loaded.append(key)
        except OSError:
            continue

    return loaded


def export_keys(keys_file: Path | None = None) -> list[str]:
    """Export keys from keys.yaml as environment variables."""
    import yaml

    if keys_file is None:
        keys_file = keys_file_path()

    if not keys_file.exists():
        return []

    try:
        data = yaml.safe_load(keys_file.read_text())
    except (yaml.YAMLError, OSError) as e:
        logger.warning("Failed to parse keys file %s: %s", keys_file, e)
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


def check_foundation_available() -> bool:
    """Verify amplifier-foundation is importable at server startup.

    Returns True if foundation is available, False otherwise.
    Logs a clear error message on failure so operators know what to fix.
    """
    try:
        from amplifier_foundation import load_bundle  # noqa: F401

        logger.info("amplifier-foundation: available")
        return True
    except ImportError:
        logger.warning(
            "amplifier-foundation is not installed. "
            "The server will not be able to create sessions. "
            "Install with: uv pip install amplifier-foundation"
        )
        return False


def check_legacy_config() -> None:
    """Log a notice if the old distro.yaml config file exists."""
    legacy = Path(conventions.AMPLIFIER_HOME).expanduser() / "distro.yaml"
    if legacy.exists():
        logger.info(
            "Found legacy distro.yaml at %s. "
            "This file is no longer used -- configuration is now via "
            "environment variables and foundation's settings.yaml. "
            "You can safely delete it.",
            legacy,
        )


def log_startup_info(
    *,
    host: str,
    port: int,
    apps: list[str],
    dev_mode: bool,
    logger: logging.Logger,
) -> None:
    """Log server version, port, and loaded apps at startup."""
    try:
        from importlib.metadata import version as pkg_version

        version = pkg_version("amplifier-distro")
    except (ImportError, PackageNotFoundError):
        logger.debug(
            "Could not determine package version, using default", exc_info=True
        )
        version = "0.1.0"

    logger.info("Amplifier Distro Server v%s", version)
    logger.info("Bind: %s:%d (dev_mode=%s)", host, port, dev_mode)
    if apps:
        logger.info("Loaded apps: %s", ", ".join(apps))
    else:
        logger.info("No apps loaded")

    check_foundation_available()
    check_legacy_config()
