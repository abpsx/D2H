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
    LOGGER.info("子命令: info | find [--target] | snap [--target] | state [--target] | items [--target] | list | parse <快照名>")
    LOGGER.info("无游戏时 info/find/list/parse 可离线运行；snap 需游戏在线")
    return 0


def cmd_snap(args) -> int:
    from d2h.acquire import process as proc
    from d2h.acquire import offsets as off
    from d2h.acquire import game as gm
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
        bases = off.collect_module_bases(handle)
        state_code = gm.read_game_state(handle, bases)
        _, desc = gm.classify_state(state_code)
        LOGGER.info("采集瞬间状态码: %s (%s)", state_code, desc)
        name, meta = store.capture(
            handle, pid, name=args.name, module_name=exe,
            label=args.label, state_code=state_code, module_bases=bases,
        )
    finally:
        proc.close(handle)
    LOGGER.info("快照完成: snapshots/%s  标签=%s", name, args.label or "(无)")
    LOGGER.info("  状态码 state_code=%s", meta.get("state_code"))
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


def cmd_items(args) -> int:
    """判断是否在游戏中；若在则生成「当前游戏物品清单.md」（只读）。

    状态码（约定）: 2000=未在游戏 / 2100=在游戏但玩家单位不可读 / 3000=已生成清单。
    同时输出 game_mode（GameInfo+0x1EB），在线时约 3936（3xxx 区间）。
    """
    from d2h.acquire import process as proc
    from d2h.acquire import offsets as off
    from d2h.acquire import game as gm
    from d2h.acquire import items as itm

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
            LOGGER.error("未找到 D2Client.dll，无法解析（确认游戏已进游戏界面？）")
            return 1
        status = gm.in_game_status(handle, bases)
        gm_mode = status.get("game_mode")
        if not status["in_game"]:
            code = 2000
            print(f"STATUS: {code}  (未在游戏中)  game_mode={gm_mode}")
            LOGGER.info("STATUS %s: 未在游戏中 (game_mode=%s)", code, gm_mode)
            return 1
        if status["status"] == 2100:
            code = 2100
            print(f"STATUS: {code}  (在游戏但玩家单位不可读)  game_mode={gm_mode}")
            LOGGER.warning("STATUS %s: 在游戏但玩家单位不可读", code)
            return 1

        # 在游戏中 -> 生成清单
        state = gm.read_state(handle, bases)
        items = itm.named_inventory(handle, bases)
        meta = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "char_name": state.get("char_name") or state.get("player_name") or "?",
            "class_name": "?",
            "game_name": state.get("game_name") or "?",
            "realm": state.get("realm") or "?",
            "status": 3000,
            "status_desc": f"在游戏中 game_mode={gm_mode}",
        }
        md = itm.render_markdown(items, meta)
        out_path = ROOT / "当前游戏物品清单.md"
        out_path.write_text(md, encoding="utf-8")
        code = 3000
        print(f"STATUS: {code}  (在游戏中)  game_mode={gm_mode}  物品数={len(items)}")
        print(f"已生成: {out_path}")
        LOGGER.info("STATUS %s: 在游戏中, 物品数=%s, 清单=%s", code, len(items), out_path)
        for i, x in enumerate(items[:15], 1):
            LOGGER.info(
                "  [%s] %s (%s) 质量=%s ilvl=%s 孔=%s loc=%s",
                i, x.get("name"), x.get("code"),
                itm.QUALITY_NAME.get(x.get("quality", 0), x.get("quality")),
                x.get("ilvl"), x.get("socket", 0),
                x.get("body", 0) or x.get("location", 0),
            )
    finally:
        proc.close(handle)
    return 0


