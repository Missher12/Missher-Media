"""Load the same content-free protocol used by the installed collection core."""
import importlib.util
import os
import stat
from pathlib import Path


def load_progress(runtime_root):
    path = Path(runtime_root) / "media_missher_runtime" / "progress.py"
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("progress module invalid")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError("progress module invalid")
    spec = importlib.util.spec_from_file_location("_media_missher_progress", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
