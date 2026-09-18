"""采集层 - 游戏进程只读访问（Windows）。

硬性约束（见规范 §2.1 / §5.1）：
- 仅以 PROCESS_VM_READ | PROCESS_QUERY_INFORMATION 打开进程，从权限层面杜绝写入。
- 本模块**不提供任何写内存接口**；一旦出现 WriteProcessMemory / write_* 等符号即违背 MemoryGuard。

全部基于标准库 ctypes，无第三方依赖。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

kernel32 = ctypes.windll.kernel32

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

TH32CS_SNAPPROCESS = 0x00000002
MEM_COMMIT = 0x1000

# ---- ctypes 原型声明 ----
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE

kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL

kernel32.ReadProcessMemory.argtypes = [
    wt.HANDLE,
    wt.LPCVOID,
    wt.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = wt.BOOL

kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE

kernel32.Process32First.argtypes = [wt.HANDLE, ctypes.c_void_p]
kernel32.Process32First.restype = wt.BOOL
kernel32.Process32Next.argtypes = [wt.HANDLE, ctypes.c_void_p]
kernel32.Process32Next.restype = wt.BOOL

kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, wt.LPCVOID, ctypes.c_void_p, ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t

INVALID_HANDLE_VALUE = -1

# 目标进程类型 -> 可执行文件名（见规范 §2.1 / 用户指定）。
# 默认 "loader" = D2loader.exe（1.13c 经 loader 启动时的实际进程；
# game.exe 作为模块加载在该进程内，可由 get_module_info 取基址）。
TARGET_TYPES: dict[str, str] = {
    "loader": "D2loader.exe",
    "game": "game.exe",
}


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


def find_pid(name: str = "game.exe") -> int | None:
    """按进程名（不区分大小写）查找首个匹配 PID。"""
    h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not h_snap or h_snap == INVALID_HANDLE_VALUE:
        return None
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(h_snap, ctypes.byref(pe)):
            return None
        target = name.lower()
        while True:
            exe = pe.szExeFile  # ctypes 对 c_char*260 返回 bytes
            if exe.decode("ascii", "ignore").lower() == target:
                return pe.th32ProcessID
            if not kernel32.Process32Next(h_snap, ctypes.byref(pe)):
                break
        return None
    finally:
        kernel32.CloseHandle(h_snap)


def find_target_pid(target_key: str = "loader") -> tuple[str, int | None]:
    """按目标类型键查找 PID。

    返回 (exe_name, pid_or_None)。target_key 既可以是 TARGET_TYPES 的键
    （loader/game），也可以是原始可执行文件名（如 "D2loader.exe"）。
    """
    exe = TARGET_TYPES.get(target_key, target_key)
    return exe, find_pid(exe)


def open_readonly(pid: int) -> int:
    """以只读权限打开进程；失败抛 OSError。"""
    h = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        raise OSError(f"OpenProcess({pid}) 失败，可能权限不足或进程已退出")
    return h


def close(handle: int) -> None:
    kernel32.CloseHandle(handle)


def read_bytes(handle: int, address: int, size: int) -> bytes | None:
    """读取进程内存；越界/失败返回 None（不抛异常，符合规范 §5.2）。"""
    if size <= 0:
        return b""
    buf = ctypes.create_string_buffer(size)
    n = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(
        handle, ctypes.c_void_p(address), buf, size, ctypes.byref(n)
    )
    if not ok:
        return None
    return buf.raw[: n.value]


def read_uint(handle: int, address: int, width: int = 4) -> int | None:
    """读取无符号整数（小端）；width ∈ {1,2,4,8}。"""
    if width not in (1, 2, 4, 8):
        return None
    data = read_bytes(handle, address, width)
    if data is None:
        return None
    return int.from_bytes(data, "little")


def get_module_info(handle: int, module_name: str = "game.exe"):
    """返回 (base_address, size_of_image)，找不到返回 None。"""
    psm = ctypes.windll.psapi
    psm.EnumProcessModules.argtypes = [
        wt.HANDLE,
        ctypes.POINTER(wt.HMODULE),
        wt.DWORD,
        ctypes.POINTER(wt.DWORD),
    ]
    psm.EnumProcessModules.restype = wt.BOOL
    psm.GetModuleInformation.argtypes = [wt.HANDLE, wt.HMODULE, ctypes.c_void_p, wt.DWORD]
    psm.GetModuleInformation.restype = wt.BOOL
    psm.GetModuleFileNameExW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]
    psm.GetModuleFileNameExW.restype = wt.DWORD

    max_mods = 1024
    modules = (wt.HMODULE * max_mods)()
    needed = wt.DWORD(0)
    if not psm.EnumProcessModules(handle, modules, ctypes.sizeof(modules), ctypes.byref(needed)):
        return None
    count = needed.value // ctypes.sizeof(wt.HMODULE)

    class MODULEINFO(ctypes.Structure):
        _fields_ = [
            ("lpBaseOfDll", ctypes.c_void_p),
            ("SizeOfImage", wt.DWORD),
            ("EntryPoint", ctypes.c_void_p),
        ]

    target = module_name.lower()
    for i in range(count):
        mi = MODULEINFO()
        if not psm.GetModuleInformation(handle, modules[i], ctypes.byref(mi), ctypes.sizeof(mi)):
            continue
        name_buf = ctypes.create_unicode_buffer(260)
        psm.GetModuleFileNameExW(handle, modules[i], name_buf, 260)
        if name_buf.value.lower().endswith(target):
            return (int(mi.lpBaseOfDll or 0), int(mi.SizeOfImage))
    return None


# 可读保护位（只取能读的，避开不可访问区域）
_READABLE = {0x02, 0x04, 0x06, 0x0A, 0x20, 0x40, 0x80}


def enum_regions(handle: int, max_regions: int = 200000):
    """枚举已提交且可读的内存区域，返回 [(base, size), ...]。"""
    regions: list[tuple[int, int]] = []
    addr = 0
    user_limit = 1 << 47  # 用户态地址上界，避免踏入内核区
    while addr < user_limit:
        mbi = MEMORY_BASIC_INFORMATION()
        r = kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
        )
        if r == 0:
            break
        if mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in _READABLE:
            regions.append((int(mbi.BaseAddress or 0), int(mbi.RegionSize)))
        base = int(mbi.BaseAddress or 0)
        size = int(mbi.RegionSize)
        if size == 0:
            break
        addr = base + size
        if len(regions) >= max_regions:
            break
    return regions