def _parse_chain(chain: str) -> tuple[str | None, int, list[int]]:
    """解析指针链，返回 (模块名|None, 首偏移, 后续偏移列表)。

    语法（Cheat Engine 语义：最后一段只加偏移、不再解引用）:
        D2CLIENT+0x50D00             -> 值 = *(D2CLIENT + 0x50D00)
        D2CLIENT+0x50D00,+0x10       -> 值 = *( *(D2CLIENT+0x50D00) + 0x10 )
        D2CLIENT+0x50D00,+0x4,+0x1C  -> 再深一层
        0x6FB00D00                   -> 绝对地址起步
    """
    parts = [p.strip() for p in chain.split(",") if p.strip()]
    if not parts:
        raise ValueError("空的指针链")
    head = parts[0]
    if "+" in head:
        mod, offs = head.split("+", 1)
        return mod.strip().upper(), int(offs.strip(), 16), [int(p, 16) for p in parts[1:]]
    return None, int(head, 16), [int(p, 16) for p in parts[1:]]


def _eval_chain(handle: int, base: int, offs: list[int]):
    """沿偏移链求值。返回 (trace, 最终地址, 最终 dword 值)。

    trace: [(层名, 地址, 该地址读到的 dword)]，便于逐层肉眼核对。
    """
    from d2h.acquire import process as proc

    trace: list[tuple[str, int, int | None]] = []
    addr = base + offs[0]
    val = proc.read_uint(handle, addr, 4)
    trace.append(("L0", addr, val))
    if len(offs) == 1:
        return trace, addr, val
    p = val or 0
    for i, o in enumerate(offs[1:], start=1):
        a = p + o
        v = proc.read_uint(handle, a, 4) if a else None
        trace.append((f"L{i}", a, v))
        if i == len(offs) - 1:
            return trace, a, v
        p = v or 0
    return trace, addr, val


