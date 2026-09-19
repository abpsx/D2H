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
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 无论以何种方式调用（脚本路径/模块/cwd 不同），都把项目根加入 sys.path，
# 保证 `import d2h` 始终可用（见规范 §15 统一入口）。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from d2h import paths  # noqa: E402  （需在 sys.path 注入后导入）

LOGS = paths.LOGS  # 目录位置以 d2h/paths.py 为唯一权威（规范 §16）

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
    LOGGER.info("子命令: info | find [--target] | snap [--target] | state [--target] | items [--target] | ui | watch [--ui] | send <键> | list | parse <快照名> | tmp [--clean] | menu")
    LOGGER.info("临时文件目录: %s（禁止写 C 盘 %%TEMP%%，见规范 §16）", paths.TEMP)
    LOGGER.info("无游戏时 info/find/list/parse 可离线运行；snap 需游戏在线")
    return 0


def cmd_tmp(args) -> int:
    """查看 / 清理项目内临时目录（禁止 C 盘 %TEMP%）。"""
    if args.clean:
        n, fail = paths.clean_temp()
        LOGGER.info("已清理 temp/: 删除 %s 项，失败 %s 项", n, fail)
        if fail:
            return 1
        return 0
    info = paths.temp_info()
    LOGGER.info("=== 项目临时目录 ===")
    LOGGER.info("路径: %s", info["temp_dir"])
    LOGGER.info("文件: %s 个 | 子目录: %s 个 | 占用: %s 字节", info["files"], info["dirs"], info["bytes"])
    if info["sample"]:
        LOGGER.info("示例: %s", ", ".join(info["sample"]))
    LOGGER.info("清理: d2h/cli.py tmp --clean")
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
        LOGGER.error("[FAIL] %s", msg)
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
        LOGGER.error("[FAIL] %s", msg)
        print(msg)  # 直接打印，确保 bat 控制台可见（不受日志级别影响）
        return 1
    msg = f"game PID: {pid}  (target: {exe})"
    LOGGER.info("[OK] 找到 %s, PID=%s", exe, pid)
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
        LOGGER.error("[FAIL] %s", msg)
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
        LOGGER.error("[FAIL] %s", msg)
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


def _watch_ui(handle: int, pid: int, bases: dict, args) -> int:
    """UI 面板监听：轮询 D2CLIENT+0x50D00 多级指针块，仅在开关变化时输出。"""
    import time

    from d2h.acquire import game as gm
    from d2h.acquire import process as proc

    print(
        f"监听游戏内 UI 面板: *(D2CLIENT+0x50D00) 多级指针  PID={pid}  "
        f"间隔={args.interval}s  仅在面板开关变化时输出（Ctrl+C 退出）"
    )
    LOGGER.info("watch --ui 启动 PID=%s interval=%s", pid, args.interval)

    last: tuple | None = None
    changes = 0
    n = 0
    try:
        while True:
            if args.count and n >= args.count:
                break
            n += 1
            ui = gm.read_ui_panels(handle, bases)
            cur = (tuple(ui["open"]), ui["side"], ui["stash"])
            if cur != last:
                ts = time.strftime("%H:%M:%S")
                opened = ", ".join(ui["open"]) if ui["open"] else "(全部关闭)"
                print(
                    f"[{ts}] {opened}  "
                    f"| 左右位={ui['side']}({ui['side_desc']})  "
                    f"仓库位={ui['stash']}({ui['stash_desc']})",
                    flush=True,
                )
                LOGGER.info("UI 变动: %s side=%s stash=%s", opened, ui["side"], ui["stash"])
                last = cur
                changes += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        proc.close(handle)
    print(f"采样 {n} 次，变动 {changes} 次。")
    return 0


UNIT_TYPE_NAME: dict[int, str] = {
    0: "玩家", 1: "怪物/NPC", 2: "物件", 3: "导弹", 4: "物品", 5: "房间格子",
}

# 这些 UI 面板打开时鼠标停在界面上而非世界画面，游戏不会刷新"世界悬停"值，
# 于是读数会停留在最后交互的对象（典型：仓库界面里一直显示储藏箱）。
def _read_unit_head(handle, p: int):
    """逐字段读 UnitAny 头部（+0x00..+0x2C）。指针不可读返回 None。

    注意：不整块 read_struct —— 悬停单位被释放后 SelectedUnit 会留下陈旧指针，
    整块读会直接失败；逐字段读至少能拿到已缓存的部分。
    """
    from d2h.acquire import process as proc

    if not p:
        return None
    t = proc.read_uint(handle, p + 0x00, 4)
    if t is None:
        return None
    return {
        "dwUnitType": t,
        "dwTxtFileNo": proc.read_uint(handle, p + 0x04, 4),
        "dwUnitId": proc.read_uint(handle, p + 0x0C, 4),
        "dwMode": proc.read_uint(handle, p + 0x10, 4),
        "pUnitData": proc.read_uint(handle, p + 0x14, 4),
        "pPath": proc.read_uint(handle, p + 0x2C, 4),
    }


