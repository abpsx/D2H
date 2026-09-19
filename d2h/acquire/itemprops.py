"""物品词缀 + 属性解析（只读）。

来源全部是**游戏内存现表**（遵循规范 §2.1 只读、§13 参考项目优先、§12 完整打印）。

取行公式（★老大实机反汇编，2026-09-20；这是**游戏的权威算法**，优先于任何猜测）
================================================================================
  稀有取行  D2Common+0x71790 : lea eax,[ecx+eax*8-0x48]  ->  rec = 表址 + (值-1)*0x48
  词缀取行  D2Common+0x71841 : lea eax,[eax+ecx-0x90]    ->  rec = 表址 + (值-1)*0x90

⇒ 两条都是 **1 基（值-1）**：值 = 1 就是表首行。id=0 表示"无"。
   本模块因此把「另一解（值 当 0 基）」也一并打印出来，供实机悬停文本对答案；
   但**采信列 = 游戏公式**。

gpt 描述区布局（1.13c；2026-09-20 逐槽实机读出）
=================================================================
gpt = D2COMMON + (0x6FDEFB94 − DLLBASE_D2COMMON)      —— 描述区**基址本身**（不解引用）

  偏移    值(实测)        判读（依据）
  +0x00  0x2CC = 716       nItemsTxt（716 与 item.txt 行数吻合）
  +0x04  0                 空
  +0x08  ptr  0x131B72CC    ┐
  +0x0C  306                │ ItemTxt 的 306+202+208 = 716 = nItemsTxt
  +0x10  ptr  0x131D6D9C    │ ⇒ +0x08..+0x1C 是 ItemTxt 的分块 {ptr,count}
  +0x14  202                │
  +0x18  ptr  0x131EBC2C    │
  +0x1C  208                ┘
  +0x20  ptr  0x132031A4    ┐ 内容为递增 WORD 序号表(0,1,2,…)，**未辨明**
  +0x24  1452               ┘
  +0x28  0                 空槽（★曾误把它当 MagicSuffix 指针，已纠正）
  +0x2C  ptr  ★ 0x90 块基址 B —— rec0 szName='of Health'
  +0x30  ptr  B + 747 行      —— rec1 szName='Sturdy'（rec0 空）
  +0x34  ptr  B + 1416 行     —— rec0 szName="Fletcher's"
  +0x38  0x47 = 71            第三段行数
  +0x3C  ptr  Gems        —— rec0 szName='Chipped Amethyst'
  +0x40  0xA9 = 169       nGems
  +0x44  ptr  Runes/Runewords
  +0x48  0xC9 = 201       n（实测 = 稀有名字词块总行数 155+46，见下）
  +0x50  ptr  ★ 0x48 块基址 RS —— 稀有名字词：rec 名字串@+0x26、locale@+0x0C
  +0x54  ptr  RS + 155 行      —— 稀有前缀名字词
  +0x64 起                    递增小整数数组（未辨明）

★ 0x90 块（一张大表，行距 0x90，**只有一个基址 B = *(gpt+0x2C)**）实测分段：
      值 1..747      行 0..746     后缀区   rec0 'of Health' … rec746 'of the Vampire'
      值 748..1416   行 747..1415  前缀区   rec747 空行、rec748 'Sturdy' … rec1415 'Cruel'
      值 1417..1487  行 1416..1486 第三段   rec1416 "Fletcher's" …（共 71 行 = gpt+0x38）
  · 边界与分段是**实测**（脚本打行名核出来的），不是推算；
  · 第三段身份**推断 = 自动前缀(automagic)**，三条依据：① 与 magic 块**同一块、无缝隙**
    （T3 == SUF + 1416*0x90 实测为 True）；② 实机 wAutoPrefix 取值 1425/1441/1443 全部落在
    1417..1487 内；③ 行名与 automagic 语义吻合（低阶/职业词条：of the Jackal/Fox…、
    Lizard's…、Shimmering/Rainbow…、Sharp/Fine、Fletcher's/Bowyer's/Archer's…）。
    ⚠️ 仍标「推断」：等老大实机确认前不当硬事实用。

★ 0x48 块（稀有物品**名字词**表，行距 0x48，基址 RS = *(gpt+0x50)**）实测分段：
      值 1..155      行 0..154   后缀词   'bite'/'scratch'/…/'flange'
      值 156..201    行 155..200 前缀词   'Beast'/'Eagle'/…/'Corruption'
  ⇒ 实机 wRarePrefix 取值 159..189、wRareSuffix 取值 64..135，**全部落在各自区段**（11 件无一例外）。
  这解释了「为什么 wRarePrefix 会 >46」：字段不是各表内序号，而是**整块 1 基序号**。
  ⇒ 该字段是**名字词**索引（决定物品显示名），不是 affix 索引（mod 在物品 StatList 里，生成时已定）。

词缀记录 `rec = 0x90`（列名 = 实测对照出的语义）
  +0x00  char szName[32]    内部英文名（如 'of Health' / 'Sturdy'）
  +0x20  WORD wLocaleTxtNo  显示名 —— 走 D2Lang 内存字符串表（lang.LocaleText）
  +0x24  DWORD nGroup       组号（同组 = 同一词缀的不同档：Sturdy/Strong 同组 5）
  +0x2C  DWORD nMin         mod1 取值下限（'of the Jackal' 1 / 'of the Fox' 6 …）
  +0x30  DWORD nMax         mod1 取值上限（'of the Jackal' 5 / 'of the Fox' 10 …）
   依据：第三段 71 行的这三列与「生命/法力/全抗/伤害」档位**逐行吻合**
   （13 组 1-5/6-10/…/41-60 = 生命；11 组 = 法力；41 组 5-10/8-15/16-30/25-35/35-45 = 全抗）。

稀有名字词记录 `rec = 0x48`
  +0x0C  WORD wLocaleTxtNo  中文名（如 'beast'→'野兽之'）
  +0x26  char szName        内部英文名（如 'Beast'）

ItemStatCost（属性名）
  DT  = *(D2COMMON + (0x6FDE9E1C − DLLBASE_D2COMMON))     DataTables
  ISC = *(DT + 0xBCC)    rec = 0x144
     +0x00 DWORD dwStatNo    +0x36 BYTE nDescFunc   +0x37 BYTE nDescVal
     +0x38 WORD  wDescStrpos（描述模板 locale id，如 stat31 → '防御 (DEF)'）
  ★ 已验证：desc/func/val 三列正确（打印出来的名字与实机悬停文本一致）。
  ⚠️ 未验证：hackmap 标的 dwDivide(+0x0C)/dwMultiply(+0x10) **在本机 1.13c 上不成立**：
     +0x0C 恒为 1024、+0x10 是各种零碎小整数，拿它们做折算会得到荒谬值（防御 175 → 1.709）。
     实机悬停文本对答案（2026-09-20，runeword「时间」Demonhead）：
       防御 175、MDR 7、四抗 15、毒抗上限 5、经验获得 3、IAS 20、FBR 18、FCR 30
       —— **全部 raw 直读 == 显示值**（系数 1）。
     ⇒ 现在默认 **不做折算（show = raw）**；hp/mana 家族（stat 6/7/8/9/10/11）另给
       `raw>>8` 作为**候选**并显式标注"未实机验证"（D2 惯例：生命/法力存 8 位小数）。

StatList（属性值）
  UnitAny.pStatList = +0x5C
  StatList / StatListEx（flag@+0x10 bit31 = Ex）
     +0x24 Stat sBaseStat {pStat@+0x24, wStats@+0x28}
     +0x48 Stat sFullStat {pStat@+0x48, wStats@+0x4C}   （仅 Ex）
     +0x50 Stat sModStat  {pStat@+0x50, wStats@+0x54}   （仅 Ex）
     StatEx = 8 字节 {WORD wParam; WORD wStatId; DWORD dwStatValue}

ItemData 词缀字段（见 structs / hackmap d2structs.h）
  +0x32 wRarePrefix  +0x34 wRareSuffix  +0x36 wAutoPrefix
  +0x38 wMagicPrefix[3]  +0x3E wMagicSuffix[3]
  +0x18 dwItemFlags（RUNEWORD=0x04000000 / SOCKETED=0x800 / ETHEREAL=0x400000）
  ★ 符文之语物品（quality=2 + RUNEWORD 标志）的 wMagicPrefix[0] 存的是**符文之语名的 locale id**
    （实测 20525→'白天 Daylight'、20635→'精神 Spirit'、20651→'时间 Time'），**不是词缀索引**。

⚠️ **仍未辨明**（代码里不猜，按原始值打印）：
  · staffmod（法杖/魔杖/头颅上的职业技能）不单独存字段，只能从 StatList 看出；
  · wAutoPrefix 的"第三段"身份见上（推断 automagic，待确认）。

★ 词缀表**只在游戏内可读**：2026-09-20 实测，离开游戏（状态码 0）后该块被清零
  ⇒ 表不可读时显式告警，**绝不静默返回空**。

全程只读：仅 read_bytes / read_uint，绝不写内存。
"""

