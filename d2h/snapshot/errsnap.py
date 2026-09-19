"""错误快照 —— 命令报错时自动抓一份"现场"，与报错信息绑定，便于离线对照校验。

目录：temp/err_<时间戳>_<命令>/
  error.txt        命令行 / 时间 / 异常类型与消息 / 完整 traceback
  context.json     进程与模块基址、状态码、UI 面板、玩家单位、悬停单位读数
  D2CLIENT.bin     D2CLIENT 模块转储（离线按偏移重读用，约 1~2MB）

设计要点：
  1. 只在**报错**时触发，正常路径零开销；
  2. 内部任何一步失败都不再抛出（不能让"抓快照"掩盖或替代原始异常）；
  3. 全部走只读接口（PROCESS_VM_READ），不写游戏内存；
  4. 解耦/调试完成后 `cli.py err --clean` 一键删除，不留垃圾。
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

from d2h import paths

ERR_PREFIX = "err_"


def err_root() -> Path:
    """错误快照根目录（项目 temp/ 下，见规范 §16）。"""
    d = paths.TEMP
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(fn, *a, **kw):
    """包一层：抓上下文时任何读取失败都退化成 None，绝不二次抛异常。"""
    try:
        return fn(*a, **kw)
    except Exception:  # noqa: BLE001
        return None


def capture_error(exc: BaseException, argv, target: str = "loader",
                  note: str = "") -> Path | None:
    """抓一份错误现场。返回目录路径；彻底失败返回 None。"""
    from d2h.acquire import game as gm
    from d2h.acquire import offsets as off
    from d2h.acquire import process as proc

    argv = list(argv or [])
    cmd = argv[0] if argv else "?"
    ts = time.strftime("%Y%m%d_%H%M%S")
    d = err_root() / f"{ERR_PREFIX}{ts}_{cmd}"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        return None

    # 1) 报错信息
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    (d / "error.txt").write_text(
        f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"命令: d2h {' '.join(argv)}\n"
        f"目标: {target}\n"
        f"备注: {note}\n"
        f"异常: {type(exc).__name__}: {exc}\n\n"
        f"{tb}",
        encoding="utf-8",
    )

    # 2) 现场上下文
    ctx: dict = {
        "captured_at": ts,
        "argv": argv,
        "target": target,
        "note": note,
        "error": f"{type(exc).__name__}: {exc}",
    }
    exe, pid = _safe(proc.find_target_pid, target) or (target, None)
    ctx["exe"] = exe
    ctx["pid"] = pid
    handle = None
    if pid:
        handle = _safe(proc.open_readonly, pid)
    if handle:
        try:
            bases = _safe(off.collect_module_bases, handle) or {}
            ctx["module_bases"] = {k: hex(v) for k, v in bases.items()}
            code = _safe(gm.read_game_state, handle, bases)
            ctx["state_code"] = code
            if code is not None:
                ing, desc = gm.classify_state(code)
                ctx["state_desc"] = desc
            ui = _safe(gm.read_ui_panels, handle, bases) or {}
            ctx["ui_open"] = ui.get("open", [])
            ctx["ui_base"] = hex(ui["base"]) if ui.get("base") else None
            ctx["ui_side"] = ui.get("side")
            ctx["ui_stash"] = ui.get("stash")
            hov = _safe(gm.read_hover_unit, handle, bases) or {}
            ctx["hover"] = {k: (hex(v) if isinstance(v, int) and v else v)
                            for k, v in hov.items()}
            # D2CLIENT 模块转储：离线可按偏移重读，验证"当时到底读到了什么"
            mod = _safe(proc.get_module_info, handle, "D2CLIENT.dll")
            if mod:
                base, size = mod
                ctx["d2client"] = {"base": hex(base), "size": size}
                data = _safe(proc.read_bytes, handle, base, size)
                if data:
                    (d / "D2CLIENT.bin").write_bytes(data)
                    ctx["d2client"]["dumped"] = len(data)
        finally:
            _safe(proc.close, handle)

    (d / "context.json").write_text(
        json.dumps(ctx, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return d


def list_errors() -> list[dict]:
    """列出所有错误快照（新的在前）。"""
    root = err_root()
    out: list[dict] = []
    for p in sorted(root.glob(ERR_PREFIX + "*"), reverse=True):
        if not p.is_dir():
            continue
        meta = {}
        cj = p / "context.json"
        if cj.exists():
            try:
                meta = json.loads(cj.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                meta = {}
        out.append({
            "name": p.name,
            "path": str(p),
            "argv": meta.get("argv", []),
            "at": meta.get("captured_at", ""),
            "error": meta.get("error", ""),
            "pid": meta.get("pid"),
            "state_code": meta.get("state_code"),
        })
    return out


def show_error(name: str) -> str:
    """打印某份错误快照的要点（error.txt + context.json 摘要）。"""
    d = err_root() / name
    if not d.is_dir():
        return f"没有这份错误快照: {name}"
    lines = [f"[目录] {d}"]
    ef = d / "error.txt"
    if ef.exists():
        lines.append("--- error.txt ---")
        lines.append(ef.read_text(encoding="utf-8").rstrip())
    cj = d / "context.json"
    if cj.exists():
        lines.append("--- context.json ---")
        lines.append(cj.read_text(encoding="utf-8").rstrip())
    return "\n".join(lines)


def clean_errors() -> int:
    """删除全部错误快照，返回删除数量。"""
    import shutil

    n = 0
    for p in err_root().glob(ERR_PREFIX + "*"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    return n
