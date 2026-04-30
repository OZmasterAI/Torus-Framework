# Re-export from torus-skills/trs/mapper.py — canonical code lives there.
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.join(_os.path.expanduser("~"), ".claude", "torus-skills"))
from trs.mapper import *  # noqa: F401,F403,E402
from trs.mapper import SkillMapper, SkillMetadata, SkillHealth  # noqa: E402
