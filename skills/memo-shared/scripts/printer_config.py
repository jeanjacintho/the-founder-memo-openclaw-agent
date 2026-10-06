"""printer_config.py -- config.json's printer object, read one way by every script."""
from __future__ import annotations

import json
from pathlib import Path


def read_printer(config_path):
    """The printer object; {} when the file, its JSON or the object is missing or malformed."""
    try:
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    printer = cfg.get("printer") if isinstance(cfg, dict) else None
    return printer if isinstance(printer, dict) else {}
