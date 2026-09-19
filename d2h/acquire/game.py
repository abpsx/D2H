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
    if code > off.STATE_LOBBY_MAX:
        # 实测见过 4096（游戏中，UI 面板可正常读写）—— 未归类但确在游戏内
        return True, f"游戏内（未归类 {code}）"
    return False, f"未知状态码 {code}"


def read_ui_panels(handle: int, bases: dict[str, int]) -> dict:
    """读取游戏内 UI 面板标记（多级指针，只读）。

    链: p = *( D2CLIENT.dll + 0x50D00 )；标志 = *( p + off )，每项 4 字节 DWORD。

    返回 {base, panels:{名称: 值}, open:[已打开面板], side, side_desc, stash, stash_desc}。
    """
    out: dict = {
        "base": None,
        "array": None,
        "panels": {},
        "open": [],
        "side": None,
        "side_desc": "不可读",
        "stash": None,
        "stash_desc": "不可读",
    }
    base = bases.get(off.UI_PANEL_CHAIN["module"])
    if not base:
        return out
    p = proc.read_uint(handle, base + off.UI_PANEL_CHAIN["offset"], 4)
    if not p:
        return out
    out["base"] = p
    arr = p + off.UI_ARRAY_DELTA  # UIVar 数组起点（= p - 4）
    out["array"] = arr

    for o, name, side in off.UI_PANELS:
        v = proc.read_uint(handle, arr + o, 4)
        out["panels"][name] = v
        if v == 1:
            out["open"].append(f"{name}({side})" if side != "-" else name)

    sb = bases.get(off.UI_SIDE_FLAG["module"])
    if sb:
        sv = proc.read_uint(handle, sb + off.UI_SIDE_FLAG["offset"], 4)
        out["side"] = sv
        if sv is not None:
            out["side_desc"] = off.UI_SIDE_MEANING.get(sv, f"未知({sv})")

    tb = bases.get(off.UI_STASH_FLAG["module"])
    if tb:
        tv = proc.read_uint(handle, tb + off.UI_STASH_FLAG["offset"], 4)
        out["stash"] = tv
        if tv is not None:
            out["stash_desc"] = off.UI_STASH_MEANING.get(tv, ("无" if tv == 0 else f"未知({tv})"))

    return out


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


# ---- 鼠标指向的单位 ----
UNIT_TYPE_NAME: dict[int, str] = {
    0: "玩家", 1: "怪物/NPC", 2: "物件", 3: "导弹", 4: "物品", 5: "房间格子",
}


def find_unit_by_id(handle: int, bases: dict[str, int], unit_id: int,
                    unit_type: int, max_nodes: int = 128) -> int | None:
    """按 (类型, unitId) 从 unit hash 表反查 UnitAny* 地址；找不到返回 None。

    D2 1.13c 结构（只读反汇编 GetSelectedUnit = 0x6FB01A80 得出，不执行代码）：
      VARS.D2CLIENT.UnitTable = 0x6FBBA608（= D2CLIENT + 0x10A608）
      块索引 = 单位类型；每块 UNIT_TABLE_STRIDE(512) 字节 = 128 个桶
      桶索引 = unitId & 0x7F；桶内是 pListNext(+0xE8) 串成的链表
    对应指令：`mov edx,[0x6FBC964C]; shl edx,9; add edx,0x6FBBA608`
              `mov ecx,[0x6FBC9638]; and eax,0x7F`
    自检：find_unit_by_id(1, 0) 返回的正是 PlayerUnit 全局的值（角色 daaaa）。
    """
    cb = bases.get("D2CLIENT")
    base = off.VARS["D2CLIENT"]["UnitTable"] - off.DLLBASE["D2CLIENT"]
    if not cb or not unit_id or unit_type is None or unit_type > 5:
        return None
    blk = cb + base + unit_type * off.UNIT_TABLE_STRIDE
    bucket = unit_id & 0x7F
    data = proc.read_bytes(handle, blk, off.UNIT_TABLE_STRIDE)
    if not data or len(data) < (bucket + 1) * 4:
        return None
    node = int.from_bytes(data[bucket * 4:bucket * 4 + 4], "little")
    seen = 0
    while node and seen < max_nodes:
        t = proc.read_uint(handle, node + 0x00, 4)
        i = proc.read_uint(handle, node + 0x0C, 4)
        if t == unit_type and i == unit_id:
            return node
        node = proc.read_uint(handle, node + off.UNIT_NEXT_OFFSET, 4)
        seen += 1
    return None


