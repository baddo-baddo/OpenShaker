"""Windowless entry point for OpenShaker.

OpenShaker.exe is built from this file (installer/OpenShaker.spec). A copy run from source starts the
same way, with no console window:

    pythonw openshaker/app.pyw [--hidden] [--no-start] [--no-tray]
"""
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Run as a script, Python puts this folder first on sys.path; the folder holding the package belongs there.
    here = Path(__file__).resolve().parent
    sys.path = [p for p in sys.path if Path(p or ".").resolve() != here]
    sys.path.insert(0, str(here.parent))

from openshaker.gui import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
