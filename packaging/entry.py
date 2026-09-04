"""Frozen-app entry point.

PyInstaller needs a real script rather than a console-script entry point.
Keeping this as a thin shim (instead of pointing the spec at
costsight/desktop.py directly) means the frozen build and the
``costsight-desktop`` console script run exactly the same code path.
"""

from __future__ import annotations

import multiprocessing
import sys

if __name__ == "__main__":
    # Safe no-op when unfrozen. Without it, any library that reaches for
    # multiprocessing inside a frozen build re-executes the bundle instead of
    # spawning a worker.
    multiprocessing.freeze_support()

    from costsight.desktop import main

    sys.exit(main())
