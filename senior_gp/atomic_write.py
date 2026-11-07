"""Crash-safe atomic file replacement, following the sibling tools."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Replace path with complete content and fsync the containing directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path: Path | None = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        fsync_directory(path.parent)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_replace_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Encode and atomically replace a text file."""
    atomic_replace_bytes(path, content.encode(encoding))


def fsync_directory(directory: Path) -> None:
    """Make a rename or new entry in directory durable."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
