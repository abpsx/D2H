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


def is_in_game(handle: int, bases: dict[str, int]) -> bool:
    """是否在游戏中：以 D2CLIENT.InGame 字节（1=在游戏）为权威信号。"""
    v = off.read_byte(handle, bases, "D2CLIENT", "InGame")
    return v == 1


def game_mode(handle: int, bases: dict[str, int]) -> int | None:
    """读取 GameInfo+0x1EB 的 WORD —— 在线时实测约 3936（3xxx 区间），
    可作为「游戏状态码」参考（2xxx/3xxx 大致区分在/不在游戏）。"""
    gi_ptr = off.read_ptr(handle, bases, "D2CLIENT", "GameInfo")
    if not gi_ptr:
        return None
    return proc.read_uint(handle, gi_ptr + 0x1EB, 2)


def read_game_state(handle: int, bases: dict[str, int]) -> int | None:
    """读取游戏状态码: *( *( Fog.dll + 0x4AFE0 ) + 0x08 )。

    多级指针，必须逐层解引用（Fog 基址取进程真实基址，抗重定位）。
    实测（战网登录界面）= 11；语义见 offsets.STATE_*：
      11    = 登录界面 / 不在游戏
      2xxx  = 战网(BN) 游戏内
      3xxx  = 单机游戏内
    """
    fog = bases.get(off.STATE_CHAIN["module"])
    if not fog:
        return None
    p = proc.read_uint(handle, fog + off.STATE_CHAIN["offset"], 4)
    if not p:
        return None
    return proc.read_uint(handle, p + off.STATE_CHAIN["final"], 4)


def classify_state(code: int | None) -> tuple[bool, str]:
    """把状态码归类为 (是否在游戏, 中文说明)。"""
    if code is None:
        return False, "状态码不可读"
    if code is not None and code <= off.STATE_LOBBY_MAX:
        name = off.STATE_MEANING.get(code)
        tail = f"（不在游戏，state={code}）"
        return False, (name + tail) if name else ("登录/大厅界面" + tail)
    if off.STATE_IN_BN_GAME[0] <= code <= off.STATE_IN_BN_GAME[1]:
        return True, "战网(BN)游戏内"
    if off.STATE_IN_SP_GAME[0] <= code <= off.STATE_IN_SP_GAME[1]:
        return True, "单机游戏内"
    return False, f"未知状态码 {code}"


def in_game_status(handle: int, bases: dict[str, int]) -> dict:
    """返回 {state_code, in_game, in_game_byte, game_mode, status, status_desc}。

    判定优先级：Fog 状态码（read_game_state）> D2CLIENT.InGame 字节（兜底）。
    工具状态码 status（供脚本/日志判定）：
      2000 = 未在/不在游戏
      2100 = 在游戏但玩家单位不可读
      3000 = 在游戏中且玩家单位可读（物品清单可生成）
    """
    code = read_game_state(handle, bases)
    ing, desc = classify_state(code)
    if code is None:  # 状态码不可读时退回 InGame 字节
        ing = is_in_game(handle, bases)
        desc = "不在游戏（in_game=0）" if not ing else "在游戏中(in_game=1)"
    gm = game_mode(handle, bases)
    if not ing:
        return {
            "state_code": code, "in_game": False, "in_game_byte": is_in_game(handle, bases),
            "game_mode": gm, "status": 2000, "status_desc": desc,
        }
    pu_ptr = off.read_ptr(handle, bases, "D2CLIENT", "PlayerUnit")
    if not pu_ptr:
        return {
            "state_code": code, "in_game": True, "in_game_byte": is_in_game(handle, bases),
            "game_mode": gm, "status": 2100, "status_desc": desc + "，玩家单位不可读",
        }
    return {
        "state_code": code, "in_game": True, "in_game_byte": is_in_game(handle, bases),
        "game_mode": gm, "status": 3000, "status_desc": desc,
    }


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