from __future__ import annotations

import struct

from d2h.acquire import offsets as off
from d2h.acquire import process as proc

# ---- 地址常量（1.13c 绝对地址，用真实模块基址换算）----
GPT_ABS = 0x6FDEFB94
DATA_TABLES_ABS = 0x6FDE9E1C

# ---- gpt 描述区槽位 ----
GPT_N_ITEMS_TXT = 0x00
GPT_ITEMTXT_CHUNKS = (0x08, 0x10, 0x18, 0x20)   # {ptr,count} 对
GPT_SLOT_UNKNOWN_20 = 0x20
GPT_SLOT_EMPTY_28 = 0x28
GPT_MAGIC_SUFFIX = 0x2C        # ★ 0x90 块基址（三段共用这一个基址）
GPT_MAGIC_PREFIX = 0x30        # = 块基址 + 747 行（实测）
GPT_AUTO_AFFIX = 0x34          # = 块基址 + 1416 行（实测；身份推断=automagic）
GPT_N_AUTO_AFFIX = 0x38        # 71
GPT_GEMS = 0x3C
GPT_N_GEMS = 0x40
GPT_RUNES = 0x44
GPT_N_RUNES = 0x48
GPT_RARE_WORDS = 0x50          # ★ 0x48 块基址（稀有名字词）
GPT_RARE_WORDS_PREFIX = 0x54   # = 块基址 + 155 行（实测）

