"""物品名表（M2 起步）。

设计（遵循规范 §2.1 内存只读 + §13 参考项目优先）：
- 身份（物品代码 szCode / 类型 nType / 孔位 / 索引）**从游戏内存现表 ItemTxt 读**（权威）。
- 显示名以参考 .vcb 为映射（用户确认 vcb 可作参考；vcb 的 code->name 作为标签）。
- 后续若要客户端语言名，可补 D2Lang 字符串表解析（哈希桶结构，待验证）。

全程只读：仅 read_bytes / read_uint，绝不写内存。
"""

from __future__ import annotations

import os
import re
import struct

from d2h import paths
from d2h.acquire import offsets as off
from d2h.acquire import process as proc
from d2h.acquire import structs as st

# ⚠️ 必须走 paths.DATA（= <根>/d2h/data）。曾写成 items.py 同级的 acquire/data，
#    路径错一层 => 表加载不到、所有物品名静默回退成代码（2026-09-20 修复）。
DATA_DIR = str(paths.DATA)
VCB_PATH = os.path.join(DATA_DIR, "item_codes.vcb")

_ITEM_NAME_CACHE: dict[str, str] | None = None

# 质量 / 位置 / 装备槽 的中文标签（与 offsets.ItemQuality / BodyLocation 对应）
QUALITY_NAME = {
    0: "无效", 1: "低质", 2: "普通", 3: "上等", 4: "魔法", 5: "套装",
    6: "稀有", 7: "暗金", 8: "手工", 9: "受损",
}
LOCATION_NAME = {
    0: "地面", 1: "背包/方块/仓库", 2: "腰带", 3: "身上",
}
BODY_NAME = {
    0: "无", 1: "头盔", 2: "护符", 3: "身体", 4: "右手主手", 5: "左手主手",
    6: "右手戒指", 7: "左手戒指", 8: "腰带", 9: "鞋子", 10: "手套",
    11: "右手副手", 12: "左手副手",
}


def load_item_names(path: str = VCB_PATH) -> dict[str, str]:
    """解析 .vcb（格式: `显示名, 代码: 索引`）为 {code(小写): 显示名}。结果缓存。"""
    global _ITEM_NAME_CACHE
    if _ITEM_NAME_CACHE is not None:
        return _ITEM_NAME_CACHE
    names: dict[str, str] = {}
    if not os.path.exists(path):
        # 不静默：表里明明有名字却显示成代码，多半就是这里路径错了
        print(f"[WARN] 物品名表不存在: {path} —— 物品名将回退为代码")
        _ITEM_NAME_CACHE = names
        return names
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith(";") or line.startswith("#"):
                continue
            m = re.match(r"^(.*?),\s*([^:]+?)\s*:\s*(\d+)\s*$", line)
            if m:
                name = m.group(1).strip()
                code = m.group(2).strip().lower()
                if code:
                    names[code] = name
    _ITEM_NAME_CACHE = names
    return names


def code_to_name(code: str) -> str:
    if not code:
        return ""
    return load_item_names().get(code.lower(), "")


class ItemTextTable:
    """游戏内存中的 ItemTxt 现表（1.13c）。

    表基址由 D2COMMON 的 GetItemTxt 函数体内 `cmp eax,[count全局]` 与
    `mov ecx,[base全局]` 两条指令的 imm32 提取（加载时已重定位，直接可用）。
    每条记录 0x1A8 字节：+0x80 起 4 字节为物品代码，+0xF4 WORD 为 wLocaleTxtNo，
    +0x11E BYTE 为 nType，+0x138 BYTE 为 nSocket。
    """

    REC = 0x1A8

    def __init__(self, handle: int, bases: dict[str, int]):
        self.handle = handle
        self.bases = bases
        self.ptr: int | None = None
        self.count: int = 0
        self._locate()

    def _locate(self) -> None:
        base = self.bases.get("D2COMMON")
        if not base:
            return
        gi_default = 0x6FDC19A0
        gi_addr = base + (gi_default - off.DLLBASE["D2COMMON"])
        code = proc.read_bytes(self.handle, gi_addr, 96)
        if not code:
            return
        cnt_global = base_global = None
        i = 0
        while i < len(code) - 5:
            if code[i : i + 2] == b"\x3b\x05":          # cmp eax,[imm32] -> count
                cnt_global = struct.unpack_from("<I", code, i + 2)[0]
            elif code[i : i + 2] == b"\x8b\x0d":        # mov ecx,[imm32] -> base
                base_global = struct.unpack_from("<I", code, i + 2)[0]
            i += 1
        if cnt_global:
            self.count = proc.read_uint(self.handle, cnt_global, 4) or 0
        if base_global:
            self.ptr = proc.read_uint(self.handle, base_global, 4)

    def read(self, idx: int) -> dict | None:
        if not self.ptr or idx < 0 or idx >= self.count:
            return None
        buf = proc.read_bytes(self.handle, self.ptr + idx * self.REC, self.REC)
        if not buf or len(buf) < 0x140:
            return None
        code = bytes(buf[0x80:0x84]).split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
        locale = struct.unpack_from("<H", buf, 0xF4)[0]
        ntype = buf[0x11E]
        sock = buf[0x138]
        return {"code": code, "locale": locale, "type": ntype, "socket": sock}


