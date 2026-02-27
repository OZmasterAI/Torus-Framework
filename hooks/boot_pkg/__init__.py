"""boot_pkg — decomposed SessionStart boot sequence."""
import os
import sys

# Ensure hooks dir is on sys.path for shared imports
_HOOKS_DIR = os.path.dirname(os.path.dirname(__file__))
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)
