#!/usr/bin/env python3
"""D2H 路径唯一权威（见规范 §16 临时文件约定）。

硬规则（2026-09-19 用户拍板）：
    **一切临时文件/中间产物一律落在项目内 <项目根>/temp/ 目录，
    禁止写入 C 盘 %TEMP%、%TMP% 或任何系统/用户目录。**

原因：临时文件留在项目内才能被 .gitignore 收纳、随项目一起清理，
不污染系统盘，且不会因为换机器/换用户而散落各处找不到。

用法::

    from d2h import paths
    p = paths.tmp_path("probe_out.txt")   # <ROOT>/temp/probe_out.txt
    paths.write_tmp("out.txt", "hello")   # 直接写文本并返回路径
    paths.clean_temp()                    # 清空 temp/（保留 .gitkeep）
"""

from __future__ import annotations

from pathlib import Path

# ---- 项目内固定目录 ----
ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
SNAPSHOTS = ROOT / "snapshots"
DATA = ROOT / "d2h" / "data"

#: 唯一的临时文件目录（替代 %TEMP%）
TEMP = ROOT / "temp"

# 禁止再使用的系统临时目录（仅作文档/自检用途，代码不得写入）
_SYSTEM_TEMPS = ("%TEMP%", "%TMP%", "/tmp", "/var/tmp")


def ensure_temp() -> Path:
    """确保 temp/ 存在并返回其路径。"""
    TEMP.mkdir(parents=True, exist_ok=True)
    return TEMP


def tmp_path(name: str) -> Path:
    """返回 temp/<name>。若 name 含子目录会自动创建。

    注意：name 必须是相对名；传入绝对路径会抛错，防止误写系统目录。
    """
    p = Path(name)
    if p.is_absolute():
        raise ValueError(
            f"临时文件名必须是相对路径，收到绝对路径: {name}\n"
            f"临时文件只允许落在 {TEMP}"
        )
    if ".." in p.parts:
        raise ValueError(f"临时文件名不允许包含 '..': {name}")
    ensure_temp()
    full = TEMP / p
    if full.parent != TEMP:
        full.parent.mkdir(parents=True, exist_ok=True)
    return full


def write_tmp(name: str, content: str, encoding: str = "utf-8") -> Path:
    """把文本写入 temp/<name>，返回路径。"""
    p = tmp_path(name)
    if p.parent != TEMP:
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)
    return p


def clean_temp(keep_placeholder: bool = True) -> tuple[int, int]:
    """清空 temp/。返回 (删除数, 失败数)。保留 .gitkeep 占位。"""
    ensure_temp()
    deleted = failed = 0
    for item in TEMP.iterdir():
        if keep_placeholder and item.name == ".gitkeep":
            continue
        try:
            if item.is_dir():
                import shutil

                shutil.rmtree(item)
            else:
                item.unlink()
            deleted += 1
        except OSError:
            failed += 1
    return deleted, failed


def temp_info() -> dict:
    """返回 temp/ 的概况，供 cli 展示。"""
    ensure_temp()
    files = [p for p in TEMP.iterdir() if p.is_file()]
    dirs = [p for p in TEMP.iterdir() if p.is_dir()]
    size = sum(p.stat().st_size for p in files if p.exists())
    return {
        "temp_dir": str(TEMP),
        "files": len(files),
        "dirs": len(dirs),
        "bytes": size,
        "sample": [p.name for p in sorted(files, key=lambda x: x.name)[:10]],
    }
