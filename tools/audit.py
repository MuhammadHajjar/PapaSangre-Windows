"""Run the content audit from a source checkout.

The audit itself lives in ``papasangre/assets/audit.py`` so the standalone
``Check game content.exe`` and this developer entry point share one
implementation.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.assets.audit import run          # noqa: E402

if __name__ == '__main__':
    run()
