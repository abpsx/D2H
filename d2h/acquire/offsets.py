"""1.13c 偏移表（占位，待 M1 校准）。

对应参考 d2ptrs.h / d2structs.h。运行时以快照为基准校准，不盲目硬编码。
当前仅支持 1.13c（见规范 §2.4）。
"""

from __future__ import annotations

TARGET_VERSION = "1.13c"

# 待 M1 实测填写：GameData 等指针/偏移。
# 示例结构（不要照抄，需以快照校准）：
# OFFSETS_113C = {
#     "GameData": 0x...,   # game.exe 内 GameData 指针地址（或偏移路径）
# }
OFFSETS_113C: dict = {}


def get_offsets(version: str = TARGET_VERSION) -> dict:
    """返回指定版本的偏移表；当前仅 1.13c。"""
    if version != TARGET_VERSION:
        raise ValueError(f"不支持的版本: {version}（当前仅支持 {TARGET_VERSION}）")
    return OFFSETS_113C
