from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _resolve_path(value: str | None, fallback: Path) -> Path:
    path = Path(value).expanduser() if value else fallback
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


ROOT = _resolve_path(os.environ.get("LEDGERBOX_ROOT"), Path.cwd())


def load_config(path: Path | None = None) -> dict[str, Any]:
    env_path = os.environ.get("LEDGERBOX_CONFIG")
    cfg_path = path or _resolve_path(env_path, ROOT / "config.yaml")
    example = Path(__file__).resolve().parents[2] / "config.example.yaml"
    if not cfg_path.exists():
        if example.exists():
            return yaml.safe_load(example.read_text(encoding="utf-8")) or {}
        return {}
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.yaml 格式无效")
    return data