AFFIX_REC = 0x90
AFFIX_NAME_INTERNAL = 0x00
AFFIX_NAME_LOCALE = 0x20
AFFIX_GROUP = 0x24    # 推断（同组=同词缀不同档）
AFFIX_MIN = 0x2C      # 推断（mod1 下限）
AFFIX_MAX = 0x30      # 推断（mod1 上限）

RARE_WORD_REC = 0x48
RARE_WORD_NAME = 0x26
RARE_WORD_LOCALE = 0x0C

# ---- 0x90 块分段（实测）----
MAGIC_SUFFIX_ROWS = 747    # 值 1..747     → 行 0..746
MAGIC_PREFIX_ROWS = 669    # 值 748..1416  → 行 747..1415
AUTO_ROWS_FALLBACK = 71    # 值 1417..1487 → 行 1416..1486（行数优先读 gpt+0x38）

# ---- 0x48 块分段（实测）----
RARE_WORD_SUFFIX_ROWS = 155   # 值 1..155     → 行 0..154
RARE_WORD_PREFIX_ROWS = 46    # 值 156..201   → 行 155..200

STATCOST_SLOT = 0xBCC     # 相对 DataTables
STATCOST_REC = 0x144
STATCOST_DESCFUNC = 0x36
STATCOST_DESCVAL = 0x37
STATCOST_STRPOS = 0x38
STATCOST_DIVIDE = 0x0C    # ⚠️ hackmap 标 dwDivide，本机 1.13c **不成立**，仅作原始值打印
STATCOST_MULTIPLY = 0x10  # ⚠️ 同上
STATCOST_ADD = 0x14       # ⚠️ 同上（原样打印，不参与折算）

# ★ "没有描述"的哨兵：ItemStatCost.wDescStrpos 指向它时游戏不显示这一条。
#   实测 locale 5382 -> '一股邪恶力量'（游戏对无名单位的默认串），stat 4/5/6/8/10/160 等都指它。
NO_DESC_LOCALE = 5382

# hp/mana 家族：D2 惯例存 8 位小数（÷256）。**未实机验证**，只作为候选值打印。
HP_MANA_STATS = frozenset({6, 7, 8, 9, 10, 11})

# StatList 三个属性组：(pStat 偏移, wStats 偏移)
STAT_GROUPS = {
    "base": (0x24, 0x28),
    "full": (0x48, 0x4C),
    "mod": (0x50, 0x54),
}

# 词缀记录读不到名字时的容错上限（防止 idx 越界读到别的分配块）
AFFIX_IDX_MAX = 4000

ITEM_FLAGS = {
    "IDENTIFIED": 0x00000010,
    "BROKEN": 0x00000100,
    "SOCKETED": 0x00000800,
    "INSTORE": 0x00002000,
    "NAMED": 0x00008000,
    "EAR": 0x00010000,
    "COMPACTSAVE": 0x00200000,
    "ETHEREAL": 0x00400000,
    "RUNEWORD": 0x04000000,
}


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _ascii(b, cap=28) -> str:
    s = b[:cap].split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
    return "" if any(ord(c) < 32 or ord(c) > 126 for c in s) else s


