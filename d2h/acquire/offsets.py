"""D2 1.13c 偏移表（只读观测用）。

数据全部搬运自参考项目 d2hackmap 的 d2ptrs.h / d2vars.h / d2structs.h，
遵循规范 §13「参考项目最优先：偏移 / 结构体直接复用」。

重要约定（见规范 §2.1 内存只读约束）：
- 本文件**只持有地址常量**，不提供任何写内存能力。
- 下列 VARS/FUNCTIONS 中每个地址都是「DLL 默认基址下的 1.13c 绝对地址」。
  d2hackmap 用 D2*PTR2 宏的**第一个参数**表示 1.13c（第二个是 1.13d）。
- 运行时必须结合进程的**真实模块基址**换算（resolve()），不能硬套 DLLBASE，
  因为部分 DLL（如 D2Game / D2Lang）会被重定位。详见 resolve()。
- FUNCTIONS 是函数入口点（需远程调用，超出只读范畴），仅作参考存档，
  解析层只读 VARS（全局状态指针）即可拿到游戏状态。
"""

from __future__ import annotations

from d2h.acquire import process as proc

# ---- DLL 默认基址（用于把绝对地址换算成相对偏移；运行时以真实基址为准）----
DLLBASE: dict[str, int] = {
    "D2CLIENT": 0x6FAB0000,
    "D2COMMON": 0x6FD50000,
    "D2GFX": 0x6FA80000,
    "D2WIN": 0x6F8E0000,
    "D2LANG": 0x6FC00000,
    "D2CMP": 0x6FE10000,
    "D2MULTI": 0x6F9D0000,
    "BNCLIENT": 0x6FF20000,
    "D2NET": 0x6FBF0000,
    "STORM": 0x6FFB0000,
    "FOG": 0x6FF50000,
    "D2GAME": 0x6FC20000,
    "D2LAUNCH": 0x6FA40000,
    "D2MCPCLIENT": 0x6FA20000,
}

# 逻辑名 -> 进程内模块文件名（用于 get_module_info 取真实基址）
MODULE_FILE: dict[str, str] = {
    "D2CLIENT": "D2Client.dll",
    "D2COMMON": "D2Common.dll",
    "D2GFX": "D2gfx.dll",
    "D2WIN": "D2Win.dll",
    "D2LANG": "D2Lang.dll",
    "D2CMP": "D2CMP.dll",
    "D2MULTI": "D2Multi.dll",
    "BNCLIENT": "BNClient.dll",
    "D2NET": "D2Net.dll",
    "STORM": "Storm.dll",
    "FOG": "Fog.dll",
    "D2GAME": "D2Game.dll",
    "D2LAUNCH": "d2launch.dll",
    "D2MCPCLIENT": "D2MCPClient.dll",
}

# ---- 游戏状态码（多级指针，实测自 Fog.dll；1.13c）----
# 链:  *( *( Fog.dll + 0x4AFE0 ) + 0x08 )  = 状态码
# 实测：11 = 战网登录界面；14 = 人物选择界面（具体成因待查，但确为「不在游戏」态）。
# 语义（用户确认）：<1000（11 / 14 等）= 登录/选人界面、不在游戏；
#                  2xxx = 战网(BN) 游戏内；3xxx = 单机游戏内。
STATE_MEANING: dict[int, str] = {
    11: "战网登录界面",
    14: "人物选择界面",
}
STATE_CHAIN: dict = {
    "module": "FOG",      # 逻辑模块名（MODULE_FILE -> Fog.dll）
    "offset": 0x4AFE0,    # 第一级偏移（相对 Fog.dll 真实基址）
    "final": 0x08,        # 第二级偏移，此处即为状态码（不再解引用）
}

# 状态码区间语义（用于判定"是否在游戏"）
STATE_IN_BN_GAME = (2000, 2999)      # 战网游戏内
STATE_IN_SP_GAME = (3000, 3999)      # 单机游戏内
STATE_LOBBY_MAX = 999                # < 1000 视为登录界面/不在游戏（如 11）

