"""单位命名（只读）：把任意 UnitAny 解析成可读名称。

依据参考项目 d2structs.h（2026-09-20 落地）：
    0 玩家 : PlayerData +0x00  szName[16]                     ascii 直接读
    1 怪物/NPC : MonsterData +0x00 -> MonsterTxt*
                -> wLocaleTxtNo(+0x06) -> D2Lang 内存字符串表
    2 物件 : ObjectData +0x00 -> ObjectTxt*
                -> wszName[64](+0x40)                         宽字符直接读
    4 物品 : UnitAny.dwTxtFileNo -> ItemTxt(+0xF4 wLocaleTxtNo)
                -> D2Lang 内存字符串表（.vcb 仅兜底）

全程只读：只用 read_bytes / read_uint，绝不调用游戏函数（GetObjectTxt 等一律不碰）。
"""

from __future__ import annotations

from d2h.acquire import lang
from d2h.acquire import process as proc

# 参考项目 d2structs.h 权威偏移
MONSTER_TXT_LOCALE = 0x06      # MonsterTxt.wLocaleTxtNo
OBJECT_TXT_SZNAME = 0x00       # ObjectTxt.szName[64]   ascii（多为内部 token）
OBJECT_TXT_WSZNAME = 0x40      # ObjectTxt.wszName[64]  wchar_t = 显示名
OBJECT_NAME_LEN = 64           # 读取上限（字符）
UNIT_P_UNITDATA = 0x14         # UnitAny.pUnitData


class UnitNamer:
    """把 UnitAny 指针解析成名称。字符串表只构造一次（hover 轮询复用）。"""

    def __init__(self, handle: int, bases: dict[str, int]):
        self.handle = handle
        self.bases = bases
        self._lt: lang.LocaleText | None = None
        self._itab = None
        self._itab_done = False
        self._qt = None
        self._qt_done = False
        self._props = None
        self._props_done = False

    @property
    def qt(self):
        """暗金/套装名字表（懒构造）。"""
        if not self._qt_done:
            self._qt_done = True
            try:
                from d2h.acquire import items as _items

                self._qt = _items.QualityNameTables(self.handle, self.bases)
            except Exception:  # noqa: BLE001
                self._qt = None
        return self._qt

    @property
    def lt(self) -> lang.LocaleText:
        if self._lt is None:
            self._lt = lang.LocaleText(self.handle, self.bases)
        return self._lt

    @property
    def props(self):
        """物品词缀 / 完整名解析器（懒构造；失败返回 None 而不是反复重试）。

        2026-09-20 加：hover 指向物品时要拼完整显示名，本属性让解析器
        在整个监听循环里复用（词缀表/字符串表都不重复定位）。
        """
        if not self._props_done:
            self._props_done = True
            try:
                from d2h.acquire import itemprops as _ip

                self._props = _ip.ItemProps(self.handle, self.bases)
            except Exception:  # noqa: BLE001
                self._props = None
        return self._props

    @property
    def itab(self):
        """ItemTxt 现表（懒构造；失败返回 None 而不是反复重试）。"""
        if not self._itab_done:
            self._itab_done = True
            try:
                from d2h.acquire import items as _items

                self._itab = _items.ItemTextTable(self.handle, self.bases)
            except Exception:  # noqa: BLE001  命名失败不该让主流程崩
                self._itab = None
        return self._itab

    def _from_txt(self, locale: int | None) -> str:
        if locale is None or not self.lt.ready():
            return ""
        return self.lt.get_clean(locale)

    def name(self, p: int, unit_type: int | None = None,
             txt: int | None = None) -> tuple[str, str]:
        """返回 (名称, 来源)。解析不出返回 ('', '')。"""
        if not p:
            return "", ""
        if unit_type is None:
            unit_type = proc.read_uint(self.handle, p + 0x00, 4)
        if unit_type is None:
            return "", ""
        if txt is None:
            txt = proc.read_uint(self.handle, p + 0x04, 4)
        pd = proc.read_uint(self.handle, p + UNIT_P_UNITDATA, 4)

        if unit_type == 0:  # 玩家
            if pd:
                raw = proc.read_bytes(self.handle, pd, 16) or b""
                nm = raw.split(b"\x00", 1)[0].decode("ascii", "ignore")
                if nm:
                    return nm, "PlayerData"
            return "", ""

        if unit_type == 1:  # 怪物 / NPC
            if pd:
                mtxt = proc.read_uint(self.handle, pd + 0x00, 4)
                if mtxt:
                    loc = proc.read_uint(self.handle, mtxt + MONSTER_TXT_LOCALE, 2)
                    nm = self._from_txt(loc)
                    if nm:
                        return nm, "MonsterTxt+内存字符串表"
            return "", ""

        if unit_type == 2:  # 物件（箱子/门/神龛/传送点…）
            if pd:
                otxt = proc.read_uint(self.handle, pd + 0x00, 4)
                if otxt:
                    nm = lang.strip_color(
                        lang.read_wstring(self.handle,
                                          otxt + OBJECT_TXT_WSZNAME, OBJECT_NAME_LEN)
                    )
                    if nm:
                        return nm, "ObjectTxt.wszName"
                    raw = proc.read_bytes(self.handle, otxt + OBJECT_TXT_SZNAME, 64) or b""
                    nm = raw.split(b"\x00", 1)[0].decode("ascii", "ignore")
                    if nm:
                        return nm, "ObjectTxt.szName(内部名)"
            return "", ""

        if unit_type == 4:  # 物品
            if txt is None:
                return "", ""
            tab = self.itab
            rec = tab.read(txt) if (tab is not None and tab.ptr) else None
            # 暗金(7)/套装(5) 走 UniqueItems/SetItems 表，索引 = ItemData.dwFileIndex
            qn = None
            if pd:
                qual = proc.read_uint(self.handle, pd + 0x00, 4)
                fidx = proc.read_uint(self.handle, pd + 0x28, 4)
                if self.qt is not None:
                    qn = self.qt.locale(qual or 0, fidx)
            if qn:
                loc, tag = qn
                nm = self._from_txt(loc)
                if nm:
                    return nm, f"{tag}(内存字符串表)"
            if rec:
                nm = self._from_txt(rec.get("locale"))
                if nm:
                    return nm, "ItemTxt+内存字符串表"
                code = rec.get("code") or ""
                if code:
                    try:
                        from d2h.acquire import items as _items

                        nm = _items.code_to_name(code)
                    except Exception:  # noqa: BLE001
                        nm = ""
                    if nm:
                        return nm, "vcb(兜底)"
                    return code, "物品代码"
            return "", ""

        return "", ""


def unit_name(handle: int, bases: dict[str, int], p: int,
              unit_type: int | None = None, txt: int | None = None) -> tuple[str, str]:
    """一次性命名（不复用字符串表时用这个）。"""
    return UnitNamer(handle, bases).name(p, unit_type, txt)
