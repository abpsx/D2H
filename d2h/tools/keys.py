# -*- coding: utf-8 -*-
"""向游戏窗口投递按键（PostMessage，不写内存、不需前台焦点）。

用途：开发期自动化验证——发键切换 UI 面板，再用只读采集核对标记。

注意：D2 是否响应该方式取决于其消息循环；实测 1.13c 对
WM_KEYDOWN/WM_KEYUP 的 PostMessage 有效（I/q/c/t 均可切换面板）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MAPVK_VK_TO_VSC = 0

# 常用键（D2 默认：I 背包 / q 任务 / c 状态 / t 技能树 / ESC 关闭 UI 或打开设置）
KEYS: dict[str, int] = {
    "i": 0x49,
    "q": 0x51,
    "c": 0x43,
    "t": 0x54,
    "esc": 0x1B,
    "enter": 0x0D,
    "space": 0x20,
}


def find_main_hwnd(pid: int) -> int | None:
    """按 PID 找到可见主窗口句柄。"""
    user32 = ctypes.windll.user32
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowThreadProcessId.restype = wt.DWORD
    GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    IsWindowVisible = user32.IsWindowVisible
    found: list[int] = []

    def cb(hwnd: int, _lparam: int) -> bool:
        p = wt.DWORD(0)
        GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(p))
        if p.value == pid and IsWindowVisible(wt.HWND(hwnd)):
            found.append(int(hwnd))
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


def send_key(hwnd: int, vk: int, hold: float = 0.08) -> bool:
    """向窗口投递一次按下+抬起。"""
    u = ctypes.windll.user32
    sc = u.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    down = 1 | (sc << 16)
    up = 1 | (sc << 16) | (1 << 30) | (1 << 31)
    r1 = u.PostMessageW(wt.HWND(hwnd), WM_KEYDOWN, vk, down)
    time.sleep(hold)
    r2 = u.PostMessageW(wt.HWND(hwnd), WM_KEYUP, vk, up)
    return bool(r1 and r2)


def resolve_key(name: str) -> int | None:
    """把 'i' / 'ESC' / '0x49' 解析成虚拟键码。"""
    n = name.strip().lower()
    if n in KEYS:
        return KEYS[n]
    if len(n) == 1:
        return ord(n.upper())
    if n.startswith("0x"):
        try:
            return int(n, 16)
        except ValueError:
            return None
    return None
