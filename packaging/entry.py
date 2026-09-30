"""Entry point for the one-file build (PyInstaller needs a plain script, not a package __main__)."""
import sys

from aitk.cli import main

sys.exit(main())
