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

    ⚠️**同一指针 = 同一物品**，必须按指针去重（2026-09-20 用户判明）：
      · 双手武器同时占「右手主手」和「左手主手」两个槽 → 数组里两条相同指针；
      · 背包/仓库里占多格的物品（2×2 就有 4 格）→ 会出现 4 条相同指针。
      不去重会把一件武器显示成两把、一个 2×2 物品显示成四个。

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
                seen.add(p)          # ★ 必须登记：同一件物品会出现多次（双手武器/多格物品）
                ua = proc.read_struct(handle, p, st.UnitAny)
                if not ua:
                    continue
                if ua.dwUnitType == off.UnitNo.ITEM and ua.pUnitData:
                    idata = proc.read_struct(handle, ua.pUnitData, st.ItemData)
                    if idata:
                        items.append(_item_record(ua, idata))

    return items


# ---- 地面物品枚举（房间邻近表，不依赖悬停）----
# 1.13c 实机验证过的偏移（2026-09-20）；落地成本函数后，本注释即权威，另见规范 §15.1。
ROOM1_PTR_OFF = 0x00        # DrlgRoom1** paRoomsNear —— ★二级指针
ROOMS_NEAR_COUNT_OFF = 0x24  # dwRoomsNear（hackmap d2structs.h 注 //+04 是笔误，+0x04 处恒 0）
ROOM_UNIT_FIRST_OFF = 0x74   # pUnitFirst（= +0x28 + 19*4，头文件未标）
PATH_ROOM1_OFF = 0x1C        # DynamicPath -> pRoom1  ★入口
ITEM_LOCATION_OFF = 0x69     # ItemData.nLocation（0=地面 / 1=方块·仓库·背包 / 2=腰带 / 3=身上）