def cmd_probe(args) -> int:
    """多级指针链求值/探测（只读）：打印每一层地址与值，并在终点 dump + 扫描状态码候选。"""
    import struct
    import time

    from d2h.acquire import process as proc
    from d2h.acquire import offsets as off

    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        msg = f"process not found: {exe}"
        LOGGER.error("✗ %s", msg)
        print(msg)
        return 1
    try:
        handle = proc.open_readonly(pid)
    except OSError as e:
        LOGGER.error("打开进程失败: %s", e)
        return 1

    try:
        bases = off.collect_module_bases(handle)
        mod, off0, rest = _parse_chain(args.chain)
        if mod:
            if mod not in bases:
                print(f"module not loaded: {mod}  (已加载: {', '.join(sorted(bases))})")
                return 1
            base = bases[mod]
            origin = f"{mod}(0x{base:X})+0x{off0:X}"
        else:
            base = 0
            origin = f"0x{off0:X}"
        offs = [off0] + rest

        def once(tag: str = "") -> None:
            """采样并打印一次（含状态码语义解读）。"""
            trace, final_addr, final_val = _eval_chain(handle, base, offs)

            print(f"=== 指针链探测 (只读)  PID={pid} {tag}===")
            print(f"  链  : {args.chain}")
            print(f"  起点: {origin}")
            for name, a, v in trace:
                vs = "0x%08X" % v if v is not None else "不可读"
                print(f"  {name}: [0x{a:08X}] -> {vs}")
            print(f"  终点地址: 0x{final_addr:08X}")

            if final_val is not None:
                print(
                    f"  终点值  : dword={final_val}  word={final_val & 0xFFFF}  "
                    f"byte={final_val & 0xFF}"
                )
                if final_val < 10000:  # 小值才可能是状态码，顺手给出语义
                    try:
                        from d2h.acquire import game as _gm

                        _, _desc = _gm.classify_state(final_val)
                        print(f"  状态码语义: {_desc}")
                    except Exception:
                        pass
            if args.dump > 0:
                raw = proc.read_bytes(handle, final_addr, args.dump)
                if raw:
                    print(f"  --- dump 0x{args.dump:X} bytes @ 0x{final_addr:08X} ---")
                    for i in range(0, len(raw), 16):
                        print(f"    +0x{i:03X}: {raw[i:i + 16].hex(' ')}")
                else:
                    print("  (终点不可读)")

            if args.scan > 0:
                raw = proc.read_bytes(handle, final_addr, args.scan)
                if raw:
                    print(f"  --- 状态码候选扫描 (+0x0..+0x{args.scan:X}, 值 1..9999) ---")
                    found = 0
                    for i in range(0, len(raw) - 3, 4):
                        v = struct.unpack_from("<I", raw, i)[0]
                        if 0 < v < 10000:
                            print(f"    +0x{i:03X} dword = {v}")
                            found += 1
                    for i in range(0, len(raw)):
                        if 0 < raw[i] < 100:
                            print(f"    +0x{i:03X} byte  = {raw[i]}")
                            found += 1
                    if not found:
                        print("    (无候选)")

        # 循环监控模式：每 interval 秒自动读一次，p 暂停/继续，Enter 立即读，q 退出
        if args.loop:
            import msvcrt

            paused = False
            print(
                "循环监控: 每 %.1f 秒读一次 | p=暂停/继续 | Enter=立即读 | q=退出"
                % args.interval,
                flush=True,
            )
            while True:
                once(f"[{time.strftime('%H:%M:%S')}] ")
                if paused:
                    print("  [已暂停] p=继续 / Enter=读一次 / q=退出", flush=True)
                    ch = msvcrt.getwch()
                else:
                    deadline = time.time() + args.interval
                    ch = ""
                    while time.time() < deadline:
                        if msvcrt.kbhit():
                            ch = msvcrt.getwch()
                            break
                        time.sleep(0.05)
                if ch.lower() == "q":
                    print("  (退出循环监控)", flush=True)
                    break
                if ch.lower() == "p":
                    paused = not paused
                    print("  [已暂停]" if paused else "  [继续监控]", flush=True)
            return 0

        samples = max(1, args.watch)
        for s in range(samples):
            if samples > 1:
                print(f"\n----- sample {s + 1}/{samples}  {time.strftime('%H:%M:%S')} -----")
            once()
            if s < samples - 1:
                if args.pause:
                    try:
                        line = input("  >>> 切换游戏界面后按 Enter 读取下一次 (输入 q+Enter 退出)...")
                    except EOFError:
                        break
                    if line.strip().lower() == "q":
                        print("  (用户中止)")
                        break
                else:
                    time.sleep(args.interval)
        return 0
    finally:
        proc.close(handle)


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
    sp.add_argument("--label", help="人工标记（如 \"11战网登录界面\"），写入 meta.json")
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
    itp = sub.add_parser("items", help="判断是否在游戏中；若在则生成「当前游戏物品清单.md」")
    itp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    prp = sub.add_parser("probe", help="多级指针链探测（只读逐层解引用/dump/扫描）")
    prp.add_argument(
        "chain",
        help='指针链, 如 "FOG+0x4AFE0,+0x8" / "D2CLIENT+0x50D00,+0x10" / "0x6FF9AFE0"',
    )
    prp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    prp.add_argument("--dump", type=lambda s: int(s, 0), default=64, help="终点 dump 字节数（0=关闭）")
    prp.add_argument("--scan", type=lambda s: int(s, 0), default=0, help="终点扫描范围，打印小整数候选（0=关闭）")
    prp.add_argument("--watch", type=int, default=1, help="采样次数（>1 持续观察）")
    prp.add_argument("--interval", type=float, default=2.0, help="采样间隔秒")
    prp.add_argument(
        "--pause",
        action="store_true",
        help="每次采样后暂停等按键（可手动切游戏界面再读，观察状态码跳变）",
    )
    prp.add_argument(
        "--loop",
        action="store_true",
        help="循环监控: 每 --interval 秒读一次, p=暂停/继续, Enter=立即读, q=退出",
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
        if args.cmd == "items":
            return cmd_items(args)
        if args.cmd == "probe":
            return cmd_probe(args)
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