# ---- 游戏内 UI 面板标记（多级指针；1.13c 实测自真实游戏）----
# 真源: p = *( D2CLIENT.dll + 0x50D00 )   —— 必须先解引用！
#       标志在 p + off，每项 4 字节 DWORD。不解引用会读到九位数垃圾。
# 实测(2026-09-19, pid 10872)：I→+0x00=1, c→+0x04=1, t→+0x0C=1, q→+0x38=1,
#   无 UI 时 ESC→+0x20=1（设置），有 UI 时 ESC 关闭当前面板。
UI_PANEL_CHAIN: dict = {
    "module": "D2CLIENT",
    "offset": 0x50D00,
}
# (偏移, 名称, 停靠侧) —— 侧用于解读 UI_SIDE_FLAG；键见 UI_PANEL_KEYS
# 绝对地址（默认基址 0x6FAB0000 下）= 0x6FBAAD84 + 偏移，例如
#   +0x24 = 0x6FBAADA8 正是已知全局 AutomapOn —— 说明它们同属一个全局 UI 结构。
UI_PANELS: list[tuple[int, str, str]] = [
    (0x00, "背包", "右"),
    (0x04, "属性", "左"),
    (0x08, "技能组", "-"),     # 注意：不是技能树
    (0x0C, "技能树", "右"),   # 注意：不是 +0x08
    (0x1C, "NPC对话框", "-"),  # 0x6FBAADA0
    (0x20, "设置", "-"),
    (0x24, "小地图开关", "-"),  # 0x6FBAADA8 = 已知全局 AutomapOn（佐证同属一块）
    (0x2C, "商店", "-"),       # 0x6FBAADB0
    (0x34, "任务物品提交窗", "-"),  # 0x6FBAADB8
    (0x38, "任务", "左"),
    (0x4C, "传送", "-"),       # 0x6FBAADD0
    (0x54, "组队信息", "-"),   # 0x6FBAADD8 按键 P
    (0x5C, "信息页", "-"),
    (0x60, "仓库", "左"),
    (0x64, "盒子", "左"),
    (0x8C, "佣兵装备", "-"),   # 0x6FBAAE10 按键 O
]

# 面板 -> 默认热键（仅用于提示与自动化验证；无按键的面板需鼠标触发，如仓库/盒子/商店）
# 实测状态（2026-09-19，pid 10872）：
#   已验证：背包(I) 属性(C) 技能树(T) 任务(Q) 设置(ESC) 仓库 组队信息(P) 佣兵装备(O)
#   待验证：技能组(+0x08，按 W 无反应，含义待定) NPC对话框 商店 任务物品提交窗 传送
#           信息页 盒子（需鼠标右键开启，无法用按键触发）
UI_PANEL_KEYS: dict[str, str] = {
    "背包": "I",
    "属性": "C",
    "技能树": "T",
    "任务": "Q",
    "组队信息": "P",
    "佣兵装备": "O",
    "设置": "ESC(无 UI 时)",
}

# 关联聚合位 A：D2CLIENT.dll + 0x11C414 —— 实测与上面面板联动（同源 UI 系统）
#   0=无 / 1=右开（背包/技能树）/ 2=左开（属性/任务）/ 3=左右同时开
UI_SIDE_FLAG: dict = {"module": "D2CLIENT", "offset": 0x11C414}
UI_SIDE_MEANING: dict[int, str] = {0: "无", 1: "右开", 2: "左开", 3: "左右开"}

# 关联聚合位 B：D2CLIENT.dll + 0x11BC34 —— 12=仓库 / 14=盒子
#   ⚠️ 未实测（需站在仓库前或打开盒子才能触发），监听时仅原样显示数值。
UI_STASH_FLAG: dict = {"module": "D2CLIENT", "offset": 0x11BC34}
UI_STASH_MEANING: dict[int, str] = {12: "仓库", 14: "盒子"}

