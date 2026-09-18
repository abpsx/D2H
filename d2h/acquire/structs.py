"""D2 1.13c 核心结构体（ctypes 重建），搬运自参考项目 d2structs.h / d2vars.h。

遵循规范 §13「结构体直接复用」。所有布局按 d2structs.h 的字段偏移逐字节对齐，
仅供采集层以只读方式解析游戏内存使用。注释中的 +0xXX 即字段在结构体中的偏移。

对齐说明：所有成员均为 1/2/4 字节宽，结构体按 4 字节对齐，与原始 C 布局一致。
"""

from __future__ import annotations

import ctypes

DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
BYTE = ctypes.c_uint8
CHAR = ctypes.c_char
BOOL_ = ctypes.c_int32


class D2Seed(ctypes.Structure):
    _fields_ = [
        ("dwLowSeed", DWORD),
        ("dwHighSeed", DWORD),
    ]


class DynamicPath(ctypes.Structure):
    """动态路径（玩家/怪物/导弹的位置信息），仅取坐标相关字段。"""
    _fields_ = [
        ("wOffsetX", WORD),    # +00
        ("wPosX", WORD),      # +02
        ("wOffsetY", WORD),    # +04
        ("wPosY", WORD),      # +06
        ("dwMapPosX", DWORD),  # +08
        ("dwMapPosY", DWORD),  # +0C
    ]


class PlayerData(ctypes.Structure):
    _fields_ = [
        ("szName", CHAR * 16),        # +00  角色名（单字节）
        ("pNormalQuest", DWORD),      # +10
        ("pNightmareQuest", DWORD),   # +14
        ("pHellQuest", DWORD),        # +18
        ("pNormalWaypoint", DWORD),   # +1C
        ("pNightmareWaypoint", DWORD),# +20
        ("pHellWaypoint", DWORD),     # +24
    ]


class ItemData(ctypes.Structure):
    _fields_ = [
        ("dwQuality", DWORD),          # +00
        ("seed", D2Seed),              # +04
        ("dwOwnerId", DWORD),          # +0C
        ("dwFingerPrint", DWORD),      # +10
        ("dwCommandFlags", DWORD),      # +14
        ("dwItemFlags", DWORD),         # +18
        ("_1", DWORD * 2),             # +1C
        ("ActionStamp", DWORD),        # +24
        ("dwFileIndex", DWORD),        # +28  UniqueItems/SetItems/... 索引
        ("dwItemLevel", DWORD),        # +2C  ILvl
        ("wItemFormat", WORD),         # +30
        ("wRarePrefix", WORD),         # +32
        ("wRareSuffix", WORD),         # +34
        ("wAutoPrefix", WORD),         # +36
        ("wMagicPrefix", WORD * 3),    # +38
        ("wMagicSuffix", WORD * 3),    # +3E
        ("nBodyLocation", BYTE),       # +44
        ("nItemLocation", BYTE),       # +45  -1 装备中 / 0 背包 / 3 方块 / 4 仓库
        ("_2", BYTE * 2),              # +46
        ("nEarLevel", BYTE),           # +48
        ("nInvGfxIdx", BYTE),          # +49
        ("szPlayerName", CHAR * 16),   # +4A  用于耳朵 / 个性化物品
        ("_3", BYTE * 2),              # +5A
        ("pOwnerInventory", DWORD),    # +5C
        ("_4", DWORD),                 # +60
        ("pNextInvItem", DWORD),       # +64
        ("_11", BYTE),                 # +68
        ("nLocation", BYTE),           # +69  0 地面 / 1 方块·仓库·背包 / 2 腰带 / 3 身上
    ]


class UnitInventory(ctypes.Structure):
    _fields_ = [
        ("dwInvStamp", DWORD),     # +00  0x1020304 校验
        ("pMemPool", DWORD),       # +04
        ("pOwner", DWORD),         # +08
        ("pFirstItem", DWORD),     # +0C  背包内第一个物品
        ("pLastItem", DWORD),      # +10
        ("pInvInfo", DWORD),       # +14  已装备装备链表
        ("dwInvInfoCount", DWORD), # +18
        ("dwWeaponId", DWORD),     # +1C
        ("pCursorItem", DWORD),    # +20
        ("dwOwnerId", DWORD),      # +24
        ("dwFilledSockets", DWORD),# +28
    ]


