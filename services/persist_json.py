"""JSON 文件持久化：让 MVP 内存 store 在服务重启后数据不丢。

- save(): 原子写（先写 .tmp 再 replace），dataclass/Enum 自动序列化
- load(): 读取为 dict；文件不存在或损坏时返回 {}

数据目录：KARMA_MVP_DATA_DIR 环境变量，缺省 <repo>/mvp_data/
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from threading import Lock

_LOCK = Lock()
_DIR = Path(os.getenv("KARMA_MVP_DATA_DIR") or (Path(__file__).resolve().parent.parent / "mvp_data"))


def _default(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "value") and hasattr(obj, "name"):  # Enum
        return obj.value
    raise TypeError(f"not JSON serializable: {type(obj)!r}")


def save(name: str, payload: dict) -> None:
    try:
        with _LOCK:
            _DIR.mkdir(parents=True, exist_ok=True)
            tmp = _DIR / f".{name}.tmp"
            tmp.write_text(json.dumps(payload, ensure_ascii=False, default=_default), encoding="utf-8")
            os.replace(tmp, _DIR / f"{name}.json")
    except Exception:  # 持久化失败不能阻断业务
        import logging

        logging.getLogger("karma.persist").exception("persist_save_failed name=%s", name)


def load(name: str) -> dict:
    p = _DIR / f"{name}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        import logging

        logging.getLogger("karma.persist").exception("persist_load_failed name=%s", name)
        return {}


def delete(name: str) -> None:
    p = _DIR / f"{name}.json"
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass
