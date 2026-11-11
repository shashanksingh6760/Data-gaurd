#!/usr/bin/env python3
"""
Script to generate synthetic datasets for DataGuard.
"""

import sys
from pathlib import Path

# Add src to pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dataguard.cli import app

if __name__ == "__main__":
    sys.argv = ["dataguard", "generate"] + sys.argv[1:]
    app()