def read_unit_pos(handle: int, p_path: int, unit_type: int | None) -> tuple[int | None, int | None]:
    """按单位类型选正确的路径结构读坐标，返回 (x, y)；读不到为 (None, None)。

    ⚠️ 路径是 union：玩家/怪物/导弹用 **DynamicPath**（WORD 坐标 @+0x02/+0x06），
    物件/物品/地块用 **StaticPath**（DWORD 坐标 @+0x0C/+0x10）。混用会得到
    65535 之类的垃圾值（布局不同，参考 d2structs.h）。
    """
    if not p_path:
        return (None, None)
    if unit_type in (0, 1, 3):          # Player / Monster / Missile
        return (proc.read_uint(handle, p_path + 0x02, 2),
                proc.read_uint(handle, p_path + 0x06, 2))
    return (proc.read_uint(handle, p_path + 0x0C, 4),   # Object / Item / Tile
            proc.read_uint(handle, p_path + 0x10, 4))


def read_hover_unit(handle: int, bases: dict[str, int]) -> dict:
    """读取鼠标当前指向的单位（只读）。返回 dict，读不到的字段为 None。

    观测点优先级：
      1) CurrentViewItem(0x11BC38) —— 直接就是 UnitAny*（hackmap: 选择显示的物品）
      2) (HoverUnitId 0x119638, HoverUnitType 0x11964C) —— 函数体真正用于查表的那组，反查 unit 表
      3) (SelectedUnitFlag 0x11C2F4, Flag2 0x11C2F8) —— 另一组（实测悬停玩家时 id=1），同样反查
    """
    cb = bases.get("D2CLIENT")
    out: dict = {"ptr": None, "source": "", "name": ""}
    if not cb:
        return out
    v = off.VARS["D2CLIENT"]

    def rd(key: str):
        return proc.read_uint(handle, cb + (v[key] - off.DLLBASE["D2CLIENT"]), 4)

    out["sel_id"] = rd("SelectedUnitFlag")
    out["sel_type"] = rd("SelectedUnitFlag2")
    out["hover_id"] = rd("HoverUnitId")
    out["hover_type"] = rd("HoverUnitType")
    out["view_item"] = rd("CurrentViewItem")

    if out["view_item"]:
        out["ptr"] = out["view_item"]
        out["source"] = "CurrentViewItem(+0x11BC38)"
    else:
        for kid, kt in (("hover_id", "hover_type"), ("sel_id", "sel_type")):
            uid, ut = out[kid], out[kt]
            if uid and ut is not None and ut <= 5:
                p = find_unit_by_id(handle, bases, uid, ut)
                if p:
                    out["ptr"] = p
                    out["source"] = f"{kid}=0x{uid:X} type={ut} → unit 表反查"
                    break

    p = out["ptr"]
    if p:
        out["unit_type"] = proc.read_uint(handle, p + 0x00, 4)
        out["txt"] = proc.read_uint(handle, p + 0x04, 4)
        out["unit_id"] = proc.read_uint(handle, p + 0x0C, 4)
        out["mode"] = proc.read_uint(handle, p + 0x10, 4)
        pp = proc.read_uint(handle, p + 0x2C, 4)
        if pp:
            out["x"], out["y"] = read_unit_pos(handle, pp, out["unit_type"])
        if out.get("unit_type") == 0:
            pd = proc.read_uint(handle, p + 0x14, 4)
            if pd:
                raw = proc.read_bytes(handle, pd, 16) or b""
                out["name"] = raw.split(b"\x00", 1)[0].decode("ascii", "ignore")
    return out
