"""`python -m aitk` is what AI apps start; it is the same as the `aitk` command."""
import sys

from .cli import main

sys.exit(main())
