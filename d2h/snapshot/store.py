"""快照层 - 采集与存储（见规范 §9）。

快照目录结构：
  snapshots/<name>/
    meta.json        # 元数据（版本/时间/pid/模块基址与大小/区域数）
    regions.json     # [[base, size], ...] 可读已提交区域清单
    game_module.bin  # game.exe 镜像转储（可选）

全程只读：仅用 acquire.process 读取，绝不写游戏内存。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from d2h.acquire import process as proc

SNAP_ROOT = Path(__file__).resolve().parent.parent.parent / "snapshots"


def capture(handle: int, pid: int, name: str | None = None,
            module_name: str = "game.exe", label: str | None = None,
            state_code: int | None = None,
            module_bases: dict | None = None) -> tuple[str, dict]:
    """对只读句柄采集一次快照；返回 (快照名, 元数据)。

    module_name: 要转储的主模块（默认 game.exe；用 loader 时为 D2loader.exe）。
    label:      人工标记（如 "11战网登录界面"）。
    state_code: 采集瞬间的游戏状态码（Fog 多级指针读出），自动写入 meta 便于对照。
    module_bases: 各模块真实基址，一并存档（离线解析时要用，防止重定位导致偏移错）。
    """
    SNAP_ROOT.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    snap_name = name or f"snap_{ts}"
    d = SNAP_ROOT / snap_name
    d.mkdir(parents=True, exist_ok=True)

    meta: dict = {
        "tool": "D2H",
        "target_version": "1.13c",
        "captured_at": ts,
        "pid": pid,
        "read_only": True,
        "target_module": module_name,
        "module_base": None,
        "module_size": None,
        "module_dumped": False,
        "module_bytes": 0,
        "region_count": 0,
        "label": label,
        "state_code": state_code,
        "module_bases": {str(k): int(v) for k, v in (module_bases or {}).items()},
    }

    mod = proc.get_module_info(handle, module_name)
    if mod:
        base, size = mod
        meta["module_base"] = base
        meta["module_size"] = size
        data = proc.read_bytes(handle, base, size)
        if data is not None:
            (d / f"{module_name}_module.bin").write_bytes(data)
            meta["module_dumped"] = True
            meta["module_bytes"] = len(data)

    regions = proc.enum_regions(handle)
    meta["region_count"] = len(regions)
    (d / "regions.json").write_text(
        json.dumps([[int(a), int(s)] for a, s in regions], separators=(",", ":")),
        encoding="utf-8",
    )

    (d / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return snap_name, meta


def list_snapshots() -> list[dict]:
    """列出本地所有快照（含 _name 字段）。"""
    if not SNAP_ROOT.exists():
        return []
    out: list[dict] = []
    for d in sorted(SNAP_ROOT.iterdir()):
        meta_path = d / "meta.json"
        if d.is_dir() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            meta["_name"] = d.name
            out.append(meta)
    return out


def load(name: str) -> dict | None:
    """读取某快照的元数据；不存在返回 None。"""
    p = SNAP_ROOT / name / "meta.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
