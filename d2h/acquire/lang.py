"""D2Lang 字符串表（只读复刻 D2LANG.GetLocaleText，见规范 §15.1 E）。

背景（2026-09-20）：
    hackmap 拿物品显示名的方式是 `D2GetItemTxt(txtFileNo)->wLocaleTxtNo` 再
    `D2GetLocaleText(no)`（d2ptrs.h:230，D2LANG + 0x9450）。那是**函数调用**，
    我们不能调用（只读约束），于是**只读 dump 该函数体**把表结构扒出来自己算。

反汇编结论（1.13c，D2LANG + 0x9450）：
    cmp si, 0x4E20(20000) -> 用 D2LANG+0x10A84 表；否则
    cmp si, 0x2710(10000) -> 用 D2LANG+0x10A80 表；否则
                            用 D2LANG+0x10A64 表（基准 0）
    然后 call 0x779050 查表，该查表函数逻辑：
        count   = WORD[table + 0x02]
        slot    = WORD[table + 0x15 + (id - 基准) * 2]   ← id -> 槽位映射数组
        pStr    = DWORD[strings + slot * 4]              ← 直接就是 wchar_t*
    其中 strings = 同组另一个全局（+0x10A68 / +0x10A6C / +0x10A70）。

⚠️ 字符串**不在 D2Lang 镜像里**：它们是运行时从 .tbl 载入堆的（实测命中
0x11EFxxxx 这类堆地址）。所以只能内存查，读本地文件既不全也不准 —— 这正是
用户强调"有些内容从服务器获取，只查本地不准确"的原因。

实测：id=2039 -> "短棍【普通】"、id=10000 -> "巴特克的猛击"、id=0 -> NPC 对白。
"""

from __future__ import annotations

import re

from d2h.acquire import offsets as off
from d2h.acquire import process as proc

# (组名, 表指针偏移, 字符串数组偏移, id 基准)
LANG_GROUPS: tuple[tuple[str, int, int, int], ...] = (
    ("base(<10000)", 0x10A64, 0x10A68, 0),
    ("mid(>=10000)", 0x10A80, 0x10A6C, 10000),
    ("high(>=20000)", 0x10A84, 0x10A70, 20000),
)

_IDX_ARRAY = 0x15          # id -> slot 的 WORD 数组起点
_MAX_STR = 256             # 字符串最大读取长度（字符）

# D2 颜色控制符：'ÿc' + 一个字符（如 ÿc2 / ÿc/ / ÿc;）
_COLOR_RE = re.compile("\xffc.")


def strip_color(s: str) -> str:
    """去掉游戏内颜色控制符（ÿcX），并压缩多余空白。"""
    if not s:
        return ""
    s = _COLOR_RE.sub("", s)
    return " ".join(s.split())


def read_wstring(handle: int, addr: int, maxlen: int = _MAX_STR) -> str:
    """读 UTF-16LE 宽字符串（遇 \\x00 结束）。读不到返回空串。"""
    if not addr:
        return ""
    raw = proc.read_bytes(handle, addr, maxlen * 2)
    if not raw:
        return ""
    return raw.decode("utf-16-le", "ignore").split("\x00", 1)[0]


class LocaleText:
    """游戏字符串表。get(id) 等价于游戏里的 GetLocaleText(id)，但全程只读。"""

    def __init__(self, handle: int, bases: dict[str, int]):
        self.handle = handle
        self.groups: list[dict] = []
        self._locate(bases)

    def _locate(self, bases: dict[str, int]) -> None:
        lb = bases.get("D2LANG")
        if not lb:
            return
        for tag, t_off, s_off, delta in LANG_GROUPS:
            t = proc.read_uint(self.handle, lb + t_off, 4)
            s = proc.read_uint(self.handle, lb + s_off, 4)
            if not t or not s:
                continue
            cnt = proc.read_uint(self.handle, t + 0x02, 2) or 0
            self.groups.append({"tag": tag, "table": t, "strings": s,
                                "delta": delta, "count": cnt})

    def ready(self) -> bool:
        return bool(self.groups)

    def get(self, sid: int) -> str:
        """按字符串 id 取原文（含颜色控制符）；取不到返回空串。"""
        if not self.groups or sid is None:
            return ""
        for g in self.groups:
            idx = sid - g["delta"]
            if idx < 0 or idx >= g["count"]:
                continue
            slot = proc.read_uint(self.handle, g["table"] + _IDX_ARRAY + idx * 2, 2)
            if slot is None:
                continue
            p = proc.read_uint(self.handle, g["strings"] + slot * 4, 4)
            if not p:
                continue
            return read_wstring(self.handle, p)
        return ""

    def get_clean(self, sid: int) -> str:
        """取字符串并去掉颜色控制符（用于显示）。"""
        return strip_color(self.get(sid))
