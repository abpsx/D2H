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


def cmd_hover(args) -> int:
    """读取鼠标当前指向的单位（UnitAny），只读。"""
    from d2h.acquire import offsets as off
    from d2h.acquire import process as proc
    from d2h.acquire import structs as st

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
        cb = bases.get("D2CLIENT")
        if not cb:
            print("D2CLIENT 模块不可读")
            return 1
        rel = off.VARS["D2CLIENT"]["SelectedUnit"] - off.DLLBASE["D2CLIENT"]
        addr = cb + rel
        p = proc.read_uint(handle, addr, 4)
        print(f"PID={pid}  SelectedUnit @0x{addr:08X} = 0x{p:08X}" if p else
              f"PID={pid}  SelectedUnit @0x{addr:08X} = 0（当前没有指向对象）")
        if not p:
            return 0
        u = proc.read_struct(handle, p, st.UnitAny)
        tname = UNIT_TYPE_NAME.get(u.dwUnitType, f"未知({u.dwUnitType})")
        print(f"  类型={u.dwUnitType} {tname}  txtFileNo={u.dwTxtFileNo}  unitId=0x{u.dwUnitId:X}")
        if u.pPath:
            x = proc.read_uint(handle, u.pPath + 0x02, 2)
            y = proc.read_uint(handle, u.pPath + 0x06, 2)
            print(f"  坐标=({x}, {y})")
        if u.dwUnitType == 0 and u.pUnitData:
            raw = proc.read_bytes(handle, u.pUnitData, 16) or b""
            name = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
            print(f"  玩家名={name}")
        return 0
    finally:
        proc.close(handle)


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
            choice = input("请选择 [1-14/q]: ").strip().lower()
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
        if argv is None:
            continue
        print()
        try:
            _dispatch(argv)
        except (KeyboardInterrupt, SystemExit):
            print("\n(已中断，返回菜单)")
        except Exception as e:  # noqa: BLE001  菜单不因单条命令失败而退出
            LOGGER.exception("执行出错: %s", e)
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