def _num(v, hexa: bool = False) -> str:
    """字段可能为 None（读不到），统一显示为 '-'。"""
    if v is None:
        return "-"
    return f"0x{v:X}" if hexa else str(v)


def _dump_hover(handle, p: int, namer=None) -> None:
    """打印 SelectedUnit 指向的单位信息（namer 提供名称解析）。"""
    from d2h.acquire import game as gm
    from d2h.acquire import process as proc

    u = _read_unit_head(handle, p)
    if u is None:
        print(f"  指针 0x{p:08X} 不可读 -> 单位多半已被释放（陈旧指针）。"
              "把鼠标重新移到对象上再读一次")
        return
    t = u["dwUnitType"]
    tname = UNIT_TYPE_NAME.get(t, f"未知({t})")
    if t == 5:
        print("  （地面/空地块 —— 不是有效指向对象，鼠标移开时常闪现这一帧）")
    print(f"  类型={t} {tname}  txtFileNo={_num(u['dwTxtFileNo'])}  "
          f"unitId={_num(u['dwUnitId'], True)}  mode={_num(u['dwMode'])}")
    if namer is not None:
        nm, src = namer.name(p, t, u["dwTxtFileNo"])
        if nm:
            print(f"  名称={nm}    [{src}]")
        else:
            print("  名称=<未能解析>（该类型命名链路未覆盖或表不可读）")
    pp = u["pPath"]
    if pp:
        x, y = gm.read_unit_pos(handle, pp, t)
        if x is None or y is None:
            print(f"  坐标=<读不到 pPath=0x{pp:08X}>")
        else:
            print(f"  坐标=({x}, {y})")
    if t == 0 and u["pUnitData"]:
        raw = proc.read_bytes(handle, u["pUnitData"], 16) or b""
        name = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
        print(f"  玩家名={name}")


def _looks_like_unit(handle, v, block=None):
    """判断 v 是否像一个真的 UnitAny*。返回 (type, txt, id, x, y) 或 None。

    过滤条件刻意从严——把任意数据当 UnitAny 解析时 dwUnitType 极易 <=5，
    必须靠 unitId / txtFileNo / pPath 坐标联合校验才不会全是噪声。
    """
    from d2h.acquire import process as proc

    if v % 4 or not (0x10000 < v < 0x7E000000):
        return None
    if block and block[0] <= v < block[1]:
        return None  # 指向采样块自身 = 多半是链表/自引用，不是悬停指针
    t = proc.read_uint(handle, v + 0x00, 4)
    if t is None or t > 5:
        return None
    txt = proc.read_uint(handle, v + 0x04, 4)
    if txt is None or txt > 0x10000:
        return None
    uid = proc.read_uint(handle, v + 0x0C, 4)
    if not uid or uid > 0x100000:
        return None
    pp = proc.read_uint(handle, v + 0x2C, 4)
    if not pp:
        return None
    from d2h.acquire import game as gm
    x, y = gm.read_unit_pos(handle, pp, t)
    if x is None or y is None:
        return None
    return (t, txt, uid, x, y)


