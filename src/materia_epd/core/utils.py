import os
import re
from pathlib import Path
from typing import Optional, Tuple


def to_float(value, positive=False):
    """Convert to float; if positive=True, return None for <= 0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if (not positive or f > 0) else None


def _extract_version(name: str) -> Optional[Tuple[int, ...]]:
    """Extract version tuple from filename (e.g. 1.0.2) or None if absent."""
    pattern = re.compile(r"version\.?(\d+(?:\.\d+)*)", re.IGNORECASE)
    match = pattern.search(name)
    if not match:
        return None
    return tuple(int(p) for p in match.group(1).split("."))


def sort_key(p: Path):
    v = _extract_version(p.name)
    return (
        v is not None,
        v or tuple(),
        p.stat().st_mtime,
    )


def qn_uri(uri: str, name: str) -> str:
    return f"{{{uri}}}{name}"


def copy_except_folders(src_dir, dest_dir, exclude_folders):
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in exclude_folders]

        rel_path = os.path.relpath(root, src_dir)
        target_root = os.path.join(dest_dir, rel_path)
        os.makedirs(target_root, exist_ok=True)

        for file in files:
            src_file = os.path.join(root, file)
            dest_file = os.path.join(target_root, file)
            with open(src_file, "rb") as f_src, open(dest_file, "wb") as f_dest:
                f_dest.write(f_src.read())
