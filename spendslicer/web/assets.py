"""Locate the prebuilt React bundle across the three ways SpendSlicer runs.

The dashboard is a static Vite build that the FastAPI app serves at /app.
Where those files live depends on how SpendSlicer was started:

1. **Frozen desktop build** (PyInstaller). Everything is unpacked into a
   temporary directory that PyInstaller exposes as ``sys._MEIPASS``; the
   bundle is collected there under ``spendslicer/web/static``.
2. **Installed wheel** (``pip install spendslicer``). The bundle ships inside
   the package as declared by ``[tool.setuptools.package-data]``, so it sits
   next to this module at ``spendslicer/web/static``.
3. **Source checkout** (``./run.sh``). Same location — Vite is configured to
   build straight into ``spendslicer/web/static`` rather than ``frontend/dist``,
   so there is exactly one served path in every mode.

Case 3 previously resolved the bundle as ``Path(__file__).parents[3] /
"frontend" / "dist"``, i.e. relative to the *repo root*. That works only in a
git checkout: an installed wheel resolved it to somewhere inside
site-packages and served a 404, and a frozen build broke outright. Hence the
single static location plus this resolver.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_STATIC = Path(__file__).resolve().parent / "static"


def _frozen_static() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    return Path(base) / "spendslicer" / "web" / "static"


def frontend_dist() -> Path | None:
    """Directory holding ``index.html`` and ``assets/``, or None if unbuilt."""
    for candidate in (_frozen_static(), _PACKAGE_STATIC):
        if candidate and (candidate / "index.html").is_file():
            return candidate
    return None


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
