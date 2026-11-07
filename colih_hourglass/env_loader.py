from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> int:
    """Carrega pares KEY=value de um arquivo no os.environ (não sobrescreve chaves já definidas)."""
    text = path.read_text(encoding="utf-8")
    loaded = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded
