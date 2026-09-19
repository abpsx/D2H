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

# ---- 游戏内 UI 标志数组（多级指针；1.13c 实测 + 参考项目 hackmap 对照）----
# 真源: p = *( D2CLIENT.dll + 0x50D00 )   —— 必须先解引用，不解引用会读到九位数垃圾。
#   实测 p = 0x6FBAAD84；**UIVar 数组起点 = p - 4 = 0x6FBAAD80**。
#
# ★★★ 与参考项目 hackmap `d2vars.h` 的 `enum UIVar` 完全对齐 ★★★
#   数组 = 38 个 DWORD（index 0..37），偏移 = index*4，范围 0x6FBAAD80 ~ 0x6FBAAE14（含）。
#   钉死基址的硬证据（2026-09-19 dump 实测，pid 10872）：
#     index  0 = 1  ← hackmap 注释 "UIVAR_UNK0 ... always 1"
#     index 19 = 1  ← hackmap 注释 "UIVAR_UNK19 ... init 1"
#     index 10 = 0x6FBAADA8 ← hackmap d2ptrs.h 里点名的全局变量 AutomapOn（小地图开关）
#     数组前 8 个 DWORD 全 0，index 38 起是垃圾值（越界）→ 数组长度正好 38 项。
#   ⚠️ 早期版本把 p 当数组起点，导致**全部偏移少 4**（整体错位一格），现已修正。
UI_PANEL_CHAIN: dict = {
    "module": "D2CLIENT",
    "offset": 0x50D00,
}
# UIVar 数组起点 = 解引用值 + UI_ARRAY_DELTA（即 p - 4）
UI_ARRAY_DELTA: int = -0x04

# (偏移, 名称, 停靠侧) —— 偏移相对**数组起点**；侧用于解读 UI_SIDE_FLAG；键见 UI_PANEL_KEYS
# 状态标记：[V]=按键实测通过  [U]=用户已核验  [?]=未辨明（只有 hackmap 命名，未实测）
UI_PANELS: list[tuple[int, str, str]] = [
    (0x00, "数组头(恒1)", "-"),      # [V] UNK0      always 1
    (0x04, "背包", "右"),            # [V] INVENTORY 键 I
    (0x08, "属性", "左"),            # [V] STATS     键 C
    (0x0C, "技能组(左右手)", "-"),    # [U] CURRSKILL 左右手技能选择（不是技能树）
    (0x10, "技能树", "右"),          # [V] SKILLS    键 T
    (0x14, "聊天输入", "-"),         # [U] CHATINPUT（用户已核验） 键 ENTER
    (0x18, "新属性点按钮", "-"),      # [U] NEWSTATS（用户已核验）  （当前=1，疑"有未分配属性点"）
    (0x1C, "新技能点按钮", "-"),      # [U] NEWSKILL（用户已核验）  （当前=1，疑"有未分配技能点"）
    (0x20, "NPC对话框", "-"),        # [U] INTERACT
    (0x24, "设置", "-"),             # [V] GAMEMENU  无 UI 时按 ESC 打开
    (0x28, "地图", "-"),             # [U] AUTOMAP   = 全局 AutomapOn，键 TAB
    (0x2C, "配置快捷键", "-"),        # [U] CFGCTRLS（用户已核验）
    (0x30, "商店(NPC交易)", "-"),     # [U] NPCTRADE
    (0x34, "显地面物品", "-"),        # [U] SHOWITEMS（用户已核验） 键 ALT
    (0x38, "打孔/注入窗", "-"),       # [U] MODITEM   （用户原称"任务物品提交窗"）
    (0x3C, "任务", "左"),            # [V] QUEST     键 Q
    (0x40, "UNK16", "-"),            # [?]
    (0x44, "任务日志按钮", "-"),      # [U] NEWQUEST  左下角任务日志按钮（用户已核验）
    (0x48, "下方面板", "-"),          # [?] STATUSAREA 置位时下部面板不重绘
    (0x4C, "UNK19(初值1)", "-"),      # [V] UNK19     dump 实测 =1
    (0x50, "传送", "-"),             # [U] WAYPOINT
    (0x54, "迷你标签栏", "-"),        # [U] MINIPANEL
    (0x58, "组队", "-"),             # [V] PARTY     键 P
    (0x5C, "玩家交易", "-"),          # [U] PPLTRADE（用户已核验）
    (0x60, "信息页(消息日志)", "-"),   # [U] MSGLOG
    (0x64, "仓库", "左"),            # [V] STASH
    (0x68, "盒子", "左"),            # [U] CUBE
    (0x6C, "UNK27", "-"),            # [?]
    (0x70, "背包2", "-"),            # [?] INVENTORY2
    (0x74, "背包3", "-"),            # [?] INVENTORY3
    (0x78, "背包4", "-"),            # [?] INVENTORY4
    (0x7C, "腰带", "-"),             # [?] BELT
    (0x80, "UNK32", "-"),            # [?]
    (0x84, "帮助", "-"),             # [U] HELP（用户已核验）      键 H
    (0x88, "UNK34", "-"),            # [?]
    (0x8C, "玩家头像列表", "-"),            # [U] PARTYHEAD（用户判明=玩家头像列表） （当前=1）
    (0x90, "佣兵装备", "-"),          # [V] PET       键 O
    (0x94, "任务卷轴", "-"),          # [U] QUESTSCROLL（用户已核验） 点击任务物品时显示任务信息
]

# index -> hackmap `enum UIVar` 名字（便于回查参考项目源码里的用法）
UI_PANEL_HM: dict[int, str] = {
    0: "UNK0", 1: "INVENTORY", 2: "STATS", 3: "CURRSKILL", 4: "SKILLS",
    5: "CHATINPUT", 6: "NEWSTATS", 7: "NEWSKILL", 8: "INTERACT",
    9: "GAMEMENU", 10: "AUTOMAP", 11: "CFGCTRLS", 12: "NPCTRADE",
    13: "SHOWITEMS", 14: "MODITEM", 15: "QUEST", 16: "UNK16",
    17: "NEWQUEST", 18: "STATUSAREA", 19: "UNK19", 20: "WAYPOINT",
    21: "MINIPANEL", 22: "PARTY", 23: "PPLTRADE", 24: "MSGLOG",
    25: "STASH", 26: "CUBE", 27: "UNK27", 28: "INVENTORY2",
    29: "INVENTORY3", 30: "INVENTORY4", 31: "BELT", 32: "UNK32",
    33: "HELP", 34: "UNK34", 35: "PARTYHEAD", 36: "PET",
    37: "QUESTSCROLL",
}

# 面板 -> 默认热键（提示与自动化验证用；无按键的面板需鼠标/NPC 触发，如仓库/盒子/商店）
UI_PANEL_KEYS: dict[str, str] = {
    "背包": "I",
    "属性": "C",
    "技能树": "T",
    "任务": "Q",
    "组队": "P",
    "佣兵装备": "O",
    "设置": "ESC(无 UI 时)",
    "地图": "TAB",
    "显地面物品": "ALT",
    "聊天输入": "ENTER",
    "帮助": "H",
}

# 会挡住世界画面的面板：打开时鼠标不在世界画面上，(unitId, 类型) 缓存会停在
# 最后交互的世界对象上（例如点储藏箱进仓库后一直显示"储藏箱"）。
# ⇒ 这些面板打开时禁止用 hover_id 反查世界单位，只看 CurrentViewItem（UI 内物品）。
UI_BLOCKS_HOVER: set[str] = {
    "仓库", "盒子", "商店", "NPC对话框", "传送", "任务物品提交窗",
    "玩家交易", "佣兵装备", "背包", "赫拉迪克方块",
}

# 关联聚合位 A：D2CLIENT.dll + 0x11C414 —— 实测与上面面板联动（同源 UI 系统）
#   0=无 / 1=右开（背包/技能树）/ 2=左开（属性/任务）/ 3=左右同时开
UI_SIDE_FLAG: dict = {"module": "D2CLIENT", "offset": 0x11C414}
UI_SIDE_MEANING: dict[int, str] = {0: "无", 1: "右开", 2: "左开", 3: "左右开"}

# 关联聚合位 B：D2CLIENT.dll + 0x11BC34 —— 12=仓库 / 14=盒子
#   ⚠️ 未实测（需站在仓库前或打开盒子才能触发），监听时仅原样显示数值。
UI_STASH_FLAG: dict = {"module": "D2CLIENT", "offset": 0x11BC34}
UI_STASH_MEANING: dict[int, str] = {12: "仓库", 14: "盒子"}

# ---- unit hash 表（按类型分块；配合 VARS.D2CLIENT.UnitTable 使用）----
#   块索引 = 单位类型（0玩家/1怪物NPC/2物件/3导弹/4物品/5房间格）
#   每块 128 个桶 × 4 字节 = 512 字节；桶索引 = unitId & 0x7F
#   桶内链表：UnitAny.pListNext（+0xE8）
UNIT_TABLE_STRIDE: int = 512      # 每种类型一块，512 字节
UNIT_TABLE_BUCKETS: int = 128     # 每块 128 个桶
UNIT_NEXT_OFFSET: int = 0xE8      # UnitAny.pListNext

# ---- 1.13c 全局变量指针（VARS[dll][name] = 默认基址下的绝对地址）----
# 来源：d2ptrs.h 中 D2VARPTR / D2VARPTR2 的「第一个参数」（即 1.13c 地址）。
VARS: dict[str, dict[str, int]] = {
    "D2CLIENT": {
        "AutomapLayerList": 0x6FBCC1C0,
        "AutomapLayer": 0x6FBCC1C4,
        "PlayerUnit": 0x6FBCBBFC,
        # ★ 鼠标指向/悬停单位（UnitAny*）—— 来自参考项目 d2ptrs.h:139
        #   D2VARPTR2(D2CLIENT, 0x6FBCBC38, ..., CurrentViewItem, UnitAny*) // 选择显示的物品
        #   hackmap 里**唯一**一个非 PlayerUnit 的 UnitAny* 全局，就是"当前查看/悬停的对象"。
        "CurrentViewItem": 0x6FBCBC38,
        # ★ `+0x11C2F4` / `+0x11C2F8` = **标记（不是指针）** —— 2026-09-20 老大实机拍板：
        #   指针形态始终没出现过（悬停时也只是 0/1），且 log 只对**地面物体本体**响应，
        #   **不对地面物品名文本框响应**。早期误当指针解引用导致崩溃。
        #   GetSelectedUnit(0x6FB01A80) 里 `mov eax,[0x6FBCC2F4]; test eax,eax; je -> 0`
        #   是"有选中才继续查"的条件，结尾 `C7 05 ...,0` 把两个一起清 0（标志或缓存都这么写）。
        # ⇒ 现在只作**诊断信息打印**；`read_hover_unit()` 里仍过一遍 `_try_ptr()` 校验，
        #   万一将来某个版本真存了指针也能自动用上，但不会再因它崩或误报。
        #   真正解决"地面物品名文本框"的是 **D2WIN+0xC9E58 悬停文本**（见 D2WIN 段）。
        "SelectedUnitFlag": 0x6FBCC2F4,
        "SelectedUnitFlag2": 0x6FBCC2F8,
        # ★ 悬停单位的 (unitId, 类型) —— GetSelectedUnit 就是用这两个去查 unit 表的：
        #   mov edx,[0x6FBC964C]; shl edx,9; add edx,0x6FBBA608   ← 块索引 = 类型
        #   mov ecx,[0x6FBC9638]; and eax,0x7F                    ← 桶索引 = unitId & 0x7F
        #   实测：悬停怪物时 HoverUnitId=0x0B、HoverUnitType=1。
        "HoverUnitId": 0x6FBC9638,
        "HoverUnitType": 0x6FBC964C,
        # unit hash 表基址（块 = 类型，见 game.find_unit_by_id）
        "UnitTable": 0x6FBBA608,
        "MousePos": 0x6FBCB824,          # D2_POINT_REV 鼠标位置（d2ptrs.h MousePos）
        "LastMousePos": 0x6FB8BC54,      # 最后一次鼠标位置
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
        # ---- 悬停提示框（hover box）状态；用户提供地址，2026-09-20 实测 ----
        # HoverFlag = 1 时表示鼠标正悬停在「可交互对象」上（NPC / 物件 / 物品，
        # 含仓库/背包 UI 内的物品）；指向地面或空处时为 0。
        # 这是比 D2CLIENT 侧 (unitId, 类型) 更干净的悬停开关：移开立即归零，
        # 不会出现「地面 tile 闪一帧」，也不会在 UI 打开时残留上一个世界对象。
        #
        # ★ 结构体布局由 **只读 dump D2WIN.DrawHoverText(D2WIN+0x118F0)** 钉死（2026-09-20）：
        #   6F8F1933  89 1D 58 A6 9A 6F   mov [0x6F9AA658], ebx   ; xPos
        #   6F8F1939  A3 5C A6 9A 6F      mov [0x6F9AA65C], eax   ; yPos
        #   6F8F193E  89 0D 60 A6 9A 6F   mov [0x6F9AA660], ecx   ; dwTran（透明度）
        #   6F8F1944  89 15 64 A6 9A 6F   mov [0x6F9AA664], edx   ; dwColor（颜色/有效位）
        #   6F8F194A  C7 05 68 A6 9A 6F 0 mov [0x6F9AA668], 0
        #   ⇒ 整块只有 0x28 字节（0xCA658~0xCA680），后面 0xCA66C/670/674/678 是框的矩形。
        # ⚠️ +0xCA658 / +0xCA65C **不是指针**，是悬停框的**屏幕坐标 (x, y)**（整数）：
        #    左右移动鼠标只有 x 变、上下移动只有 y 变（2026-09-20 用户实测）；
        #    对象挪到画面左上角时 xy 均为个位数 ⇒ 以**客户区左上角**为原点
        #    （不含窗口标题栏/边框，即 D2 的 800x600 画面坐标系）。
        "HoverX": 0x6F9AA658,
        "HoverY": 0x6F9AA65C,
        "HoverTran": 0x6F9AA660,
        "HoverFlag": 0x6F9AA664,
        "HoverRectL": 0x6F9AA66C,     # 实到 109/99，疑似 right/bottom 或宽高，待确认
        "HoverRectT": 0x6F9AA670,
        "HoverRectR": 0x6F9AA674,
        "HoverRectB": 0x6F9AA678,
        # ★ 悬停**文本内容**（wchar 缓冲，最长 0x400 字符 = 2KB）—— 权威偏移来自
        #   DrawHoverText 里 `mov ecx,0x6F9A9E58` / `mov edi,0x6F9A9E58`（rep stosd 清零 2KB）
        #   以及 DrawHover(D2WIN+0x133A0) 里 `mov eax,0x6F9A9E58` 读它来画。
        #   ⇒ 悬停任何东西时，游戏**正在显示的这段字**我们都能直接读出来（含颜色符 ÿcX）。
        #   ⚠️ 别和上面的框结构体搞混：框在 +0xCA658，文本在 +0xC9E58。
        "HoverTextBuf": 0x6F9A9E58,
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
