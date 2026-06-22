"""Make the repo-root packages (``shared``, ``critcom_agent``) importable.

``critcom`` is installed from ``src/`` via ``pip install -e .``, but the A2A
glue lives in top-level ``shared``/``critcom_agent`` packages that aren't part
of the installed distribution. Prepend the repo root so ``import shared`` works
under a bare ``pytest`` invocation, matching the container's PYTHONPATH.
"""

from __future__ import annotations

import pathlib
import sys

_REPO_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
