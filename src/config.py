
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv
from .utils import env_expand

def _walk(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _walk(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v) for v in obj]
    if isinstance(obj, str):
        return env_expand(obj)
    return obj

def load_config(path: str = "config.yaml") -> dict[str, Any]:
    load_dotenv()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config.example.yaml to config.yaml and edit it."
        )
    with p.open("r", encoding="utf-8") as f:
        return _walk(yaml.safe_load(f) or {})