def enumerate_ground_items(handle: int, bases: dict[str, int],
                           player_unit: int | None = None,
                           max_rooms: int = 64, max_units: int = 4096,
                           namer=None) -> dict:
    """枚举**地面上（未拾取）**的物品 —— 走房间邻近表，不依赖鼠标悬停。

    链（1.13c）：
      pPlayer     = *(D2CLIENT PlayerUnit)
      pPath       = *(pPlayer + 0x2C)              DynamicPath
      pRoom1      = *(pPath   + 0x1C)              ★入口
      paRoomsNear = *(pRoom1  + 0x00)              ★二级指针：房间 i = u32(pa + i*4)
      dwRoomsNear = *(pRoom1  + 0x24)
      pUnitFirst  = *(room    + 0x74)              链表 *(p + 0xE8) = UnitAny.pListNext
      判定：dwUnitType == 4(ITEM) && u8(*(p+0x14) + 0x69) == 0   ← ItemData.nLocation

    ⚠️ 两个坑（都踩过，改这里前先看一眼）：
      ① 入口是 **pPath + 0x1C** 不是 pPlayer + 0x1C —— 后者是 pDrlgAct，其 +0x24 恒 0
         ⇒ 静默返回「房间 0 个」**且不报错**，极难发现。
      ② **paRoomsNear 是二级指针**：必须 `u32(u32(pRoom1+0x00) + i*4)`；
         直接 `u32(pRoom1 + i*4)` 读到的是指针本身（i=4 恰命中 pRoom2 → 假房间，
         表现为「链长 1、type 0」）。
      ③ 坐标必须走 `read_unit_pos()`（物品是 StaticPath，手写 WORD 偏移会得到 65535）。

    返回 dict（失败也返回完整结构，字段打 0 / 空列表，由调用方照 §12 完整打印）：
      {"ok", "reason", "player", "room1", "rooms", "units", "items"}
      items 每项 = _item_record() 的字段 + ptr / unit_id / x / y / name。
    """
    out: dict = {"ok": False, "reason": "", "player": None, "room1": None,
                 "rooms": 0, "units": 0, "items": []}
    p = player_unit or off.read_ptr(handle, bases, "D2CLIENT", "PlayerUnit")
    if not p:
        out["reason"] = "PlayerUnit 读不到（不在游戏里？）"
        return out
    out["player"] = p
    p_path = proc.read_uint(handle, p + 0x2C, 4)
    if not p_path:
        out["reason"] = "pPath 读不到（+0x2C）"
        return out
    room1 = proc.read_uint(handle, p_path + PATH_ROOM1_OFF, 4)
    if not room1:
        out["reason"] = ("pRoom1 读不到 —— 检查入口是不是写成了 pPlayer+0x1C"
                         "（那是 pDrlgAct，会静默给出 0 个房间）")
        return out
    out["room1"] = room1

    pa = proc.read_uint(handle, room1 + ROOM1_PTR_OFF, 4)
    n_rooms = proc.read_uint(handle, room1 + ROOMS_NEAR_COUNT_OFF, 4) or 0
    if not pa or not n_rooms:
        out["reason"] = f"paRoomsNear=0x{pa or 0:08X} 房间数={n_rooms}"
        return out
    n_rooms = min(n_rooms, max_rooms)
    out["rooms"] = n_rooms

    seen_rooms: set[int] = set()
    seen_units: set[int] = set()
    for i in range(n_rooms):
        room = proc.read_uint(handle, pa + i * 4, 4)   # ★二级指针：先取数组再取元素
        if not room or room in seen_rooms:
            continue
        seen_rooms.add(room)
        node = proc.read_uint(handle, room + ROOM_UNIT_FIRST_OFF, 4)
        guard = 0
        while node and guard < max_units and node not in seen_units:
            seen_units.add(node)
            guard += 1
            t = proc.read_uint(handle, node + 0x00, 4)
            if t == off.UnitNo.ITEM:
                ua = proc.read_struct(handle, node, st.UnitAny)
                if ua and ua.pUnitData:
                    loc = proc.read_uint(handle, ua.pUnitData + ITEM_LOCATION_OFF, 1)
                    if loc == 0:                       # 0 = 躺在地上
                        idata = proc.read_struct(handle, ua.pUnitData, st.ItemData)
                        if idata:
                            rec = _item_record(ua, idata)
                            rec["ptr"] = node
                            rec["unit_id"] = ua.dwUnitId
                            x, y = read_unit_pos(handle, ua.pPath, 4)
                            rec["x"], rec["y"] = x, y
                            if namer is not None:
                                try:
                                    nm, src = namer.name(node, 4, ua.dwTxtFileNo)
                                except Exception:       # noqa: BLE001
                                    nm, src = "", ""
                                rec["name"] = nm or ""
                                rec["name_src"] = src or ""
                            out["items"].append(rec)
            node = proc.read_uint(handle, node + off.UNIT_NEXT_OFFSET, 4)

    out["units"] = len(seen_units)
    out["ok"] = True
    return out


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
        "file_index": idata.dwFileIndex,   # 暗金/套装专用：UniqueItems.txt / SetItems.txt 行号
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


def hover_blocked_by_ui(handle: int, bases: dict[str, int]) -> list[str]:
    """当前打开的、会挡住世界画面的 UI 面板名（读失败返回空，不影响主流程）。"""
    try:
        ui = read_ui_panels(handle, bases)
        # open 里的名字带停靠侧后缀（如 "仓库(左)"），比对前先剥掉
        return [n for n in (x.split("(")[0] for x in ui.get("open", []))
                if n in off.UI_BLOCKS_HOVER]
    except Exception:  # noqa: BLE001
        return []


def read_hover_text(handle: int, bases: dict[str, int], limit: int = 256) -> str:
    """读 D2WIN 悬停提示框**正在显示的文字**（wchar 缓冲 @ D2WIN+0xC9E58）。

    权威偏移来自只读 dump `D2WIN.DrawHoverText`：它把 x/y/透明度/颜色写进框结构体
    （`+0xCA658~`），把**文本本身**拷进 `0x6F9A9E58`（2KB 缓冲，`DrawHover` 从那儿取来画）。

    ⚠️ 这条链路**不依赖任何 UnitAny 指针** —— 所以鼠标停在「地面物品名文本框」这类
    拿不到单位的场景时，仍然能把游戏显示的那行字读出来。
    返回已用 `lang.strip_color()` 清洗掉 `ÿcX` 颜色符的文本；读不到返回 ""。
    """
    from d2h.acquire import lang

    dw = bases.get("D2WIN")
    if not dw:
        return ""
    addr = dw + (off.VARS["D2WIN"]["HoverTextBuf"] - off.DLLBASE["D2WIN"])
    raw = proc.read_bytes(handle, addr, min(limit, 0x400) * 2) or b""
    s = raw.decode("utf-16-le", "ignore").split("\x00", 1)[0]
    return lang.strip_color(s).strip() if s else ""