class UnitAny(ctypes.Structure):
    _fields_ = [
        ("dwUnitType", DWORD),     # +00
        ("dwTxtFileNo", DWORD),    # +04
        ("pMemPool", DWORD),       # +08
        ("dwUnitId", DWORD),       # +0C
        ("dwMode", DWORD),         # +10
        ("pUnitData", DWORD),      # +14  union: PlayerData*/MonsterData*/ItemData*/...
        ("dwAct", DWORD),          # +18
        ("pDrlgAct", DWORD),       # +1C
        ("seed", D2Seed),          # +20
        ("dwInitSeed", DWORD),     # +28
        ("pPath", DWORD),          # +2C  union: StaticPath*/DynamicPath*
        ("_1", DWORD * 11),        # +30
        ("pStatList", DWORD),      # +5C
        ("pInventory", DWORD),     # +60
        ("_2", DWORD * 12),        # +64
        ("dwOwnerType", DWORD),    # +94
        ("dwOwnerId", DWORD),      # +98
        ("_3", DWORD * 3),         # +9C
        ("pSkill", DWORD),         # +A8
        ("_4", DWORD * 6),         # +AC
        ("dwFlags1", DWORD),       # +C4
        ("dwFlags2", DWORD),       # +C8
        ("_5", DWORD * 6),         # +CC
        ("pRoomNext", DWORD),      # +E4
        ("pListNext", DWORD),      # +E8
    ]


class GameStructInfo(ctypes.Structure):
    _fields_ = [
        ("_1", BYTE * 27),             # +00
        ("szGameName", CHAR * 24),     # +1A
        ("szGameServerIp", CHAR * 86), # +32
        ("szAccountName", CHAR * 48),  # +88
        ("szCharName", CHAR * 24),     # +B8
        ("szRealmName", CHAR * 24),    # +D0
        ("_2", BYTE * 258),            # +E8
        ("nGameMode", BYTE),           # +1EB  含 hc/ladder/expansion 等位域
        ("nReadyAct", BYTE),           # +1EC
        ("_3", BYTE * 60),             # +1ED
        ("szServerVersion", CHAR * 24),# +228
        ("szGamePassword", CHAR * 24), # +240
    ]


class RosterUnit(ctypes.Structure):
    _fields_ = [
        ("szName", CHAR * 16),     # +00
        ("dwUnitId", DWORD),       # +10
        ("dwPartyLife", DWORD),    # +14
        ("dwKills", DWORD),        # +18
        ("dwClassId", DWORD),      # +1C
        ("wLevel", WORD),          # +20
        ("wPartyId", WORD),        # +22
        ("dwLevelNo", DWORD),      # +24
        ("dwPosX", DWORD),         # +28
        ("dwPosY", DWORD),         # +2C
        ("dwPartyFlags", DWORD),   # +30
        ("pPvPInfo", DWORD),       # +34
        ("pMinon", DWORD),         # +38
        ("_6", DWORD * 10),        # +3C
        ("_7", WORD),              # +64
        ("szName2", CHAR * 16),    # +66
    ]


class DrlgAct(ctypes.Structure):
    """精简版：仅取 pRoom1 / dwActNo / pDrlgMisc。"""
    _fields_ = [
        ("_1", DWORD * 4),     # +00
        ("pRoom1", DWORD),     # +10
        ("dwActNo", DWORD),    # +14
        ("_2", DWORD * 12),    # +18
        ("pDrlgMisc", DWORD),  # +48
    ]


def read_unit(handle: int, addr: int, cls=UnitAny):
    """从进程内存读取一个结构体实例；失败返回 None。"""
    from d2h.acquire import process as proc

    return proc.read_struct(handle, addr, cls)
