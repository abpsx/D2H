#!/usr/bin/env python3
"""D2H 统一入口（见规范 §15）。

所有 D2H 的 Python 执行都经此入口；由 run.bat 唤起。
每次运行：控制台(stdout) + logs/d2h_<时间戳>.txt 双写日志。
子命令：info / snap / list / parse。

硬性约束：本入口只触发"只读"采集，绝不写游戏内存。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"

# 无论以何种方式调用（脚本路径/模块/cwd 不同），都把项目根加入 sys.path，
# 保证 `import d2h` 始终可用（见规范 §15 统一入口）。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGGER = logging.getLogger("d2h")


def setup_logging() -> Path:
    """初始化双日志（控制台 + txt），返回日志文件路径。"""
    LOGS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = LOGS / f"d2h_{ts}.txt"
    LOGGER.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(module)s: %(message)s", "%H:%M:%S"
    )
    sh = logging.StreamHandler(sys.stdout)  # bat 可见（向 bat 输出执行过程）
    sh.setLevel(logging.INFO)
    fh = logging.FileHandler(logfile, encoding="utf-8")  # 落盘存档
    fh.setLevel(logging.DEBUG)
    sh.setFormatter(fmt)
    fh.setFormatter(fmt)
    LOGGER.addHandler(sh)
    LOGGER.addHandler(fh)
    LOGGER.info("D2H 启动 | 日志文件: %s", logfile)
    return logfile


def cmd_info(args) -> int:
    LOGGER.info("=== D2H 项目信息 ===")
    LOGGER.info("定位: D2H = d2hackmap 的 Python 观测型重写")
    LOGGER.info("目标版本: 1.13c")
    LOGGER.info("默认目标进程: D2loader.exe (loader) | 备选: game.exe")
    LOGGER.info("内存约束: 只读 / 禁止写入 / 允许快照")
    LOGGER.info("运行平台: Windows | 入口: d2h/cli.py (run.bat 唤起)")
    LOGGER.info("子命令: info | find [--target] | snap [--target] | state [--target] | list | parse <快照名>")
    LOGGER.info("无游戏时 info/find/list/parse 可离线运行；snap 需游戏在线")
    return 0


def cmd_snap(args) -> int:
    from d2h.acquire import process as proc
    from d2h.snapshot import store

    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        LOGGER.warning("未检测到 %s 进程（游戏未运行？）。snap 需要游戏在线，已跳过。", exe)
        LOGGER.warning("提示: 无游戏时可运行 `info` / `list` / `parse` / `find` 进行离线开发。")
        return 1
    LOGGER.info("找到 %s, PID=%s", exe, pid)
    try:
        handle = proc.open_readonly(pid)
    except OSError as e:
        LOGGER.error("打开进程失败: %s", e)
        return 1
    try:
        name, meta = store.capture(handle, pid, name=args.name, module_name=exe)
    finally:
        proc.close(handle)
    LOGGER.info("快照完成: snapshots/%s", name)
    LOGGER.info(
        "  模块基址=0x%x 大小=%s 字节 已转储=%s",
        meta.get("module_base") or 0,
        meta.get("module_size"),
        meta.get("module_dumped"),
    )
    LOGGER.info("  可读区域数=%s", meta.get("region_count"))
    LOGGER.info("后续可离线: python d2h/cli.py parse %s", name)
    return 0


def cmd_list(args) -> int:
    from d2h.snapshot import store

    snaps = store.list_snapshots()
    if not snaps:
        LOGGER.info("暂无快照。运行 `snap` 对游戏拍一张。")
        return 0
    LOGGER.info("=== 快照列表 (%s) ===", len(snaps))
    for s in snaps:
        LOGGER.info(
            "  %s | 版本=%s pid=%s 区域数=%s 模块=%s字节",
            s.get("_name"),
            s.get("target_version"),
            s.get("pid"),
            s.get("region_count"),
            s.get("module_bytes"),
        )
    return 0


def cmd_state(args) -> int:
    """读取游戏状态（仅只读）：InGame / GameInfo / 本地玩家 / 背包物品枚举。"""
    from d2h.acquire import process as proc
    from d2h.acquire import offsets as off
    from d2h.acquire import game as gm

    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        msg = f"process not found: {exe}"
        LOGGER.error("✗ %s", msg)
        print(msg)
        return 1
    LOGGER.info("找到 %s, PID=%s", exe, pid)
    try:
        handle = proc.open_readonly(pid)
    except OSError as e:
        LOGGER.error("打开进程失败: %s", e)
        return 1
    try:
        bases = off.collect_module_bases(handle)
        LOGGER.info("已加载模块基址: %s", ", ".join(f"{k}=0x{v:X}" for k, v in bases.items()))
        if "D2CLIENT" not in bases:
            LOGGER.error("未找到 D2Client.dll，无法解析游戏状态（确认游戏已进游戏界面？）")
            return 1
        state = gm.read_state(handle, bases)
    finally:
        proc.close(handle)

    # 控制台直接打印结构化结果（bat 可见）
    print("=== D2H 游戏状态 (只读) ===")
    print(f"  InGame       : {state.get('in_game')}")
    print(f"  AutomapOn    : {state.get('automap_on')}")
    print(f"  CharName     : {state.get('char_name')}")
    print(f"  PlayerName   : {state.get('player_name')}")
    print(f"  GameName     : {state.get('game_name')}")
    print(f"  Realm        : {state.get('realm')}")
    print(f"  Account      : {state.get('account')}")
    print(f"  GameMode     : 0x{state.get('game_mode', 0) or 0:02X}")
    print(f"  PlayerUnitId : {state.get('player_unit_id')}")
    print(f"  Position     : ({state.get('pos_x')}, {state.get('pos_y')})")
    print(f"  InvItems     : {state.get('inventory_count')}")
    for i, it in enumerate(state.get("inventory_sample", [])):
        print(
            f"    [{i}] type={it['type']} quality={it['quality']} "
            f"ilvl={it['ilvl']} loc={it['location']} body={it['body']} "
            f"flags=0x{it['flags']:X}"
        )
    # 同时写入日志（落盘）
    LOGGER.info("状态读取完成: %s", {k: v for k, v in state.items() if k != "inventory_sample"})
    LOGGER.info("背包物品(样本): %s", state.get("inventory_sample"))
    return 0


def cmd_find(args) -> int:
    """查找游戏进程 PID（默认目标 D2loader.exe）。

    找到: 返回 0 并打印 "game PID: <pid> (target: <exe>)"。
    不存在: 返回 1 并打印 "process not found: <exe>"。
    """
    from d2h.acquire import process as proc

    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        msg = f"process not found: {exe}"
        LOGGER.error("✗ %s", msg)
        print(msg)  # 直接打印，确保 bat 控制台可见（不受日志级别影响）
        return 1
    msg = f"game PID: {pid}  (target: {exe})"
    LOGGER.info("✓ 找到 %s, PID=%s", exe, pid)
    print(msg)
    return 0


def cmd_parse(args) -> int:
    from d2h.snapshot import store

    meta = store.load(args.name)
    if meta is None:
        LOGGER.error("找不到快照: %s (用 `list` 查看可用快照)", args.name)
        return 1
    LOGGER.info("=== 快照 %s ===", args.name)
    LOGGER.info("  目标版本: %s", meta.get("target_version"))
    LOGGER.info("  采集时间: %s", meta.get("captured_at"))
    LOGGER.info("  PID: %s", meta.get("pid"))
    LOGGER.info("  模块基址: 0x%x", meta.get("module_base") or 0)
    LOGGER.info(
        "  模块大小: %s 字节 (已转储=%s)",
        meta.get("module_size"),
        meta.get("module_dumped"),
    )
    LOGGER.info("  可读区域数: %s", meta.get("region_count"))
    LOGGER.info("（完整解析将在 M2/M4/M5 接入；当前仅展示元数据）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="d2h", description="D2H 统一入口（只读观测工具）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="项目/约束/版本信息")
    fp = sub.add_parser("find", help="查找游戏进程 PID（默认 D2loader.exe）")
    fp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    sp = sub.add_parser("snap", help="对游戏拍快照（需游戏在线）")
    sp.add_argument("--name", help="快照名（默认 snap_<时间戳>）")
    sp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    stp = sub.add_parser("state", help="读取游戏状态（InGame/GameInfo/玩家/背包，需游戏在线）")
    stp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    sub.add_parser("list", help="列出本地快照")
    pp = sub.add_parser("parse", help="离线解析快照摘要")
    pp.add_argument("name", help="快照名")
    return p


def process_targets() -> dict[str, str]:
    """延迟导入，避免顶层循环依赖；返回 TARGET_TYPES 的键集合。"""
    from d2h.acquire import process as proc

    return proc.TARGET_TYPES


def main(argv=None) -> int:
    logfile = setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "info":
            return cmd_info(args)
        if args.cmd == "find":
            return cmd_find(args)
        if args.cmd == "snap":
            return cmd_snap(args)
        if args.cmd == "state":
            return cmd_state(args)
        if args.cmd == "list":
            return cmd_list(args)
        if args.cmd == "parse":
            return cmd_parse(args)
        return 0
    except Exception as e:  # 顶层兜底，友好退出，不吐堆栈给用户
        LOGGER.exception("执行失败: %s", e)
        return 2
    finally:
        LOGGER.info("本次日志已存档: %s", logfile)


if __name__ == "__main__":
    sys.exit(main())