# ★★ 悬停「沿触发」表（2026-09-20 老大方案：两个标记一起判，谁跳变就从谁那条路取）
#   老大的判读：`D2WIN+0xCA664` 管 **NPC / 物件 / 背包内物品**；
#               `D2CLIENT+0x11C2F8` **只对地面物品（含地面物品名文本框）响应**。
#   两者互补 —— 地面物品那档 HoverFlag 不抬（实测=0），正由 0x11C2F8 补上；
#   反过来移开时两者都回落，不会再拿陈旧值当"当前对象"。
HOVER_TRIGGER_KEYS: dict[str, tuple[str, str]] = {
    "ground": ("D2CLIENT", "SelectedUnitFlag2"),   # 0x11C2F8 地面物品 / 地面物品名文本框
    "unit": ("D2WIN", "HoverFlag"),                # 0xCA664  NPC / 物件 / UI 内物品
    "npc": ("D2CLIENT", "SelectedUnitFlag"),       # 0x11C2F4 对 NPC 也有响应（仅观测）
}

# 触发键 -> 中文说明（CLI 打印用）
HOVER_TRIGGER_DESC: dict[str, str] = {
    "ground": "地面物品 / 地面物品名文本框",
    "unit": "NPC / 物件 / UI 内物品",
    "npc": "NPC（观测，不单独取）",
}


def read_hover_marks(handle: int, bases: dict[str, int]) -> dict[str, int | None]:
    """只读一遍全部悬停触发标记（**不解析单位**），供「沿触发」比对。

    返回 `{"ground": v, "unit": v, "npc": v}`。哪个标记的值变了，就从它对应的
    路径取一次单位；**都不变 ⇒ 鼠标没换对象 ⇒ 不刷新**（这正是「移开后一直显示
    上一个对象」的解法 —— 旧实现每帧都取，陈旧值就被当成当前对象了）。
    """
    marks: dict[str, int | None] = {}
    for key, (mod, name) in HOVER_TRIGGER_KEYS.items():
        base = bases.get(mod)
        if not base:
            marks[key] = None
            continue
        try:
            addr = base + (off.VARS[mod][name] - off.DLLBASE[mod])
            marks[key] = proc.read_uint(handle, addr, 4)
        except Exception:  # noqa: BLE001
            marks[key] = None
    return marks


