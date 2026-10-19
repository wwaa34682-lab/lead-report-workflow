"""Config loading with ${ENV_VAR} expansion. Secrets never live in YAML."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_config(path: str | Path, strict: bool = True) -> dict:
    path = Path(path).resolve()
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_sources = [dict(x) for x in cfg.get("sources") or []]
    cfg = _expand(cfg)
    cfg["_raw_sources"] = raw_sources   # pre-expansion copy, used to detect plaintext secrets
    cfg["_base_dir"] = str(path.parent)
    if strict:
        validate(cfg)
    return cfg


def resolve_path(cfg: dict, p: str | None) -> Path | None:
    if not p:
        return None
    q = Path(p)
    return q if q.is_absolute() else (Path(cfg["_base_dir"]) / q).resolve()


def validate(cfg: dict) -> None:
    from .validate import check

    errors, _ = check(cfg)
    if errors:
        raise ValueError("配置有误 / config errors:\n  - " + "\n  - ".join(errors) +
                         "\n运行 `python run.py validate --config <file>` 查看完整检查结果")