def describe_inventory(handle: int, bases: dict[str, int], player_unit: st.UnitAny) -> list[dict]:
    """枚举某玩家单位的全部物品，并为每件附加 代码 / 显示名 / 类型名。"""
    from d2h.acquire import game as g

    raw = g.enumerate_inventory(handle, player_unit)
    table = ItemTextTable(handle, bases)
    out: list[dict] = []
    for it in raw:
        rec = table.read(it["type"]) if table.ptr else None
        code = rec["code"] if rec else ""
        name = code_to_name(code) if code else ""
        d = dict(it)
        d["code"] = code
        d["name"] = name or code or f"type{it['type']}"
        d["type_name"] = QUALITY_NAME.get(it["quality"], str(it["quality"]))
        out.append(d)
    return out


def named_inventory(handle: int, bases: dict[str, int]) -> list[dict]:
    """定位本地玩家单位并枚举其带名物品。找不到玩家单位返回空列表。"""
    pu_ptr = off.read_ptr(handle, bases, "D2CLIENT", "PlayerUnit")
    if not pu_ptr:
        return []
    ua = proc.read_struct(handle, pu_ptr, st.UnitAny)
    if not ua:
        return []
    return describe_inventory(handle, bases, ua)


def render_markdown(items: list[dict], meta: dict) -> str:
    """把物品清单渲染成 Markdown。"""
    L: list[str] = []
    L.append("# 当前游戏物品清单")
    L.append("")
    L.append(f"- 生成时间: {meta.get('generated_at', '')}")
    L.append(f"- 角色: {meta.get('char_name', '?')}  （{meta.get('class_name', '?')}）")
    L.append(f"- 游戏: {meta.get('game_name', '?')}  | Realm: {meta.get('realm', '?')}")
    L.append(f"- 状态码: {meta.get('status', '?')}（{meta.get('status_desc', '')}）")
    L.append(f"- 物品总数: {len(items)}")
    L.append("")

    # 已装备（body > 0）
    equipped = [x for x in items if x.get("body", 0) and x.get("body", 0) != 255]
    carried = [x for x in items if not (x.get("body", 0) and x.get("body", 0) != 255)]
    for title, group in (("## 已装备", equipped), ("## 背包 / 地面 / 其他", carried)):
        L.append(title)
        L.append("")
        if not group:
            L.append("_（无）_")
            L.append("")
            continue
        L.append("| # | 名称 | 代码 | 质量 | 等级 | 孔 | 位置 |")
        L.append("| ---: | --- | --- | --- | ---: | ---: | --- |")
        for i, x in enumerate(group, 1):
            slot = BODY_NAME.get(x.get("body", 0), str(x.get("body", 0))) if x.get("body", 0) else LOCATION_NAME.get(x.get("location", 0), str(x.get("location", 0)))
            L.append(
                f"| {i} | {x.get('name','')} | {x.get('code','')} | "
                f"{QUALITY_NAME.get(x.get('quality',0), x.get('quality',0))} | "
                f"{x.get('ilvl',0)} | {x.get('socket',0) if x.get('socket') else '-'} | {slot} |"
            )
        L.append("")
    return "\n".join(L)