# ---- 1.13c 全局变量指针（VARS[dll][name] = 默认基址下的绝对地址）----
# 来源：d2ptrs.h 中 D2VARPTR / D2VARPTR2 的「第一个参数」（即 1.13c 地址）。
VARS: dict[str, dict[str, int]] = {
    "D2CLIENT": {
        "AutomapLayerList": 0x6FBCC1C0,
        "AutomapLayer": 0x6FBCC1C4,
        "PlayerUnit": 0x6FBCBBFC,
        "RosterUnitList": 0x6FBCBC14,
        "PetUnitList": 0x6FBCC4D4,
        "DrlgAct": 0x6FBCC3B8,
        "Expansion": 0x6FBC9854,
        "Difficulty": 0x6FBCC390,
        "GameInfo": 0x6FBCB980,
        "Fps": 0x6FBCC2AC,
        "Ping": 0x6FBC9804,
        "ExitAppFlag": 0x6FBA8C9C,
        "InGame": 0x6FBCC3A0,
        "AutomapOn": 0x6FBAADA8,
        "Divisor": 0x6FBA16B0,
        "Offset": 0x6FBCC1F8,
        "AutomapPos": 0x6FBCC1E8,
        "AutoMapSize": 0x6FBCC230,
        "MinmapType": 0x6FBCC1B0,
        "MinimapOffset": 0x6FBCC228,
        "IsMapShakeOn": 0x6FBCBEFC,
        "MapShakeY": 0x6FBBB9DC,
        "MapShakeX": 0x6FBCBF00,
        "ScreenSizeX": 0x6FB8BC48,
        "ScreenSizeY": 0x6FB8BC4C,
        "ScreenSize": 0x6FB8BC48,
        "DrawOffset": 0x6FBCB9A0,
        "InfoPositionX": 0x6FBA9E14,
        "InfoPositionY": 0x6FBCC21C,
        "QuestData": 0x6FBC973B,
        "GameQuestData": 0x6FBC973F,
        "QuestPage": 0x6FBD3395,
        "MButton": 0x6FBCC3A0,
        "LastChatMessage": 0x6FBCEC80,
        "ChatTextLength": 0x6FBCC028,
        "MousePos": 0x6FBCB824,
        "LastMousePos": 0x6FB8BC54,
        "CursorInvGridX": 0x6FB90EB8,
        "CursorInvGridY": 0x6FB90EBC,
        "CurrentViewItem": 0x6FBCBC38,
        "GoldInTranBox": 0x6FBCBBB0,
        "ShowLifeStr": 0x6FBCC4B0,
        "ShowManaStr": 0x6FBCC4B4,
    },
    "D2COMMON": {
        "WeaponsTxts": 0x6FDEFBA0,
        "ArmorTxts": 0x6FDEFBA8,
        "DataTables": 0x6FDE9E1C,
        "RuneWords": 0x6FDEFBD4,
        "RuneWordTxt": 0x6FDEFBD8,
    },
    "D2GFX": {
        "WinState": 0x6FA9D66C,
    },
    "D2WIN": {
        "FocusedControl": 0x6F9014B0,
    },
    "D2NET": {
        "UnkNetFlag": 0x6FBFB244,
    },
    "BNCLIENT": {
        "BnChatMessage": 0x6FF3F64C,
    },
    "D2MULTI": {
        "GameListControl": 0x6FA09CC0,
        "EditboxPreferences": 0x6F9E9C60,
    },
}

# ---- 1.13c 函数入口点（仅参考存档；需远程调用，超出只读范畴）----
# 来源：d2ptrs.h 中 D2FUNCPTR2 的「第一个参数」。解析层不使用。
FUNCTIONS: dict[str, dict[str, int]] = {
    "D2CLIENT": {
        "ShowGameMessage": 0x6FB2D850,
        "ShowPartyMessage": 0x6FB2D610,
        "ShowMap": 0x6FAEB8B0,
        "RevealAutomapRoom": 0x6FB12580,
        "GetPlayerXOffset": 0x6FAEF6C0,
        "GetPlayerYOffset": 0x6FAEF6D0,
        "SetUiStatus": 0x6FB72790,
        "GetUnitFromId": 0x6FB55B40,
        "GetSelectedUnit": 0x6FB01A80,
        "CheckUiStatusStub": 0x6FB6E400,
        "ItemProtect": 0x6FAD3200,
        "DrawClient": 0x6FAD9250,
        "Storm511": 0x6FABBE84,
    },
    "D2COMMON": {
        "GetObjectTxt": 0x6FD8E980,
        "GetLevelDefTxt": 0x6FDBCB20,
        "GetLevelTxt": 0x6FDBCCC0,
        "GetItemTxt": 0x6FDC19A0,
        "GetUnitStat": 0x6FD88B70,
        "GetUnitBaseStat": 0x6FD88C20,
        "CheckUnitState": 0x6FD83CD0,
        "GetItemValue": 0x6FD79D60,
        "GetCursorItem": 0x6FD6DFB0,
        "GetFirstItemInInv": 0x6FD6E190,
        "GetNextItemInInv": 0x6FD6E8F0,
        "GetUnitPosX": 0x6FD84B80,
        "GetUnitPosY": 0x6FD84BB0,
    },
    "D2GFX": {
        "GetHwnd": 0x6FA87FB0,
    },
}


