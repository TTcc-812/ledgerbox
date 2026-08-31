from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path.cwd()


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or ROOT / "config.yaml"
    example = Path(__file__).resolve().parents[2] / "config.example.yaml"
    if not cfg_path.exists():
        if example.exists():
            return yaml.safe_load(example.read_text(encoding="utf-8")) or {}
        return {}
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.yaml 格式无效")
    return data
