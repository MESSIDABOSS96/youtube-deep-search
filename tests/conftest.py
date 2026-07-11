"""pytest config — make the local `fixtures` package importable (SPEC §10)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
