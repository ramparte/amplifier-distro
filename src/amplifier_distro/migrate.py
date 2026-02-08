"""Memory store migration from legacy to canonical location."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import load_config

# Files that belong to the memory store
MEMORY_FILES = ["memory-store.yaml", "work-log.yaml", "project-notes.md", "README.md"]


@dataclass
class MigrationResult:
    migrated: bool
    source: str
    destination: str
    files_moved: list[str] = field(default_factory=list)
    message: str = ""


def migrate_memory() -> MigrationResult:
    """Migrate memory store from legacy location to canonical ~/.amplifier/memory/.

    Checks legacy paths from config, moves files if canonical doesn't exist yet,
    and creates a symlink from old location for backward compatibility.
    """
    config = load_config()
    canonical = Path(config.memory.path).expanduser()

    # If canonical already exists, nothing to migrate
    if canonical.is_dir():
        return MigrationResult(
            migrated=False,
            source="",
            destination=str(canonical),
            message=f"Memory store already at {canonical}",
        )

    # Check each legacy path for an existing memory store
    for legacy_str in config.memory.legacy_paths:
        legacy = Path(legacy_str).expanduser()
        if legacy.is_dir():
            return _move_legacy(legacy, canonical)

    # Neither exists — initialize empty canonical directory
    canonical.mkdir(parents=True, exist_ok=True)
    return MigrationResult(
        migrated=False,
        source="",
        destination=str(canonical),
        message="Initialized empty memory store",
    )


def _move_legacy(legacy: Path, canonical: Path) -> MigrationResult:
    """Move memory files from *legacy* to *canonical* and leave a symlink."""
    canonical.mkdir(parents=True, exist_ok=True)

    moved: list[str] = []
    for name in MEMORY_FILES:
        src = legacy / name
        if src.exists():
            shutil.move(str(src), str(canonical / name))
            moved.append(name)

    # Replace legacy directory with a symlink to canonical
    # Remove remaining contents (if any) before replacing with symlink
    shutil.rmtree(legacy)
    legacy.symlink_to(canonical)

    return MigrationResult(
        migrated=True,
        source=str(legacy),
        destination=str(canonical),
        files_moved=moved,
        message=f"Migrated {len(moved)} file(s) from {legacy} → {canonical}",
    )
