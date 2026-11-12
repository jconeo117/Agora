from __future__ import annotations

import sys
from pathlib import Path

# Asegurar que las pruebas usan el código de `src/` de este árbol de trabajo,
# incluso cuando `.venv` esté compartido con la rama principal u otros worktrees.
_SRC = str(Path(__file__).resolve().parents[1] / "src")
if sys.path[0] != _SRC:
    sys.path.insert(0, _SRC)