# ---- 枚举（来自 d2vars.h）----
class UnitNo:
    PLAYER = 0
    MONSTER = 1
    OBJECT = 2
    MISSILE = 3
    ITEM = 4
    ROOMTILE = 5


class ItemQuality:
    INVALID = 0
    LOW = 1
    NORMAL = 2
    SUPERIOR = 3
    MAGIC = 4
    SET = 5
    RARE = 6
    UNIQUE = 7
    CRAFTED = 8
    TAMPERED = 9


# ITEMFLAG_*（dwItemFlags 位掩码）
class ItemFlag:
    IDENTIFIED = 0x00000010
    SOCKETED = 0x00000800
    ETHEREAL = 0x00400000
    RUNEWORD = 0x04000000


# UIVAR_*（界面编号；细化判断需用 CheckUiStatusStub 函数，此处仅存档）
class UIVar:
    INVENTORY = 1
    STATS = 2
    SKILLS = 4
    CHATINPUT = 5
    GAMEMENU = 9
    ATUOMAP = 10
    NPCTRADE = 12
    SHOWITEMS = 13
    QUEST = 15
    WAYPOINT = 20
    MINIPANEL = 21
    PARTY = 22
    STASH = 25
    CUBE = 26
    BELT = 31
    HELP = 33
    PET = 36


# UNIT_STAT_*（属性编号，来自 d2vars.h UnitStat）
class UnitStat:
    STRENGTH = 0
    ENERGY = 1
    DEXTERITY = 2
    VITALITY = 3
    STATPOINTSLEFT = 4
    NEWSKILLS = 5
    HP = 6
    MAXHP = 7
    MANA = 8
    MAXMANA = 9
    LEVEL = 12
    EXP = 13
    GOLD = 14
    GOLDBANK = 15
    MAGIC_FIND = 80
    IAS = 93
    FCR = 105
    NUMSOCKETS = 194


# BODY_LOCATION（装备槽位）
class BodyLocation:
    NONE = 0
    HEAD = 1
    AMULET = 2
    BODY = 3
    RIGHT_PRIMARY = 4
    LEFT_PRIMARY = 5
    RIGHT_RING = 6
    LEFT_RING = 7
    BELT = 8
    FEET = 9
    GLOVES = 10
    RIGHT_SECONDARY = 11
    LEFT_SECONDARY = 12


# ----------------------------------------------------------------
# 解析辅助：把「默认基址下的绝对地址」换算成「真实模块基址下的地址」。
# 运行时必须先收集真实模块基址（collect_module_bases），再 resolve。
# ----------------------------------------------------------------

def collect_module_bases(handle: int, dlls: list[str] | None = None) -> dict[str, int]:
    """收集所需 DLL 的真实模块基址：{逻辑名: base}。找不到的不会出现在结果里。"""
    if dlls is None:
        dlls = list(MODULE_FILE.keys())
    bases: dict[str, int] = {}
    for dll in dlls:
        fname = MODULE_FILE.get(dll)
        if not fname:
            continue
        info = proc.get_module_info(handle, fname)
        if info:
            bases[dll] = info[0]
    return bases


def resolve(bases: dict[str, int], dll: str, name: str) -> int | None:
    """把 1.13c 绝对地址换算为进程真实地址；模块未加载或名称未知返回 None。"""
    if dll not in bases:
        return None
    if dll not in VARS or name not in VARS[dll]:
        return None
    return bases[dll] + (VARS[dll][name] - DLLBASE[dll])


def read_ptr(handle: int, bases: dict[str, int], dll: str, name: str) -> int | None:
    """读取一个 4 字节指针值（变量指针指向的数据地址或指针本身）。"""
    addr = resolve(bases, dll, name)
    if addr is None:
        return None
    return proc.read_uint(handle, addr, 4)


def read_byte(handle: int, bases: dict[str, int], dll: str, name: str) -> int | None:
    """读取 1 字节（如 InGame / BOOL 标志）。"""
    addr = resolve(bases, dll, name)
    if addr is None:
        return None
    return proc.read_uint(handle, addr, 1)