class ItemProps:
    """物品词缀 / 属性解析器。取不到的表一律返回 None，绝不抛异常。"""

    def __init__(self, handle: int, bases: dict[str, int]):
        self.handle = handle
        self.bases = bases
        self.gpt: int = 0
        self.dt: int = 0
        self.isc: int = 0
        self._cn = {}          # (key, idx) -> dict | None  词缀缓存
        self._sd = {}          # stat id -> dict
        self._loc = None
        self._lt_tried = False

        b = bases.get("D2COMMON")
        if b:
            # ★ gpt 是**描述区基址本身**（不是它的内容！）
            #   0x6FDEFB94 处存的是 nItemsTxt=716，表指针从 gpt+0x04 起。
            #   曾误写成「解引用 gpt」→ self.gpt=0x2CC，所有词缀表全取不到（静默返回空）。
            self.gpt = b + (GPT_ABS - off.DLLBASE["D2COMMON"])
            self.dt = proc.read_uint(handle, b + (DATA_TABLES_ABS - off.DLLBASE["D2COMMON"]), 4) or 0
        if self.dt:
            self.isc = proc.read_uint(handle, self.dt + STATCOST_SLOT, 4) or 0

    # ---------- D2Lang 字符串表（延迟加载，避免每次构造都连） ----------
    def _lt(self):
        if not self._lt_tried:
            self._lt_tried = True
            try:
                from d2h.acquire import lang
                self._loc = lang.LocaleText(self.handle, self.bases)
            except Exception:  # noqa: BLE001
                self._loc = None
        return self._loc

    def loc(self, cid) -> str:
        lt = self._lt()
        if not lt or not cid:
            return ""
        try:
            return lt.get_clean(cid) or ""
        except Exception:  # noqa: BLE001
            return ""

    # ---------- 表访问 ----------
    def slot_ptr(self, slot: int) -> int:
        """读 gpt 里某个槽位的指针（0 = 无）。"""
        if not self.gpt:
            return 0
        return proc.read_uint(self.handle, self.gpt + slot, 4) or 0

    def slot_int(self, slot: int) -> int:
        """读 gpt 里某个槽位的整数值（计数）。"""
        if not self.gpt:
            return 0
        return proc.read_uint(self.handle, self.gpt + slot, 4) or 0

    def magic_block(self) -> int:
        """0x90 块基址（后缀/前缀/第三段共用）。"""
        return self.slot_ptr(GPT_MAGIC_SUFFIX)

    def rare_block(self) -> int:
        """0x48 块基址（稀有名字词）。"""
        return self.slot_ptr(GPT_RARE_WORDS)

    def auto_rows(self) -> int:
        n = self.slot_int(GPT_N_AUTO_AFFIX)
        return n or AUTO_ROWS_FALLBACK

    def table_layout(self) -> dict:
        """把 gpt 里与物品词缀相关的槽位一次读齐（诊断用，全部原始值）。"""
        rs = self.slot_ptr(GPT_RARE_WORDS)
        rp = self.slot_ptr(GPT_RARE_WORDS_PREFIX)
        return {
            "gpt": self.gpt,
            "n_items_txt": self.slot_int(GPT_N_ITEMS_TXT) if self.gpt else 0,
            "magic_block": self.magic_block(),
            "magic_suffix": self.magic_block(),
            "magic_prefix": self.slot_ptr(GPT_MAGIC_PREFIX),
            "magic_suffix_rows": MAGIC_SUFFIX_ROWS,
            "magic_prefix_rows": MAGIC_PREFIX_ROWS,
            "auto_affix": self.slot_ptr(GPT_AUTO_AFFIX),
            "auto_rows": self.auto_rows(),
            "rare_words": rs,
            "rare_words_prefix": rp,
            "rare_word_suffix_rows": ((rp - rs) // RARE_WORD_REC) if (rs and rp > rs) else RARE_WORD_SUFFIX_ROWS,
            "rare_word_prefix_rows": RARE_WORD_PREFIX_ROWS,
            "n_rare_words": self.slot_int(GPT_N_RUNES),
            "gems": self.slot_ptr(GPT_GEMS),
            "n_gems": self.slot_int(GPT_N_GEMS),
            "runes": self.slot_ptr(GPT_RUNES),
            "n_runes": self.slot_int(GPT_N_RUNES),
            "id_mode": "(值-1) 1 基（D2Common+0x71790 / +0x71841 实测公式）",
            "tables_readable": self.tables_readable(),
        }

    def tables_readable(self) -> bool:
        """词缀表当前是否可读（不在游戏内时整块被清零 ⇒ False）。

        ★ 2026-09-20 实测：离开游戏后该块全为 0，
          此时若不显式报出来，"解析不出词缀"会被误判成偏移写错（曾白查一轮）。
        """
        base = self.magic_block()
        if not base:
            return False
        rb = proc.read_bytes(self.handle, base, 4)
        return bool(rb) and rb != b"\x00\x00\x00\x00"

    # ---------- 词缀记录（0x90） ----------
    def record(self, addr: int) -> dict | None:
        """按地址读一条 0x90 词缀记录（名字 / locale / 组 / min-max）。"""
        rb = proc.read_bytes(self.handle, addr, 0x34)
        if not rb or len(rb) < 0x34:
            return None
        internal = _ascii(rb, 28)
        wloc = _u16(rb, AFFIX_NAME_LOCALE)
        name = self.loc(wloc)
        if not name and not internal:
            return None
        return {
            "internal": internal, "locale": wloc, "name": name, "rec_addr": addr,
            "group": _u32(rb, AFFIX_GROUP),
            "min": _u32(rb, AFFIX_MIN),
            "max": _u32(rb, AFFIX_MAX),
        }

    def row90(self, idx: int) -> dict | None:
        """0x90 块**行号 idx（0 基）**记录；idx 越界/空行返回 None。"""
        base = self.magic_block()
        if not base or not (0 <= idx < AFFIX_IDX_MAX):
            return None
        return self.record(base + idx * AFFIX_REC)

    def zone90(self, idx: int) -> str:
        if idx < MAGIC_SUFFIX_ROWS:
            return "后缀区"
        if idx < MAGIC_SUFFIX_ROWS + MAGIC_PREFIX_ROWS:
            return "前缀区"
        if idx < MAGIC_SUFFIX_ROWS + MAGIC_PREFIX_ROWS + self.auto_rows():
            return "第三段(推断:自动前缀)"
        return "越界"

    def row48(self, idx: int) -> dict | None:
        """0x48 稀有名字词块**行号 idx（0 基）**记录。"""
        base = self.rare_block()
        if not base or not (0 <= idx < AFFIX_IDX_MAX):
            return None
        rb = proc.read_bytes(self.handle, base + idx * RARE_WORD_REC, RARE_WORD_NAME + 0x16)
        if not rb or len(rb) < RARE_WORD_NAME + 6:
            return None
        internal = _ascii(rb[RARE_WORD_NAME:RARE_WORD_NAME + 0x16], 0x16)
        wloc = _u16(rb, RARE_WORD_LOCALE)
        name = self.loc(wloc)
        if not internal and not name:
            return None
        return {"internal": internal, "locale": wloc, "name": name,
                "rec_addr": base + idx * RARE_WORD_REC}

    def zone48(self, idx: int) -> str:
        n = ((self.slot_ptr(GPT_RARE_WORDS_PREFIX) - self.rare_block()) // RARE_WORD_REC
             if self.rare_block() and self.slot_ptr(GPT_RARE_WORDS_PREFIX) > self.rare_block()
             else RARE_WORD_SUFFIX_ROWS)
        if idx < n:
            return "稀有后缀词区"
        if idx < n + RARE_WORD_PREFIX_ROWS:
            return "稀有前缀词区"
        return "越界"

    # ---------- 统一的「值 -> 记录」入口（游戏公式：行 = 值-1） ----------
    def _resolve(self, kind: str, idx: int) -> dict:
        """把某个原始 id 按**游戏公式**解析成记录，并把「另一解（值 当 0 基）」也带上。

        kind: 'MagicPrefix' | 'MagicSuffix' | 'AutoPrefix' | 'RarePrefix' | 'RareSuffix'
        """
        out = {"idx": idx, "primary": None, "alt": None,
               "zone": "-", "alt_zone": "-", "mode": "1基(值-1)"}
        if not idx or idx <= 0:
            return out
        if kind in ("MagicPrefix", "MagicSuffix", "AutoPrefix"):
            out["zone"] = self.zone90(idx - 1)
            out["alt_zone"] = self.zone90(idx)
            out["primary"] = self.row90(idx - 1)
            out["alt"] = self.row90(idx)
        else:
            out["zone"] = self.zone48(idx - 1)
            out["alt_zone"] = self.zone48(idx)
            out["primary"] = self.row48(idx - 1)
            out["alt"] = self.row48(idx)
        return out

    def magic_affix(self, idx) -> dict:
        """兼容旧名：magic 词缀 id（后缀/前缀共用同一 0x90 块）。"""
        return self._resolve("MagicSuffix", idx)

    # ---------- ItemStatCost ----------
    def stat_desc(self, sid: int) -> dict:
        """返回该 stat 的描述信息 dict。

        {desc, locale, func, val, divide, multiply, add}
        desc 为空串表示游戏不显示这一条（locale 指向 NO_DESC_LOCALE 哨兵）。
        ⚠️ divide/multiply 仅作**原始值**打印，不参与折算（见模块 docstring：本机不成立）。
        """
        if sid in self._sd:
            return self._sd[sid]
        res = {"desc": "", "locale": 0, "func": 0, "val": 0,
               "divide": 1, "multiply": 1, "add": 0}
        if self.isc and isinstance(sid, int) and 0 <= sid < 4096:
            rb = proc.read_bytes(self.handle, self.isc + sid * STATCOST_REC, 0x40)
            if rb and len(rb) >= 0x3A:
                wl = _u16(rb, STATCOST_STRPOS)
                res = {
                    "desc": "" if wl == NO_DESC_LOCALE else self.loc(wl),
                    "locale": wl,
                    "func": rb[STATCOST_DESCFUNC],
                    "val": rb[STATCOST_DESCVAL],
                    "divide": _u32(rb, STATCOST_DIVIDE),
                    "multiply": _u32(rb, STATCOST_MULTIPLY),
                    "add": _u32(rb, STATCOST_ADD),
                }
        self._sd[sid] = res
        return res

    @staticmethod
    def scale(st: dict, raw: int):
        """显示值：**实机悬停文本已证 = raw 直读（系数 1）**，故不折算。

        历史坑：曾按 hackmap 的 dwDivide/dwMultiply(+0x0C/+0x10) 折算，
        得到防御 175 → 1.709 这种荒谬值（1.13c 上这两列不是显示系数）。
        """
        return raw

    @staticmethod
    def scale_alt(sid: int, raw: int):
        """未实机验证的**候选**折算：hp/mana 家族给 raw>>8（D2 惯例 8 位小数），其余 None。"""
        return (raw >> 8) if sid in HP_MANA_STATS else None

    @staticmethod
    def format_stat(desc: str, func: int, dval: int, val: int) -> str:
        """把 (模板, descFunc, descVal, 值) 拼成一行属性文本。

        ⚠️ **格式为程序推断**（descFunc 语义取自 hackmap ItemVariableProp / 社区文档），
        只用于人读；原始 (func/val/值) 一律同时打印。
        """
        if not desc:
            return ""
        if func == 0 or dval == 0:
            return desc
        if func == 1:
            return f"+{val} {desc}" if dval == 1 else f"{desc} +{val}"
        if func == 2:
            return f"{val}% {desc}"
        if func == 3:
            return f"{desc} {val}"
        if func == 4:
            return f"{desc} +{val}%"
        if func == 5:
            return f"{val}% {desc}"
        if func in (6, 7, 8, 9, 10):
            return f"{desc} {val}"
        if func in (11, 12, 13):
            return f"+{val} {desc}"
        if func == 14:
            return f"{val} {desc}"
        return f"{desc} {val}"

    # ---------- StatList ----------
    def stat_lists(self, p_unit: int, limit: int = 8) -> list[dict]:
        """遍历某单位的 StatList 链（StatList / StatListEx）。"""
        out: list[dict] = []
        cur = proc.read_uint(self.handle, p_unit + 0x5C, 4) or 0
        seen: set[int] = set()
        for _ in range(limit):
            if not cur or cur in seen:
                break
            seen.add(cur)
            hb = proc.read_bytes(self.handle, cur, 0x64)
            if not hb or len(hb) < 0x58:
                break
            flag = _u32(hb, 0x10)
            ex = bool(flag & 0x80000000)
            out.append({
                "addr": cur, "flag": flag, "ex": ex,
                "unit": _u32(hb, 0x04), "owner_type": _u32(hb, 0x08),
                "owner_id": _u32(hb, 0x0C), "state": _u32(hb, 0x14),
                "skill_no": _u32(hb, 0x1C), "skill_lvl": _u32(hb, 0x20),
                "next": _u32(hb, 0x3C), "next_ex": _u32(hb, 0x38),
                "groups": {g: (_u32(hb, po), _u16(hb, no))
                           for g, (po, no) in STAT_GROUPS.items()},
            })
            cur = _u32(hb, 0x38) if ex else _u32(hb, 0x3C)
        return out

    def iter_stats(self, p_unit: int, max_each: int = 200) -> list[dict]:
        """把所有 StatList 的三个属性组都摊平成一维列表（完整打印，不过滤）。"""
        rows: list[dict] = []
        for li, lst in enumerate(self.stat_lists(p_unit)):
            for gname, (pstat, n) in lst["groups"].items():
                if not pstat or not n:
                    continue
                n2 = min(n, max_each)
                sb = proc.read_bytes(self.handle, pstat, 8 * n2)
                if not sb:
                    continue
                for j in range(n2):
                    wp, sid, val = struct.unpack_from("<HHI", sb, j * 8)
                    st = self.stat_desc(sid)
                    rows.append({
                        "list": li, "list_addr": lst["addr"], "ex": lst["ex"],
                        "group": gname, "index": j,
                        "stat_id": sid, "param": wp, "value": val,
                        "desc": st["desc"], "desc_locale": st["locale"],
                        "desc_func": st["func"], "desc_val": st["val"],
                        "isc_div": st["divide"], "isc_mul": st["multiply"],
                        "value_show": self.scale(st, val),
                        "value_alt": self.scale_alt(sid, val),
                        "text": self.format_stat(st["desc"], st["func"], st["val"], val),
                    })
        return rows

    # ---------- 词缀（ItemData 字段 -> 表） ----------
    def affixes(self, idata: dict) -> list[dict]:
        """从 ItemData 字段解析词缀。

        每项 = {kind, slot, idx, rec, alt_rec, zone, alt_zone, mode}
        · 魔法前缀/后缀/自动前缀 → 0x90 块（值-1 取行，带区段标注）
        · 稀有前缀/后缀         → 0x48 名字词块（值-1 取行）
        符文之语物品的 wMagicPrefix[0] 不是词缀，调用方（item_affix_report）已单独处理。
        """
        out: list[dict] = []

        def add(kind, slot, res):
            out.append({"kind": kind, "slot": slot, "idx": res["idx"],
                        "rec": res["primary"], "alt_rec": res["alt"],
                        "zone": res["zone"], "alt_zone": res["alt_zone"],
                        "mode": res["mode"]})

        for i, ix in enumerate(idata.get("magic_prefix") or ()):
            add("魔法前缀", i, self._resolve("MagicPrefix", ix))
        for i, ix in enumerate(idata.get("magic_suffix") or ()):
            add("魔法后缀", i, self._resolve("MagicSuffix", ix))
        add("自动前缀", 0, self._resolve("AutoPrefix", idata.get("auto_prefix") or 0))
        add("稀有前缀(名字词)", 0, self._resolve("RarePrefix", idata.get("rare_prefix") or 0))
        add("稀有后缀(名字词)", 0, self._resolve("RareSuffix", idata.get("rare_suffix") or 0))
        return out

    def rare_name(self, idata: dict) -> dict:
        """稀有物品的**显示名**候选 = 前缀词 + 后缀词（游戏公式取行）。

        返回 {"primary": "...", "alt": "...", "words": {...}}；
        两解都打印（差 1 行），等实机悬停文本对答案定型。
        """
        rp, rs = idata.get("rare_prefix") or 0, idata.get("rare_suffix") or 0
        p1 = self._resolve("RarePrefix", rp)
        s1 = self._resolve("RareSuffix", rs)
        p2 = p1["alt"] or {}
        s2 = s1["alt"] or {}

        def join(a, b):
            w = "%s %s" % ((a or {}).get("internal") or "?", (b or {}).get("internal") or "?")
            c = " ".join(x for x in [(a or {}).get("name"), (b or {}).get("name")] if x)
            return "%s  (中文: %s)" % (w, c) if c else w

        return {
            "primary": join(p1["primary"], s1["primary"]),
            "alt": join(p2, s2),
            "words": {"prefix": p1["primary"], "suffix": s1["primary"],
                      "prefix_alt": p2, "suffix_alt": s2},
        }


# ==================== 便捷函数 ====================

def read_item_fields(handle: int, p_idata: int) -> dict:
    """一次读齐 ItemData 里与词缀有关的字段（只读 0x70 字节）。"""
    rb = proc.read_bytes(handle, p_idata, 0x70)
    if not rb or len(rb) < 0x6A:
        return {}
    return {
        "quality": _u32(rb, 0x00),
        "file_index": _u32(rb, 0x28),
        "ilvl": _u32(rb, 0x2C),
        "flags": _u32(rb, 0x18),
        "item_format": _u16(rb, 0x30),
        "rare_prefix": _u16(rb, 0x32),
        "rare_suffix": _u16(rb, 0x34),
        "auto_prefix": _u16(rb, 0x36),
        "magic_prefix": [_u16(rb, 0x38 + 2 * i) for i in range(3)],
        "magic_suffix": [_u16(rb, 0x3E + 2 * i) for i in range(3)],
        "n_location": rb[0x69],
        "n_item_location": rb[0x45],
        "n_body_location": rb[0x44],
        "owner_id": _u32(rb, 0x0C),
        "p_owner_inv": _u32(rb, 0x5C),
        "p_next_inv_item": _u32(rb, 0x64),
    }


def socket_children(handle: int, p_owner_inv: int, limit: int = 12) -> list[int]:
    """从「父物品的 UnitInventory」走出镶在它里面的宝石/符文物品指针。

    ★ 2026-09-20 实测纠正 1（起点）：走 **UnitAny+0x60（自己的 inventory）** →
    pFirstItem(+0x0C)。ItemData+0x5C 对**未打孔**物品指向持有者（玩家背包），
    直接走会拿到无关物品 ⇒ 调用方必须按 SOCKETED 标志门控。

    ★★ 2026-09-20 实测纠正 2（**静默漏数**，本条是坑）：兄弟链必须先走
    **ItemData+0x64 = pNextInvItem**；`UnitAny+0xE8 (pListNext)` 对**镶入物恒为 0**
    （镶入物不在房间单位链里）。实测 4 孔符文之语「统治者大盾 Spirit」：
      · 只沿 +0xE8 → 得到 1 个（**不报错、静默少报**，最毒的一种错）
      · 沿 +0x64 → 得到全部 4 个（txt=616/619/618/620，全是 UNIT=TYPE_ITEM）
    手法：**两条都试，+0x64 优先，为 0 才退 +0xE8**，配合 seen 去重。
    """
    out: list[int] = []
    if not p_owner_inv:
        return out
    node = proc.read_uint(handle, p_owner_inv + 0x0C, 4) or 0
    seen: set[int] = set()
    while node and node not in seen and len(out) < limit:
        seen.add(node)
        if (proc.read_uint(handle, node + 0x00, 4) or 0) == 4:   # ITEM
            out.append(node)
        pdata = proc.read_uint(handle, node + 0x14, 4) or 0
        nxt = (proc.read_uint(handle, pdata + 0x64, 4) or 0) if pdata else 0
        if not nxt:
            nxt = proc.read_uint(handle, node + 0xE8, 4) or 0
        node = nxt
    return out


def item_affix_report(handle: int, bases: dict[str, int], p_item: int) -> dict:
    """给定物品 UnitAny 指针，返回词缀 + 属性完整报告（dict）。

    ⚠️ 只读；任何一步失败都降级为空值，绝不抛异常。
    """
    ip = ItemProps(handle, bases)
    head = proc.read_bytes(handle, p_item, 0x18)
    if not head or len(head) < 0x18:
        return {"ok": False, "reason": f"读不到 UnitAny @0x{p_item:X}"}
    utype, txtno, _mp, uid = struct.unpack_from("<IIII", head, 0)
    pdata = _u32(head, 0x14)
    rep: dict = {
        "ok": True, "ptr": p_item, "unit_type": utype,
        "txt_file_no": txtno, "unit_id": uid, "p_item_data": pdata,
        "layout": ip.table_layout(),
        "plen": ip,
    }
    if not pdata:
        rep["ok"] = False
        rep["reason"] = "ItemData 为空"
        return rep
    f = read_item_fields(handle, pdata)
    rep["fields"] = f
    rep["flag_names"] = [k for k, v in ITEM_FLAGS.items() if f.get("flags", 0) & v]
    # ★ 符文之语物品：wMagicPrefix[0] 是**符文之语名 locale id**，不是词缀索引（实测 20525/20635/20651）
    #    ⇒ 单独当"符文之语名"报出来，**同时保留原始 id**（规范 §12：不裁字段），
    #      并且不要把它丢进词缀解析（否则必然报"越界读不到名字"）。
    rep["runeword"] = None
    if f.get("flags", 0) & ITEM_FLAGS["RUNEWORD"] and f.get("magic_prefix"):
        rid = f["magic_prefix"][0]
        rep["runeword"] = {"locale": rid, "name": ip.loc(rid)}
        f = dict(f)
        f["magic_prefix"] = [0] + list(f["magic_prefix"][1:])
        f["magic_prefix_raw"] = list(read_item_fields(handle, pdata).get("magic_prefix") or ())
        rep["fields"] = f
    rep["affixes"] = ip.affixes(f)
    rep["rare_name"] = ip.rare_name(f)
    rep["stats"] = ip.iter_stats(p_item)
    # ⚠️ pOwnerInventory(+0x5C) 对**未打孔**物品指向持有者（玩家）的 inventory，
    #    其 pFirstItem 是背包里第一件物品 —— 直接走会得到一件无关物品。
    #    只有 SOCKETED 物品才当"父物品的 inventory"用。
    if f.get("flags", 0) & ITEM_FLAGS["SOCKETED"]:
        # 优先用 UnitAny+0x60（自己的 inventory）；退回 ItemData+0x5C（实测两者一致时才用）
        rep["sockets"] = socket_children(handle, proc.read_uint(handle, p_item + 0x60, 4) or
                                         f.get("p_owner_inv", 0))
    else:
        rep["sockets"] = []
    return rep
