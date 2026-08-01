"""Shared capture-file handling for the Jeep Cherokee KL tools.

No hardware dependency, so offline tools can import it too.
"""
from pathlib import Path


def resolve_capture_path(raw, base_file):
    """Resolve a capture path against the tool's own directory, not the cwd.

    A relative path resolved against the caller's cwd meant `captures/x.csv`
    failed depending on where the tool was invoked from — after a successful
    30-second capture, which was then lost.
    """
    path = Path(raw)
    if not path.is_absolute():
        path = Path(base_file).resolve().parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def guard_capture_path(path, force=False):
    """Refuse to overwrite an existing capture unless explicitly forced.

    A capture cannot be reproduced on demand — a drive least of all. Rerunning a
    command with the same --log/--out path silently destroyed a 115-second drive
    capture, which is exactly the kind of loss that must be made impossible rather
    than remembered.
    """
    if path.exists() and not force:
        size = path.stat().st_size
        raise SystemExit(
            f"Refusing to overwrite an existing capture:\n"
            f"  {path}  ({size:,} bytes)\n\n"
            f"Captures cannot be reproduced on demand. Either:\n"
            f"  - pick a new filename, or\n"
            f"  - pass --force to overwrite this one deliberately\n"
        )