def _scan_hover_unit(handle, cb: int, seconds: float, interval: float,
                     lo: int, hi: int) -> int:
    """差异扫描：定位"鼠标指向对象"的指针存在哪个全局里。

    做法：持续采样 D2CLIENT 数据段的一段，把「发生变化、且新值经严格校验确实
    是 UnitAny」的地址记下来。运行期间把鼠标移到 NPC/怪物/物品上并**停住不动**
    ——真指针只在移上去的那一刻变一次，之后保持不变；每帧乱变的是噪声，
    所以扫描结束时会再复检一次，仍指向同一单位的才是最像的答案。全程只读。
    """
    import struct
    from d2h.acquire import process as proc

    start = cb + lo
    size = hi - lo
    n = size // 4
    fmt = f"<{n}I"
    raw0 = proc.read_bytes(handle, start, size)
    if raw0 is None or len(raw0) < size:
        print("采样区间不可读，换个 --range 试试")
        return 1
    cur = struct.unpack(fmt, raw0)
    print(f"采样 0x{start:08X}..0x{start + size:08X}（{n} 个 DWORD），"
          f"{seconds:.0f} 秒内请把鼠标移到 NPC/怪物/物品上…")
    seen: dict[int, list] = {}
    end = time.time() + seconds
    try:
        while time.time() < end:
            time.sleep(interval)
            raw = proc.read_bytes(handle, start, size)
            if raw is None or len(raw) < size:
                continue
            now = struct.unpack(fmt, raw)
            checked = 0
            for i, v in enumerate(now):
                if v == cur[i] or checked > 200:
                    continue
                checked += 1
                info = _looks_like_unit(handle, v, (start, start + size))
                if info is None:
                    continue
                a = start + i * 4
                t, txt, uid, x, y = info
                if a not in seen:
                    stamp = datetime.now().strftime("%H:%M:%S")
                    print(f"[{stamp}] 新候选 0x{a:08X} (D2CLIENT+0x{a - cb:X}) -> "
                          f"0x{v:08X} 类型={t} {UNIT_TYPE_NAME.get(t, '')} "
                          f"txt={txt} unitId=0x{uid:X} 坐标=({x},{y})")
                    seen[a] = [0, v, info]
                seen[a][0] += 1
                seen[a][1] = v
                seen[a][2] = info
            cur = now
    except KeyboardInterrupt:
        print("\n提前结束扫描")
    if not seen:
        print("未捕获到候选：确认期间鼠标真的悬停在对象上，或扩大 --range / 加长 --seconds")
        return 0
    print()
    print("结束时复检（鼠标停在对象上不动 => 真指针此刻应仍指向同一单位）：")
    alive = 0
    for a, (cnt, v, info) in sorted(seen.items()):
        t, txt, uid, x, y = info
        mark = ""
        if proc.read_uint(handle, a, 4) == v:
            alive += 1
            mark = "   <== 仍指向同一单位，最像悬停指针"
        print(f"  0x{a:08X} D2CLIENT+0x{a - cb:X} 变动{cnt}次 最新=0x{v:08X} "
              f"类型={t} {UNIT_TYPE_NAME.get(t, '')} txt={txt} unitId=0x{uid:X} "
              f"坐标=({x},{y}){mark}")
    if not alive:
        print("  没有候选在结束时保持不变 —— 多半全是噪声，重跑时把鼠标停在对象上别动")
    return 0


def cmd_hover(args) -> int:
    """读取鼠标当前指向的单位（UnitAny），只读。--watch 可持续监听。"""
    from d2h.acquire import game as gm
    from d2h.acquire import names as _names
    from d2h.acquire import offsets as off
    from d2h.acquire import process as proc

    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        print(f"process not found: {exe}")
        return 1
    try:
        handle = proc.open_readonly(pid)
    except OSError as e:
        LOGGER.error("打开进程失败: %s", e)
        return 1
    watch = getattr(args, "watch", False)
    interval = getattr(args, "interval", 0.5) or 0.5
    try:
        bases = off.collect_module_bases(handle)
        cb = bases.get("D2CLIENT")
        if not cb:
            print("D2CLIENT 模块不可读")
            return 1
        if getattr(args, "scan", False):
            lo, hi = args.range
            return _scan_hover_unit(handle, cb, getattr(args, "seconds", 30.0),
                                    interval, lo, hi)
        # 命名器：字符串表只构造一次，供整个监听循环复用
        namer = _names.UnitNamer(handle, bases)
        gate = not getattr(args, "no_gate", False)
        if gate:
            print("（悬停开关：D2WIN+0xCA664 HoverFlag —— 0 即判无悬停对象，"
                  "地面/空处不再误报；加 --no-gate 关闭）")
        last_key = None
        had = False        # 上一状态是否「有悬停对象」
        none_run = 0       # 连续 flag=0 的采样数
        first = True       # 首次采样必打印状态（单次读数也总有输出）
        rc = 0
        # 去抖只用于「移开」：flag=0 需连续 2 次才宣布，避免落单帧抖动
        none_need = 2 if (watch and not getattr(args, "no_debounce", False)) else 1
        limit = watch and getattr(args, "seconds", 30.0) and args.seconds > 0
        deadline = time.time() + getattr(args, "seconds", 30.0) if limit else 0
        while True:
            u = gm.read_hover_unit(handle, bases, gate=gate)
            flag = u.get("flag")
            if gate and flag == 0:
                # 权威开关说没有可交互对象 —— 旧值（view_item / hover_id）一律不采信
                none_run += 1
                # 首帧不去抖（否则单次读数可能整轮无输出）
                need = 1 if first else none_need
                if none_run >= need and (had or first):
                    stamp = datetime.now().strftime("%H:%M:%S")
                    if had:
                        print(f"[{stamp}] 已移开（HoverFlag=0）  "
                              f"旧值 id=0x{u.get('hover_id') or 0:X} "
                              f"type={u.get('hover_type')} —— 不采信")
                    else:
                        print(f"[{stamp}] 无悬停对象（HoverFlag=0）"
                              + (f"  旧值 id=0x{u.get('hover_id') or 0:X} "
                                 f"type={u.get('hover_type')}" if u.get("hover_id") else ""))
                    had = False
                    last_key = None
            else:
                none_run = 0
                key = (u.get("ptr"), u.get("hover_id"), u.get("hover_type"))
                if key != last_key:
                    stamp = datetime.now().strftime("%H:%M:%S")
                    print(f"[{stamp}] HoverFlag={flag} 框坐标=({u.get('hx')},{u.get('hy')})  "
                          f"悬停(id=0x{u['hover_id'] or 0:X} type={u['hover_type']})  "
                          f"CurrentViewItem=0x{u['view_item'] or 0:08X}")
                    if not u.get("ptr"):
                        if u.get("source"):
                            print(f"  {u['source']}")
                        else:
                            print("  当前没有指向对象（把鼠标移到 NPC/怪物/物品上）")
                    else:
                        print(f"  -> UnitAny=0x{u['ptr']:08X}  来源: {u['source']}")
                        _dump_hover(handle, u["ptr"], namer)
                    last_key = key
                    had = True
            first = False
            if not watch:
                break
            # 限时监听：--seconds > 0 时到点自动结束（便于非交互抓取，如脚本里跑 20 秒）
            if limit and time.time() >= deadline:
                print(f"\n监听满 {args.seconds:.0f} 秒，结束")
                break
            time.sleep(interval)
        return rc
    except KeyboardInterrupt:
        print("\n已停止监听")
        return 0
    finally:
        proc.close(handle)


def cmd_err(args) -> int:
    """报错现场快照：列出 / 查看 / 清理（报错时由入口自动抓取）。"""
    from d2h.snapshot import errsnap

    if args.clean:
        n = errsnap.clean_errors()
        print(f"已删除 {n} 份错误快照")
        return 0
    if args.show:
        print(errsnap.show_error(args.show))
        return 0
    items = errsnap.list_errors()
    if not items:
        print("没有错误快照（说明还没报过错，或已清理）")
        return 0
    print(f"共 {len(items)} 份：")
    for it in items:
        print(f"  {it['name']}")
        print(f"      命令: {' '.join(it['argv']) or '(菜单)'}   pid={it['pid']}   "
              f"状态码={it['state_code']}")
        print(f"      {it['error']}")
    print("\n查看明细: cli.py err --show <名字>     清空: cli.py err --clean")
    return 0


def cmd_lang(args) -> int:
    """查游戏字符串表（内存 .tbl，只读复刻 D2LANG.GetLocaleText）。"""
    from d2h.acquire import lang
    from d2h.acquire import offsets as off
    from d2h.acquire import process as proc

    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        print(f"process not found: {exe}")
        return 1
    try:
        handle = proc.open_readonly(pid)
    except OSError as e:
        LOGGER.error("打开进程失败: %s", e)
        return 1
    try:
        bases = off.collect_module_bases(handle)
        lt = lang.LocaleText(handle, bases)
        if not lt.ready():
            print("D2LANG 字符串表不可读（需在游戏内，且 D2Lang.dll 已加载）")
            return 1
        ids: list[int] = list(args.ids or [])
        if args.range:
            lo, hi = args.range
            ids.extend(range(lo, min(hi, lo + 2000) + 1))
        if not ids:
            print("用法: cli.py lang <id> [id...]  /  --range LO HI  /  --search 关键字")
            return 1
        for g in lt.groups:
            print(f"组 {g['tag']}: count={g['count']}")
        print()
        for sid in ids:
            raw = lt.get(sid)
            if not raw:
                continue
            show = raw if args.raw else lang.strip_color(raw)
            if args.search and args.search not in show:
                continue
            print(f"{sid:>7}  {show}")
        return 0
    finally:
        proc.close(handle)


def _auto_errsnap(exc: BaseException, argv, args=None) -> None:
    """报错时自动抓一份现场（见规范 §17）。抓快照本身失败也不影响主流程。"""
    try:
        from d2h.snapshot import errsnap

        target = getattr(args, "target", "loader") if args is not None else "loader"
        d = errsnap.capture_error(exc, list(argv or []), target)
        if d:
            print(f"[错误现场已存档] {d}")
            print("  可离线对照校验，确认无误后 cli.py err --clean 删除")
    except Exception as snape:  # noqa: BLE001
        LOGGER.debug("抓取错误现场失败: %s", snape)


def cmd_ui(args) -> int:
    """一次性读取游戏内 UI 面板标记（只读）。"""
    from d2h.acquire import game as gm
    from d2h.acquire import offsets as off
    from d2h.acquire import process as proc

    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        msg = f"process not found: {exe}"
        LOGGER.error("[FAIL] %s", msg)
        print(msg)
        return 1
    try:
        handle = proc.open_readonly(pid)
    except OSError as e:
        LOGGER.error("打开进程失败: %s", e)
        return 1
    try:
        bases = off.collect_module_bases(handle)
        code = gm.read_game_state(handle, bases)
        ing, desc = gm.classify_state(code)
        ui = gm.read_ui_panels(handle, bases)
        print(f"PID={pid}  状态={code} ({desc})")
        if ui["base"]:
            print(f"*(D2CLIENT+0x50D00) = 0x{ui['base']:08X}   UIVar 数组起点 = 0x{ui['array']:08X}")
        else:
            print("UI 块不可读（未在游戏中的常见表现）")
        for o, name, side in off.UI_PANELS:
            v = ui["panels"].get(name)
            mark = "开" if v == 1 else ("关" if v == 0 else f"?({v})")
            key = off.UI_PANEL_KEYS.get(name, "")
            hm = off.UI_PANEL_HM.get(o // 4, "")
            print(f"  +{o:02X} [{o // 4:>2}] {name:<14} 侧={side} 键={key:<11} {hm:<12} {mark}")
        print(f"  左右位(D2CLIENT+0x11C414) = {ui['side']} ({ui['side_desc']})")
        print(f"  仓库位(D2CLIENT+0x11BC34) = {ui['stash']} ({ui['stash_desc']})")
        return 0 if ing else 2
    finally:
        proc.close(handle)


def cmd_send(args) -> int:
    """向游戏窗口投递按键（PostMessage，不写内存）。用于开发期验证。"""
    from d2h.acquire import process as proc
    from d2h.tools import keys as K

    vk = K.resolve_key(args.key)
    if vk is None:
        print(f"未知按键: {args.key}（可用: {', '.join(sorted(K.KEYS))} 或单字符/0xNN）")
        return 1
    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        msg = f"process not found: {exe}"
        LOGGER.error("[FAIL] %s", msg)
        print(msg)
        return 1
    hwnd = K.find_main_hwnd(pid)
    if not hwnd:
        print(f"未找到窗口句柄 (pid={pid})")
        return 1
    ok = True
    for _ in range(max(1, args.times)):
        ok = K.send_key(hwnd, vk) and ok
        time.sleep(args.gap)
    print(f"send {args.key} (vk=0x{vk:02X}) -> hwnd=0x{hwnd:08X} pid={pid} {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


def cmd_watch(args) -> int:
    """变动监听（只读）：按 interval 轮询指针链，**仅在值变动时**向窗口输出一行。

    默认监听游戏状态码链 FOG+0x4AFE0,+0x8，间隔 0.3 秒；Ctrl+C 退出。
    """
    import time

    from d2h.acquire import process as proc
    from d2h.acquire import offsets as off

    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        msg = f"process not found: {exe}"
        LOGGER.error("[FAIL] %s", msg)
        print(msg)
        return 1
    try:
        handle = proc.open_readonly(pid)
    except OSError as e:
        LOGGER.error("打开进程失败: %s", e)
        return 1

    bases = off.collect_module_bases(handle)
    if args.ui:
        return _watch_ui(handle, pid, bases, args)
    mod, off0, rest = _parse_chain(args.chain)
    if mod:
        if mod not in bases:
            print(f"module not loaded: {mod}  (已加载: {', '.join(sorted(bases))})")
            proc.close(handle)
            return 1
        base = bases[mod]
    else:
        base = 0
    offs = [off0] + rest

    def meaning(v: int | None) -> str:
        if v is None:
            return "不可读"
        if v < 10000:  # 小值才当状态码解读
            try:
                from d2h.acquire import game as _gm

                _ing, desc = _gm.classify_state(v)
                return desc
            except Exception:  # noqa: BLE001
                return ""
        return ""

    def label(v: int | None) -> str:
        """把状态码渲染成 '界面名(码)'；非状态码则直接给数值。"""
        if v is None:
            return "不可读"
        m = meaning(v)
        return f"{m}({v})" if m else str(v)

    print(
        f"监听界面标记: {args.chain}  PID={pid}  间隔={args.interval}s  "
        f"仅在界面切换时输出（Ctrl+C 退出）"
    )
    LOGGER.info("watch 启动: %s PID=%s interval=%s", args.chain, pid, args.interval)

    last: int | None = None
    changes = 0
    n = 0
    try:
        while True:
            if args.count and n >= args.count:
                break
            n += 1
            _trace, _addr, val = _eval_chain(handle, base, offs)
            if val != last:
                ts = time.strftime("%H:%M:%S")
                m = meaning(val)
                extra = f"  [{m}]" if m else ""
                print(f"[{ts}] {label(last)} -> {label(val)}", flush=True)
                LOGGER.info("watch 变动: %s -> %s%s", last, val, extra)
                last = val
                changes += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        proc.close(handle)
    print(f"采样 {n} 次，变动 {changes} 次。")
    return 0


def _dispatch(argv: list[str]) -> int:
    """按 argv 执行一次子命令（菜单内部复用，避免反复启动 Python）。"""
    args = build_parser().parse_args(argv)
    table = {
        "info": cmd_info,
        "find": cmd_find,
        "snap": cmd_snap,
        "state": cmd_state,
        "items": cmd_items,
        "probe": cmd_probe,
        "list": cmd_list,
        "tmp": cmd_tmp,
        "parse": cmd_parse,
        "menu": cmd_menu,
        "watch": cmd_watch,
        "ui": cmd_ui,
        "hover": cmd_hover,
        "send": cmd_send,
        "err": cmd_err,
        "lang": cmd_lang,
    }
    fn = table.get(args.cmd)
    return fn(args) if fn is not None else 0


# 菜单项：(编号, 说明, argv)。argv 为 None 表示走子流程。
MENU_ITEMS: list[tuple[str, str, list[str] | None]] = [
    ("1", "项目信息", ["info"]),
    ("2", "查找游戏 PID（默认 D2loader.exe）", ["find"]),
    ("3", "查找游戏 PID：选择目标类型", None),
    ("4", "拍快照（需游戏在线）", ["snap"]),
    ("5", "列出本地快照", ["list"]),
    ("6", "解析快照", None),
    ("7", "当前物品清单（需在游戏中）", ["items"]),
    ("8", "状态码循环监控（3 秒一次：p 暂停 / Enter 立即读 / q 退出）",
     ["probe", "FOG+0x4AFE0,+0x8", "--loop", "--interval", "3", "--dump", "0", "--scan", "0"]),
    ("9", "查看临时目录", ["tmp"]),
    ("10", "清空临时目录", ["tmp", "--clean"]),
    ("11", "界面标记监听（0.3 秒轮询，界面切换才输出，Ctrl+C 结束）", ["watch"]),
    ("12", "游戏内 UI 面板监听（0.3 秒轮询，面板开关变化才输出）", ["watch", "--ui"]),
    ("13", "查看游戏内 UI 面板（一次性读数）", ["ui"]),
    ("14", "向游戏投递按键（i/q/c/t/esc，仅窗口消息不写内存）", None),
    ("15", "查看鼠标指向的对象（NPC/怪物/物品，一次性读数）", ["hover"]),
    ("16", "鼠标指向对象监听（0.5 秒轮询，悬停开关门控，Ctrl+C 结束）",
     ["hover", "--watch"]),
    ("17", "定位鼠标指向指针（差异扫描 30 秒：期间把鼠标移到 NPC/物品上并停住）",
     ["hover", "--scan"]),
    ("18", "报错现场快照：列出（报错时自动抓取，可离线对照）", ["err"]),
    ("19", "清理报错现场快照", ["err", "--clean"]),
    ("20", "查询游戏字符串表（内存 .tbl，输入 id 或区间）", None),
    ("q", "退出", None),
]


def _menu_target() -> list[str] | None:
    """目标类型子菜单：返回 find 的 argv，None = 返回上级。"""
    while True:
        print()
        print("  目标进程类型：")
        print("    l. D2loader.exe（默认）")
        print("    g. game.exe")
        print("    x. 返回上级菜单")
        try:
            t = input("  请选择 [l/g/x]: ").strip().lower()
        except EOFError:
            return None
        if t == "l":
            return ["find", "--target", "loader"]
        if t == "g":
            return ["find", "--target", "game"]
        if t == "x":
            return None
        print("  输入无效。")


def _menu_parse() -> list[str] | None:
    """快照选择子菜单：返回 parse 的 argv，None = 返回上级。"""
    from d2h.snapshot import store

    snaps = store.list_snapshots()
    if not snaps:
        print("  暂无快照，请先执行选项 4 拍一张。")
        return None
    while True:
        print()
        print("  选择要解析的快照：")
        for i, s in enumerate(snaps, 1):
            print(f"    {i}. {s.get('_name')}")
        print("    x. 返回上级菜单")
        try:
            raw = input("  请输入序号 [x 返回]: ").strip().lower()
        except EOFError:
            return None
        if raw == "x":
            return None
        try:
            idx = int(raw)
        except ValueError:
            print("  输入无效。")
            continue
        if 1 <= idx <= len(snaps):
            return ["parse", str(snaps[idx - 1].get("_name"))]
        print("  序号超出范围。")


def _menu_sendkey() -> list[str] | None:
    """发键子菜单：返回 send 的 argv，None = 返回上级。"""
    while True:
        print()
        print("  向游戏窗口投递按键（PostMessage，不写内存）：")
        print("    i. I  背包     q. Q  任务")
        print("    c. C  属性     t. T  技能树")
        print("    e. ESC 关闭当前 UI / 无 UI 时打开设置")
        print("    x. 返回上级菜单")
        try:
            t = input("  请选择 [i/q/c/t/e/x]: ").strip().lower()
        except EOFError:
            return None
        if t == "x":
            return None
        mapping = {"i": "i", "q": "q", "c": "c", "t": "t", "e": "esc"}
        if t in mapping:
            return ["send", mapping[t]]
        print("  输入无效。")


def _menu_lang() -> list[str] | None:
    """字符串表查询子菜单：返回 lang 的 argv，None = 返回上级。"""
    print()
    print("  查询游戏字符串表（从内存 .tbl 读取，非本地文件）：")
    print("    直接输入 id（可空格分隔多个，支持 0x 十六进制）")
    print("    或输入区间如  10000-10050")
    print("    x. 返回上级菜单")
    try:
        raw = input("  请输入 [x 返回]: ").strip()
    except EOFError:
        return None
    if raw.lower() == "x" or not raw:
        return None
    m = re.fullmatch(r"(\w+)\s*-\s*(\w+)", raw)
    if m:
        try:
            return ["lang", "--range", str(int(m.group(1), 0)), str(int(m.group(2), 0))]
        except ValueError:
            print("  区间格式无效。")
            return None
    return ["lang"] + raw.split()


def cmd_menu(args) -> int:
    """交互式中文菜单（run.bat 无参数双击时进入；也可 `cli.py menu` 直接跑）。

    bat 保持纯 ASCII（中文会导致 cmd 按本地代码页解碎脚本），
    所有中文界面与交互全部由 Python 渲染，且子命令在同一进程内复用。
    """
    while True:
        print()
        print("==========================================")
        print("            D2H 工具（内存只读）")
        print("==========================================")
        for key, desc, _ in MENU_ITEMS:
            print(f"  {key:>2}. {desc}")
        print("==========================================")
        try:
            choice = input("请选择 [1-20/q]: ").strip().lower()
        except EOFError:
            print("(输入结束，退出)")
            return 0
        if choice in ("q", "quit", "exit"):
            print("已退出。")
            return 0
        item = next((m for m in MENU_ITEMS if m[0] == choice), None)
        if item is None:
            print("输入无效，请重新选择。")
            continue
        key, _desc, argv = item
        if key == "3":
            argv = _menu_target()
        elif key == "6":
            argv = _menu_parse()
        elif key == "14":
            argv = _menu_sendkey()
        elif key == "20":
            argv = _menu_lang()
        if argv is None:
            continue
        print()
        try:
            _dispatch(argv)
        except (KeyboardInterrupt, SystemExit):
            print("\n(已中断，返回菜单)")
        except Exception as e:  # noqa: BLE001  菜单不因单条命令失败而退出
            LOGGER.exception("执行出错: %s", e)
            _auto_errsnap(e, argv, None)
        try:
            input("\n按回车返回菜单...")
        except EOFError:
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
    sub.add_parser("menu", help="交互式中文菜单（run.bat 无参数时默认进入）")
    wp = sub.add_parser(
        "watch", help="界面标记监听：按间隔轮询状态码，仅在界面切换时输出（默认 0.3s）"
    )
    wp.add_argument("--chain", default="FOG+0x4AFE0,+0x8", help="指针链（默认界面标记链）")
    wp.add_argument("--interval", type=float, default=0.3, help="轮询间隔秒（默认 0.3）")
    wp.add_argument("--count", type=int, default=0, help="采样次数上限，0=不限（默认）")
    wp.add_argument(
        "--ui",
        action="store_true",
        help="监听游戏内 UI 面板标记（*(D2CLIENT+0x50D00) 多级指针），而非状态码链",
    )
    wp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    uip = sub.add_parser("ui", help="一次性读取游戏内 UI 面板标记（背包/属性/技能树/任务/设置…）")
    uip.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    hp = sub.add_parser("hover", help="读取鼠标当前指向的单位（NPC/怪物/物品/物件）")
    hp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    hp.add_argument(
        "--watch", action="store_true",
        help="持续监听，只在指向对象变化时打印（Ctrl+C 退出）",
    )
    hp.add_argument(
        "--interval", type=float, default=0.5,
        help="--watch / --scan 的轮询间隔秒数（默认 0.5）",
    )
    hp.add_argument(
        "--scan", action="store_true",
        help="差异扫描：持续采样并找出变成 UnitAny 指针的全局地址（需同时把鼠标移到对象上）",
    )
    hp.add_argument(
        "--no-debounce", action="store_true",
        help="--watch 关闭去抖（默认：移开需连续 2 次采样才宣布，滤掉单帧抖动）",
    )
    hp.add_argument(
        "--no-gate", action="store_true",
        help="关闭悬停开关门控（默认用 D2WIN+0xCA664 HoverFlag 判定是否真有悬停对象）",
    )
    hp.add_argument(
        "--seconds", type=float, default=30.0,
        help="时长秒数：--scan 的扫描时长 / --watch 的监听时长（默认 30；--watch 给 0 表示不限时）",
    )
    hp.add_argument(
        "--range", nargs=2, default=[0x100000, 0x130000],
        type=lambda s: int(s, 0), metavar=("LO", "HI"),
        help="--scan 的采样区间（相对 D2CLIENT 基址，默认 0x100000 0x130000）",
    )
    lp = sub.add_parser("lang", help="查游戏字符串表（内存 .tbl，只读）")
    lp.add_argument("ids", nargs="*", type=lambda s: int(s, 0),
                    help="字符串 id（可多个，支持 0x 十六进制）")
    lp.add_argument("--range", nargs=2, type=lambda s: int(s, 0), metavar=("LO", "HI"),
                    help="批量列出 id 区间（上限 2000 条）")
    lp.add_argument("--search", help="只显示包含该关键字的结果")
    lp.add_argument("--raw", action="store_true", help="保留游戏颜色控制符（默认已清洗）")
    lp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    skp = sub.add_parser("send", help="向游戏窗口投递按键（PostMessage，不写内存；仅供开发验证）")
    skp.add_argument("key", help="按键名: i/q/c/t/esc/enter/space，或单字符、0xNN 虚拟键码")
    skp.add_argument("--times", type=int, default=1, help="投递次数（默认 1）")
    skp.add_argument("--gap", type=float, default=0.3, help="多次投递间隔秒（默认 0.3）")
    skp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    tp = sub.add_parser("tmp", help="查看/清理项目内临时目录（禁写 C 盘 %TEMP%）")
    tp.add_argument("--clean", action="store_true", help="清空 temp/")
    ep = sub.add_parser("err", help="报错现场快照：列出/查看/清理（报错时自动抓取）")
    ep.add_argument("--show", metavar="NAME", help="查看某份错误快照的明细")
    ep.add_argument("--clean", action="store_true", help="删除全部错误快照")
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
        if args.cmd == "menu":
            return cmd_menu(args)
        if args.cmd == "watch":
            return cmd_watch(args)
        if args.cmd == "ui":
            return cmd_ui(args)
        if args.cmd == "hover":
            return cmd_hover(args)
        if args.cmd == "send":
            return cmd_send(args)
        if args.cmd == "list":
            return cmd_list(args)
        if args.cmd == "tmp":
            return cmd_tmp(args)
        if args.cmd == "err":
            return cmd_err(args)
        if args.cmd == "lang":
            return cmd_lang(args)
        if args.cmd == "parse":
            return cmd_parse(args)
        return 0
    except Exception as e:  # 顶层兜底，友好退出，不吐堆栈给用户
        LOGGER.exception("执行失败: %s", e)
        _auto_errsnap(e, argv if argv is not None else sys.argv[1:], args)
        return 2
    finally:
        LOGGER.info("本次日志已存档: %s", logfile)


if __name__ == "__main__":
    sys.exit(main())
