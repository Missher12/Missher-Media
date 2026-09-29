#!/usr/bin/env python3
from pathlib import Path
import sys


RUNTIME_PARENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_PARENT))

from media_missher_runtime.cli import main


if __name__ == "__main__":
    raise SystemExit(main(fixed_platform="xhs"))
