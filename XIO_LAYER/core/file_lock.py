"""Portable exclusive sidecar-file locking for local persistence ports."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class FileLockError(RuntimeError):
    """Raised when a persistence sidecar lock cannot be managed."""


@contextmanager
def exclusive_file_lock(path: str | Path):
    """Hold an exclusive lock on a sidecar file until the context exits."""

    lock_path = Path(path)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = lock_path.open("a+b")
    except OSError as exc:
        raise FileLockError("persistence lock could not be opened") from exc

    acquired = False
    try:
        try:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            acquired = True
        except OSError as exc:
            raise FileLockError("persistence lock could not be acquired") from exc

        try:
            yield
        finally:
            if acquired:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                except OSError as exc:
                    raise FileLockError("persistence lock could not be released") from exc
    finally:
        stream.close()


__all__ = ["FileLockError", "exclusive_file_lock"]