def read_hover_unit(handle: int, bases: dict[str, int], gate: bool = False,
                    trigger: str | None = None) -> dict:
    """读取鼠标当前指向的单位（只读）。返回 dict，读不到的字段为 None。

    ★★ 触发方式（`trigger`，2026-09-20 老大定的方案 —— **两个标记一起判**）：
      · `trigger="ground"` → 走**地面物品**路径：直取 hover_id 反查（跳过 CurrentViewItem，
        免得把背包里的物品当成地面对象）
      · `trigger="unit"`   → 走 **NPC / 物件 / UI 内物品**路径：CurrentViewItem 优先，
        再 hover_id 反查
      · `trigger=None`     → 全链依次尝试（旧行为，供 `--no-trigger` 对照）
      由谁触发由调用方比对 `read_hover_marks()` 的跳变决定，本函数只管"从哪条路取"。

    ⚠️ `gate` 参数（HoverFlag 门控）**默认关闭**：实测悬停地面物品时 HoverFlag=0 而真值是对的，
    门控会把真值屏蔽成空。现在"移开后不残留"改由**沿触发**保证（标记回落即视为移开）。

    单位来源优先级（flag=1 时），每一级都过 `_try_ptr()` 校验，失败自动退到下一条：
      1) CurrentViewItem(0x11BC38)  —— 直接就是 UnitAny*（hackmap: 选择显示的物品）
      2) SelectedUnitFlag(0x11C2F4) / Flag2(0x11C2F8) —— ⚠️ **实测是标记不是指针**，
         这里只是留一道校验（真成指针时自动用上，否则跳过）
      3) (HoverUnitId 0x119638, HoverUnitType 0x11964C) —— 兜底：反查 unit 表
      4) D2WIN+0xC9E58 悬停文本 —— 拿不到单位时（地面物品名文本框）仍能报出游戏显示的字

    ★★ UI 阻断**已取消**（2026-09-20）：原先命中 `UI_BLOCKS_HOVER`（背包/仓库/商店…）
    就直接 return、不去解析单位 —— 结果**开着背包时悬停 NPC / 地面物品全部显示为空**
    （用户实机反馈）。现在面板名只作为提示放进 `out["ui"]`，**绝不阻断解析**。
    ⚠️ 教训：那条"防残留"规则是为了解决「仓库界面一直显示储藏箱」，但它把**正常的世界
    悬停**一起误杀了；宁可偶发陈旧值（有 flag 把关），也不要把真实指向屏蔽掉。
    """
    cb = bases.get("D2CLIENT")
    out: dict = {"ptr": None, "source": "", "name": "", "flag": None,
                 "hx": None, "hy": None, "text": ""}
    if not cb:
        return out
    v = off.VARS["D2CLIENT"]

    # ---- D2WIN 侧：悬停开关与悬停框屏幕坐标 ----
    dw = bases.get("D2WIN")
    if dw:
        w = off.VARS["D2WIN"]
        db = off.DLLBASE["D2WIN"]

        def rdw(key: str):
            return proc.read_uint(handle, dw + (w[key] - db), 4)

        out["flag"] = rdw("HoverFlag")
        out["hx"] = rdw("HoverX")
        out["hy"] = rdw("HoverY")
        out["text"] = read_hover_text(handle, bases)

    def rd(key: str):
        return proc.read_uint(handle, cb + (v[key] - off.DLLBASE["D2CLIENT"]), 4)

    out["sel_ptr"] = rd("SelectedUnitFlag")
    out["sel2_ptr"] = rd("SelectedUnitFlag2")
    out["hover_id"] = rd("HoverUnitId")
    out["hover_type"] = rd("HoverUnitType")
    out["view_item"] = rd("CurrentViewItem")

    def _try_ptr(p: int, tag: str) -> bool:
        """校验并把 p 当成 UnitAny* 采信；非法返回 False（指针可能已失效）。"""
        if not p or p < 0x10000 or p > 0x7FFFFFFF:
            return False
        t = proc.read_uint(handle, p + 0x00, 4)
        uid = proc.read_uint(handle, p + 0x0C, 4)
        if t is None or t > 5 or not uid:
            return False
        out["ptr"] = p
        out["source"] = f"{tag} 0x{p:08X}"
        return True

    # ★★ 门控**默认关闭**：HoverFlag 在地面物品悬停时为 0（用户 2026-09-20 实机），
    #    用它阻断会把正确结果屏蔽成空。开 `gate=True` 才走下面这段（仅旧行为对照）。
    if gate and out["flag"] == 0:
        out["source"] = ("无悬停对象(HoverFlag=0，门控已开启) "
                         "—— ⚠️ 地面物品悬停时该位也可能是 0，此结论不可靠")
        return out

    # 按触发源选解析路径（老大方案，见 HOVER_TRIGGER_KEYS 注释）：
    #   ground -> 跳过 CurrentViewItem，直走 hover_id 反查（地面物品是 type=4 的 unit）
    #   unit   -> CurrentViewItem 优先，再 hover_id 反查
    #   None   -> 全链（--no-trigger 对照用）
    if trigger != "ground":
        _try_ptr(out["view_item"], "CurrentViewItem(+0x11BC38)")
    if not out["ptr"]:
        _try_ptr(out["sel_ptr"], "SelectedUnitFlag(+0x11C2F4)")
    if not out["ptr"]:
        _try_ptr(out["sel2_ptr"], "SelectedUnitFlag2(+0x11C2F8)")
    if not out["ptr"]:
        uid, ut = out["hover_id"], out["hover_type"]
        if uid and ut is not None and ut <= 5:
            p = find_unit_by_id(handle, bases, uid, ut)
            if p:
                out["ptr"] = p
                out["source"] = (f"hover_id=0x{uid:X} type={ut} "
                                 f"-> unit 表反查")
    # 打开的面板只作为**提示**带出去，不再阻断解析（见 docstring 的 UI 阻断说明）
    out["ui"] = hover_blocked_by_ui(handle, bases)

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
