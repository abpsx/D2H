"""采集层 - 游戏状态只读解析（M1 起步）。

把 offsets（1.13c 偏移）+ structs（结构体）拼装成可读取的游戏状态：
当前游戏/小地图开关、GameInfo（角色名/游戏名/ realm/模式）、本地玩家
（名字/位置/背包物品枚举）。

全程只读：仅用 read_bytes / read_struct，绝不写内存。
物品名称解码（ItemTxt / .vcb）留待 M2。
"""

from __future__ import annotations

from d2h.acquire import offsets as off
from d2h.acquire import process as proc
from d2h.acquire import structs as st


def read_state(handle: int, bases: dict[str, int]) -> dict:
    """读取一份游戏状态快照（dict）。读取失败的项以 None 占位。"""
    result: dict = {}

    # 全局标志
    result["in_game"] = off.read_byte(handle, bases, "D2CLIENT", "InGame")
    result["automap_on"] = off.read_byte(handle, bases, "D2CLIENT", "AutomapOn")

    # GameInfo -> GameStructInfo
    gi_ptr = off.read_ptr(handle, bases, "D2CLIENT", "GameInfo")
    if gi_ptr:
        gi = proc.read_struct(handle, gi_ptr, st.GameStructInfo)
        if gi:
            result["char_name"] = _cstr(gi.szCharName)
            result["game_name"] = _cstr(gi.szGameName)
            result["realm"] = _cstr(gi.szRealmName)
            result["account"] = _cstr(gi.szAccountName)
            result["game_mode"] = gi.nGameMode

    # PlayerUnit -> UnitAny
    pu_ptr = off.read_ptr(handle, bases, "D2CLIENT", "PlayerUnit")
    if pu_ptr:
        ua = proc.read_struct(handle, pu_ptr, st.UnitAny)
        if ua:
            result["player_unit_id"] = ua.dwUnitId
            result["player_type"] = ua.dwUnitType
            result["player_flags1"] = ua.dwFlags1
            # 玩家名（PlayerData）
            if ua.pUnitData:
                pd = proc.read_struct(handle, ua.pUnitData, st.PlayerData)
                if pd:
                    result["player_name"] = _cstr(pd.szName)
            # 坐标（DynamicPath）
            if ua.pPath:
                dp = proc.read_struct(handle, ua.pPath, st.DynamicPath)
                if dp:
                    result["pos_x"] = dp.wPosX
                    result["pos_y"] = dp.wPosY
            # 背包物品枚举
            items = enumerate_inventory(handle, ua)
            result["inventory_count"] = len(items)
            result["inventory_sample"] = items[:8]

    return result


def enumerate_inventory(handle: int, unit: st.UnitAny) -> list[dict]:
    """枚举某单位持有的全部物品（M1 起步版）。

    覆盖两类：
    1) 散落物品（背包/方块/仓库/腰带）：从 UnitInventory.pFirstItem 沿 pListNext 走。
    2) 已装备物品：从 UnitInventory.pInvInfo 的指针数组（dwInvInfoCount 项）逐个解引用。

    按 dwUnitType==ITEM 过滤，坏指针/容器节点/空槽由 read_struct 返回 None 或类型不符剔除。
    上限 256 防失控，环路用 seen 去重。M2 将接入 ItemTxt/.vcb 把 type 解码成物品名。
    """
    import struct as _struct

    items: list[dict] = []
    if not unit.pInventory:
        return items
    inv = proc.read_struct(handle, unit.pInventory, st.UnitInventory)
    if not inv:
        return items

    seen: set[int] = set()

    # 1) 散落物品
    addr = inv.pFirstItem
    guard = 0
    while addr and guard < 256 and addr not in seen:
        seen.add(addr)
        ua = proc.read_struct(handle, addr, st.UnitAny)
        if not ua:
            break
        if ua.dwUnitType == off.UnitNo.ITEM and ua.pUnitData:
            idata = proc.read_struct(handle, ua.pUnitData, st.ItemData)
            if idata:
                items.append(_item_record(ua, idata))
        if not ua.pListNext:
            break
        addr = ua.pListNext
        guard += 1

    # 2) 已装备物品（pInvInfo 指针数组）
    if inv.pInvInfo and inv.dwInvInfoCount > 0:
        arr = proc.read_bytes(handle, inv.pInvInfo, inv.dwInvInfoCount * 4)
        if arr and len(arr) >= inv.dwInvInfoCount * 4:
            ptrs = _struct.unpack("<%dI" % inv.dwInvInfoCount, arr)
            for p in ptrs:
                if not p or p < 0x10000 or p in seen:
                    continue
                ua = proc.read_struct(handle, p, st.UnitAny)
                if not ua:
                    continue
                if ua.dwUnitType == off.UnitNo.ITEM and ua.pUnitData:
                    idata = proc.read_struct(handle, ua.pUnitData, st.ItemData)
                    if idata:
                        items.append(_item_record(ua, idata))

    return items


def _item_record(ua: st.UnitAny, idata: st.ItemData) -> dict:
    """把一件物品压成可读记录（M2 会增加物品名解码）。"""
    return {
        "type": ua.dwTxtFileNo,
        "quality": idata.dwQuality,
        "ilvl": idata.dwItemLevel,
        "flags": idata.dwItemFlags,
        "location": idata.nLocation,
        "body": idata.nBodyLocation,
    }


def _cstr(buf) -> str:
    """c_char 数组 -> ascii 字符串（去尾零）。"""
    if isinstance(buf, (bytes, bytearray)):
        return buf.split(b"\x00", 1)[0].decode("ascii", "ignore")
    # ctypes c_char_Array
    try:
        raw = bytes(buf)
        return raw.split(b"\x00", 1)[0].decode("ascii", "ignore")
    except Exception:
        return ""
