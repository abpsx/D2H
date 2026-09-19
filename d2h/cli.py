#!/usr/bin/env python3
"""D2H 统一入口（见规范 §15）。

所有 D2H 的 Python 执行都经此入口；由 run.bat 唤起。
每次运行：控制台(stdout) + logs/d2h_<时间戳>_<src>.txt **同步双写** ——
print / logging / traceback 全部落盘（d2h/runlog.py 把 stdout 包成 Tee），
`logs/latest.txt` 指向最近一次；D2H_LOG=0 可关闭落盘。
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

from d2h import paths, runlog  # noqa: E402  （需在 sys.path 注入后导入）

LOGS = paths.LOGS  # 目录位置以 d2h/paths.py 为唯一权威（规范 §16）

LOGGER = logging.getLogger("d2h")


def setup_logging() -> Path | None:
    """初始化日志：控制台 + logs/d2h_<时间戳>_<src>.txt 双写。

    ★ 2026-09-20 修正（用户要求「bat 内所有打印调用都加上保存本地日志」）：
      此前**只有 LOGGER 落盘**，满屏 `print()` 一条都没进文件 —— logs/ 里每个文件
      才几百字节，排障时等于没日志。现在由 `d2h.runlog` 把 sys.stdout / sys.stderr
      整体包成 Tee ⇒ **屏幕上出现的 = 盘里有的**（print、logging、traceback 全收）。

    ★ 安装顺序（必须，反了会重复落盘）：
        ① 先给 LOGGER 挂 StreamHandler（此刻捕获的是**原始** sys.stdout）；
        ② 再把 sys.stdout / sys.stderr 换成 Tee。
      反过来的话 LOGGER→sys.stdout(=Tee)→文件，同一行会在文件里出现两遍。

    ★ 日志文件名里的 src 标签来自环境变量 D2H_LOG_SRC（bat 内设置）：
        run.bat=run / watch.bat=watch / uiwatch.bat=uiwatch / capture.py=agent / 默认 cli
      `logs/latest.txt` 永远指向最近一次日志，bat 结尾只提示这个路径即可。
    ★ D2H_LOG=0 关闭落盘（返回 None，不创建文件）。
    """
    LOGGER.handlers.clear()          # 同进程内多次 main() 时避免 handler 叠加
    LOGGER.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(module)s: %(message)s", "%H:%M:%S"
    )
    sh = logging.StreamHandler(sys.stdout)  # bat 可见（向 bat 输出执行过程）
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    LOGGER.addHandler(sh)

    if not runlog.enabled():
        LOGGER.info("注意: 本次不写日志文件（D2H_LOG=0）")
        return None

    LOGS.mkdir(parents=True, exist_ok=True)
    logfile = runlog.new_path(LOGS)
    stream = runlog.open_stream(logfile)      # UTF-8 行缓冲，下面与 Sink 共用
    sink = runlog.make_sink(stream, label="log")
    # ★ handler 的 stream 必须是 Sink 而不是原始 stream：
    #   watch 类命令的输出**全走 LOGGER**，直写句柄就会绕过大小上限（上限形同虚设）。
    fh = logging.StreamHandler(sink)          # 与 print 共用同一额度 + 同一句柄
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    LOGGER.addHandler(fh)

    runlog.install(sink)                      # ← 必须在上面两个 handler 之后
    runlog.write_header(stream)               # 元信息只进文件，不进控制台
    runlog.write_latest(LOGS, logfile)

    LOGGER.info("D2H 启动 | 日志文件: %s", logfile)
    LOGGER.info("日志说明: 控制台与文件同步双写（含全部 print）；"
                "上限 %s 字节，可用 D2H_LOG_MAX_MB 调整", runlog.max_bytes())
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


def _print_layout(lay: dict) -> None:
    """打印 gpt 描述区里与词缀相关的槽位（原始值，全部打出来）。"""
    print("---- 词缀表布局（gpt 描述区，1.13c 偏移）----")
    print(f"  gpt=0x{lay['gpt']:08X}  nItemsTxt={lay['n_items_txt']}"
          f"  词缀表当前可读={'是' if lay['tables_readable'] else '否'}")
    print(f"  0x90 块 基址=0x{lay['magic_block']:08X}（一张大表，行距 0x90）")
    print(f"    值 1..{lay['magic_suffix_rows']}      后缀区   "
          f"（gpt+0x2C 与 gpt+0x30 两指针实测相差 {lay['magic_suffix_rows']} 行）")
    print(f"    值 {lay['magic_suffix_rows'] + 1}..{lay['magic_suffix_rows'] + lay['magic_prefix_rows']}"
          f"   前缀区   (gpt+0x30=0x{lay['magic_prefix']:08X})")
    print(f"    值 {lay['magic_suffix_rows'] + lay['magic_prefix_rows'] + 1}"
          f"..{lay['magic_suffix_rows'] + lay['magic_prefix_rows'] + lay['auto_rows']}"
          f"  第三段   (gpt+0x34=0x{lay['auto_affix']:08X} 共 {lay['auto_rows']} 行)"
          f"  ← 身份推断=自动前缀(automagic)，待实机确认")
    print(f"  0x48 块 基址=0x{lay['rare_words']:08X}（稀有物品**名字词**，行距 0x48）")
    print(f"    值 1..{lay['rare_word_suffix_rows']}    稀有后缀词区"
          f"    值 {lay['rare_word_suffix_rows'] + 1}..{lay['rare_word_suffix_rows'] + lay['rare_word_prefix_rows']}"
          f"  稀有前缀词区 (gpt+0x54=0x{lay['rare_words_prefix']:08X})"
          f"   （gpt+0x48 计数={lay['n_rare_words']}）")
    print(f"  Gems p=0x{lay['gems']:08X} n={lay['n_gems']}"
          f"   Runes/Runewords p=0x{lay['runes']:08X} n={lay['n_runes']}")
    print(f"  取行公式={lay['id_mode']}")
    print("    ⇒ 值=1 命中表首行；`另一解` 列就是「值当 0 基」的邻行。")
    print("    ★ 已用实机 roll 值证实（2026-09-20）：稀有戒指 4 条属性同时命中 (值-1) ——")
    print("      后缀174→行173 学徒的 FCR 10-10（实际10）、后缀286→行285 机会的 MF 5-15（实际10）、")
    print("      前缀1156→行1155 Beryl PR 5-10（实际10）、前缀987→行986 Steel AR 41-60（实际43）。")
    print("      故「采信」列=已证实；`props --hover` 的悬停对答案保留作回归手段。")
    if not lay["tables_readable"]:
        print("  [WARN] 词缀表内容当前为不可读（读到全 0）。实测**离开游戏后该块会被清零**，")
        print("         所以先确认在游戏中，再判读下面的词缀结果。")


def _print_item_props(rep: dict, title: str, props, hover_text: str = "",
                      depth: int = 0) -> None:
    """完整打印一件物品的词缀 + 属性（规范 §12：所有字段一律打，缺失打 `-`）。

    `props` = itemprops.ItemProps 实例（借它读孔内子物品；自带 handle/bases）。
    `depth` 仅用于孔内递归限深，避免异常数据无限套娃。
    """
    from d2h.acquire import itemprops as ipx

    print()
    print(title)
    print(f"  ptr=0x{rep['ptr']:08X}  unit_type={rep['unit_type']}  txt_file_no={rep['txt_file_no']}"
          f"  unit_id=0x{rep['unit_id']:X}  pItemData=0x{rep['p_item_data']:08X}")
    if hover_text:
        print(f"  悬停文本框(游戏自绘，对答案用)= {hover_text}")
    if not rep.get("ok"):
        print(f"  [FAIL] {rep.get('reason')}")
        return
    f = rep["fields"]
    print("  -- ItemData 原始字段 --")
    print(f"    dwQuality={f['quality']}  dwFileIndex={f['file_index']}  dwItemLevel={f['ilvl']}"
          f"  wItemFormat={f['item_format']}")
    print(f"    dwItemFlags=0x{f['flags']:08X}  [{', '.join(rep['flag_names']) or '-'}]")
    print(f"    nBodyLocation={f['n_body_location']}  nItemLocation={f['n_item_location']}"
          f"  nLocation={f['n_location']}")
    print(f"    dwOwnerId=0x{f['owner_id']:08X}  pOwnerInventory=0x{f['p_owner_inv']:08X}"
          f"  pNextInvItem=0x{f['p_next_inv_item']:08X}")
    print(f"    wRarePrefix={f['rare_prefix']}  wRareSuffix={f['rare_suffix']}"
          f"  wAutoPrefix={f['auto_prefix']}")
    raw_mp = f.get("magic_prefix_raw") or f["magic_prefix"]
    print(f"    wMagicPrefix={raw_mp}  wMagicSuffix={f['magic_suffix']}")
    rw = rep.get("runeword")
    if rw:
        print(f"    ★ 符文之语：wMagicPrefix[0]={rw['locale']} 是**名字 locale id**（不是词缀索引）"
              f" → {rw['name'] or '-'}")

    print("  -- 词缀 --")
    any_affix = False
    for a in rep["affixes"]:
        if not a["idx"] and not a["rec"]:
            continue
        any_affix = True
        print(f"    [{a['kind']} 槽{a['slot']}] id={a['idx'] or 0}  解析方式={a.get('mode') or '-'}")
        r = a.get("rec")
        if r:
            print(f"        采信  : 行{a['idx'] - 1}({a.get('zone') or '-'})  0x{r['rec_addr']:08X}"
                  f"  name={r['name'] or '-'}  internal={r['internal'] or '-'}"
                  f"  locale={r['locale']}")
        elif a["idx"]:
            print(f"        采信  : -（行{a['idx'] - 1} {a.get('zone') or '-'} 读不到名字："
                  f"越界 / 空行 / 表不可读）")
        alt = a.get("alt_rec")
        if alt:
            print(f"        另一解: 行{a['idx']}({a.get('alt_zone') or '-'})  0x{alt['rec_addr']:08X}"
                  f"  name={alt['name'] or '-'}  internal={alt['internal'] or '-'}"
                  f"  locale={alt['locale']}")
        else:
            print(f"        另一解: -（行{a['idx']} {a.get('alt_zone') or '-'}）")
    if not any_affix:
        print("    （该物品 ItemData 里没有词缀 id：普通/超强/暗金/套装/宝石/符文都是这样）")
    rn = rep.get("rare_name")
    if rn and (f.get("rare_prefix") or f.get("rare_suffix")):
        print(f"  -- 稀有物品显示名（前缀词+后缀词，游戏公式取行）--")
        print(f"    (值-1) 采信 = {rn['primary']}")
        print(f"    (值)   另一解 = {rn['alt']}")

    print(f"  -- 属性 StatList 全组（共 {len(rep['stats'])} 条；原始值直读=显示值，"
          f"已用悬停文本验证）--")
    for k, s in enumerate(rep["stats"]):
        extra = (f"  alt(÷256,未验证)={s['value_alt']}" if s.get("value_alt") is not None else "")
        print(f"    [{k:>3}] {'EX' if s['ex'] else '  '} list{s['list']} {s['group']:<4s}"
              f" #{s['index']:<2d} stat={s['stat_id']:<4d} param={s['param']:<5d}"
              f" raw={s['value']:<10d} show={s['value_show']:<8}{extra}"
              f" desc={s['desc'] or '-'}"
              f" func={s['desc_func']} val={s['desc_val']} text={s['text'] or '-'}"
              f"  [ItemStatCost 原样: div={s['isc_div']} mul={s['isc_mul']}]")
    print(f"  -- 孔内物品（{len(rep['sockets'])} 个）--")
    if not rep["sockets"]:
        print("    -（该物品未打孔，或孔内为空；未打孔时 pOwnerInventory 指向玩家背包，"
              "不能当孔用，code 已按 SOCKETED 标志门控）")
    _tb = None
    _lt = None
    for sp in rep["sockets"]:
        if depth >= 1:
            print(f"    孔内 ptr=0x{sp:08X}（层级过深，不再递归）")
            continue
        sub = ipx.item_affix_report(props.handle, props.bases, sp)
        # 子物品先报「代码 + 显示名」（内存 ItemTxt + 内存字符串表），取不到打 `-`
        if sub.get("ok"):
            if _tb is None:
                from d2h.acquire import items as itm
                from d2h.acquire import lang as lg
                _tb = itm.ItemTextTable(props.handle, props.bases)
                _lt = lg.LocaleText(props.handle, props.bases)
            _rec = _tb.read(sub["txt_file_no"]) if _tb.ptr else None
            _nm = ""
            if _rec and _lt.ready():
                _nm = _lt.get_clean(_rec["locale"]) or ""
            print(f"    孔内 ptr=0x{sp:08X}  txt={sub['txt_file_no']}"
                  f"  code={_rec['code'] if _rec else '-'}  名={_nm or '-'}")
        _print_item_props(sub, f"    ++++ 孔内物品 ptr=0x{sp:08X} ++++", props, "", depth + 1)


def cmd_props(args) -> int:
    """物品词缀 + 属性解析（只读）。

    规范 §12：所有字段一律打印，空值显式打 `-`，禁止按条件裁剪。

    用法：
      props                列出背包/装备物品（编号 + 名称 + 原始词缀 id 一览）
      props --index 3      对第 3 件出完整报告
      props --all          对全部物品出报告
      props --hover        对鼠标当前指向的物品出报告（同时打印游戏自绘的悬停文本框，用于对答案）
    """
    from d2h.acquire import process as proc
    from d2h.acquire import offsets as off
    from d2h.acquire import game as gm
    from d2h.acquire import items as itm
    from d2h.acquire import itemprops as ipx

    exe, pid = proc.find_target_pid(args.target)
    if pid is None:
        print(f"process not found: {exe}")
        LOGGER.error("[FAIL] process not found: %s", exe)
        return 1
    handle = proc.open_readonly(pid)
    try:
        bases = off.collect_module_bases(handle)
        for need in ("D2CLIENT", "D2COMMON"):
            if need not in bases:
                print(f"[FAIL] 缺少模块 {need}，无法解析")
                return 1
        st = gm.in_game_status(handle, bases)
        print(f"STATUS: {st['status']}  ({st['status_desc']})  game_mode={st.get('game_mode')}")

        props = ipx.ItemProps(handle, bases)
        _print_layout(props.table_layout())

        rows: list[dict] = []
        hover_text = ""
        if args.hover:
            u = gm.read_hover_unit(handle, bases)
            ptr = u.get("ptr")
            print(f"鼠标指向: {u.get('source') or '-'}  ptr={'0x%08X' % ptr if ptr else '-'}"
                  f"  unit_type={u.get('unit_type')}  txt={u.get('txt')}")
            hover_text = gm.read_hover_text(handle, bases)
            print(f"悬停文本框(游戏自绘)= {hover_text or '-'}")
            if ptr:
                rows = [{"ptr": ptr, "name": u.get("name") or "", "code": "",
                         "type": u.get("txt"), "quality": None, "type_name": "",
                         "ilvl": None, "file_index": None, "unit_id": u.get("unit_id"),
                         "name_src": "悬停"}]
        else:
            rows = itm.named_inventory(handle, bases)
            if not rows:
                print("[WARN] 没有枚举到任何物品（不在游戏内 / 玩家单位不可读）")
                return 1

        if not (args.index or args.all or args.hover):
            print()
            print(f"---- 物品清单（{len(rows)} 件；此处 mP/mS 是 ItemData 原始 id，未解析）----")
            for i, row in enumerate(rows, 1):
                ptr = row.get("ptr") or 0
                ids = ""
                if ptr:
                    pd = proc.read_uint(handle, ptr + 0x14, 4) or 0
                    fr = ipx.read_item_fields(handle, pd) if pd else {}
                    if fr:
                        ids = (f"  mP={fr['magic_prefix']} mS={fr['magic_suffix']}"
                               f" rP={fr['rare_prefix']} rS={fr['rare_suffix']}"
                               f" auto={fr['auto_prefix']}")
                print(f"  [{i:>3}] {(row.get('name') or '?')}"
                      f"  ({row.get('type_name') or '-'}/{row.get('code') or '-'})"
                      f"  txt={row.get('type')} ilvl={row.get('ilvl')}"
                      f"  fidx={row.get('file_index')}  ptr=0x{ptr:08X}{ids}")
            print()
            print("  --index N 看某一件的完整词缀+属性；--all 全看；--hover 看鼠标指着的那件。")
            return 0

        if args.index:
            if not (1 <= args.index <= len(rows)):
                print(f"[FAIL] 序号 {args.index} 越界（共 {len(rows)} 件）")
                return 1
            sel = [rows[args.index - 1]]
        else:
            sel = rows

        for i, row in enumerate(sel, 1):
            ptr = row.get("ptr") or 0
            if not ptr:
                continue
            rep = ipx.item_affix_report(handle, bases, ptr)
            tag = f"#{args.index}" if args.index else f"#{i}/{len(sel)}"
            title = (f"==== 物品 {tag}  {row.get('name') or '?'}"
                     f"  ({row.get('type_name') or '-'}/{row.get('code') or '-'})"
                     f"  名称来源={row.get('name_src') or '-'} ====")
            _print_item_props(rep, title, props, hover_text if args.hover else "")
    finally:
        proc.close(handle)
    return 0


def cmd_ground(args) -> int:
    """枚举地面上的物品（走房间邻近表，不依赖鼠标悬停）。

    输出按 §12「完整结构」约定：所有字段都打，失败也把 reason 打出来。
    """
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
    try:
        bases = off.collect_module_bases(handle)
        if "D2CLIENT" not in bases:
            print("未找到 D2Client.dll（确认已进游戏界面？）")
            return 1
        status = gm.in_game_status(handle, bases)
        namer = _names.UnitNamer(handle, bases)
        res = gm.enumerate_ground_items(handle, bases, namer=namer)
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{stamp}] ==== 地面物品枚举（房间邻近表，不依赖悬停）====")
        print(f"  在游戏中         = {status.get('in_game')}"
              f"    (状态码={_num(status.get('state_code'))})")
        print(f"  PlayerUnit       = {_num(res['player'], True, 8)}")
        # 入口是 pPath+0x1C（不是 pPlayer+0x1C，那是 pDrlgAct 会静默给 0 个房间）
        pp = proc.read_uint(handle, res["player"] + 0x2C, 4) if res["player"] else None
        print(f"  pPath (+0x2C)    = {_num(pp, True, 8)}")
        print(f"  pRoom1 (pPath+0x1C) = {_num(res['room1'], True, 8)}")
        print(f"  房间数 / 单元数  = {res['rooms']} / {res['units']}")
        print(f"  枚举结果         = {'成功' if res['ok'] else '未完成'}"
              f"    原因={res['reason'] or '-'}")
        items = res["items"]
        print(f"  ---- 地面物品（nLocation==0）共 {len(items)} 件 ----")
        if not items:
            print("  -    （地上没有物品，或上面的原因导致没枚举到）")
        for i, it in enumerate(items, 1):
            nm = it.get("name") or "-"
            print(f"  [{i}] UnitAny={_num(it.get('ptr'), True, 8)} "
                  f"unitId={_num(it.get('unit_id'), True)} "
                  f"txt={_num(it.get('type'))} 质量={_num(it.get('quality'))} "
                  f"ilvl={_num(it.get('ilvl'))} loc={_num(it.get('location'))} "
                  f"坐标=({_num(it.get('x'))},{_num(it.get('y'))}) "
                  f"名称={nm}"
                  + (f"  [{it['name_src']}]" if it.get("name_src") else ""))
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


def _num(v, hexa: bool = False, width: int = 0) -> str:
    """字段可能为 None（读不到），统一显示为 '-'。

    width 用于十六进制补零（指针统一 8 位，便于肉眼比对）。
    """
    if v is None:
        return "-"
    if hexa:
        return f"0x{v:0{width}X}" if width else f"0x{v:X}"
    return str(v)


def _print_item_display_name(handle, p: int, namer) -> None:
    """悬停到物品(type=4)时，拼出**完整显示名**：部件全列，每项都带出处。

    ★ 规范 §12：不裁剪、不隐藏 —— 拿不到的部件打 `-`，不因为"看起来没用"而少打。
    拼接规则见 `itemprops.ItemProps.display_name()`；这里只负责呈现，
    并且**同时给「空格连接 / 无空格」两种变体**，最终以游戏自绘的悬停文本框为准。
    """
    props = getattr(namer, "props", None)
    if props is None:
        print("  ---- 完整显示名（本帧跳过：词缀解析器不可用）----")
        return
    try:
        dn = props.display_name(p, getattr(namer, "itab", None))
    except Exception as e:  # noqa: BLE001  解析失败不能打断监听
        print(f"  ---- 完整显示名（解析异常，已忽略：{e!r}）----")
        return
    print("  ---- 完整显示名（程序按 D2 取名规则拼接；与上方悬停文本对照）----")
    print(f"  底材            = {dn.get('base') or '-'}    "
          f"[{dn.get('base_src') or '-'}]  代码={dn.get('code') or '-'}")
    print(f"  品质            = {dn.get('quality')} {dn.get('quality_cn')}"
          f"   归类={dn.get('kind') or '-'}")
    parts = dn.get("parts") or {}
    labels = [
        ("runeword", "符文之语名      "),
        ("quality_name", "暗金/套装名     "),
        ("magic_prefix", "魔法前缀        "),
        ("magic_suffix", "魔法后缀        "),
        ("rare_prefix", "稀有名字-前缀词 "),
        ("rare_suffix", "稀有名字-后缀词 "),
        ("auto_prefix", "自动前缀(第三段)"),
    ]
    for key, label in labels:
        pt = parts.get(key)
        if not pt:
            continue
        if pt.get("row") is not None:
            where = f"行{pt['row']} {pt['zone']} id={pt['idx']}"
        else:
            where = pt.get("src") or "-"
        loc = pt.get("locale")
        print(f"  {label}= {pt.get('name') or '-'}"
              f"   (内部名={pt.get('internal') or '-'} locale={loc if loc is not None else '-'}"
              f"  {where})")
    print(f"  完整名(主推)    = {dn.get('full') or '-'}")
    print(f"  完整名(备选)    = {dn.get('alt') or '-'}")
    print(f"  完整名(无空格)  = {dn.get('full_tight') or '-'}")
    for n in dn.get("notes") or []:
        print(f"  注              = {n}")


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
    if t == 4 and namer is not None:
        # ★ 2026-09-20 老大要求：鼠标指向物品时直接给出**完整名**（接进菜单 16 hover --watch）
        _print_item_display_name(handle, p, namer)


def _print_hover_frame(handle, u: dict, namer) -> None:
    """完整打印一次采样的「悬停对象结构」——所有字段一律输出，空值显式打 `-`。

    ⚠️ 2026-09-20 踩过：`gm` 只在 `_dump_hover` 里局部导入，本函数直接用会
    `NameError: name 'gm' is not defined`（报错快照抓到）。需要 game 模块就先导入。

    ★★ 约定（2026-09-20 老大）：**不显示 ≠ 没读到**，禁止因"觉得没意义"而裁剪字段。
    历史教训：悬停文本原先只在 `HoverFlag=1` 的分支里打印，结果明明读到了
    `融解药` 却被藏住，反被当成地址错误、白查一轮。所以这里：
      · D2WIN 侧观测量（开关 / 框坐标 / 文本）**不看门控，永远打**；
      · D2CLIENT 侧四个原始值（含两个已判定的标记位）**永远打**；
      · 判定结果、单位详情缺失时打 `-`，让人一眼分清「读到空」和「没读」。
    """
    from d2h.acquire import game as gm

    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] ==== 悬停对象完整结构 ====")
    # ---- 沿触发：本次是因哪个标记跳变而取样的 ----
    trg = u.get("trigger")
    if trg == "ptr":
        old, new = u.get("ptr_change") or ({}, {})
        print(f"  触发来源         = ptr（{gm.HOVER_TRIGGER_DESC.get('ptr', '-')}）")
        print(f"    view_item {_num(old.get('view_item'), True, 8)}"
              f" -> {_num(new.get('view_item'), True, 8)}   "
              f"hover_id {_num(old.get('hover_id'), True)}"
              f" -> {_num(new.get('hover_id'), True)}   "
              f"type {_num(old.get('hover_type'))}"
              f" -> {_num(new.get('hover_type'))}")
    elif trg and trg != "基线":
        prev, cur = u.get("edge") or (None, None)
        print(f"  触发标记         = {trg}（{gm.HOVER_TRIGGER_DESC.get(trg, '-')}）"
              f"  {_num(prev)} -> {_num(cur)}")
    elif trg:
        print("  触发标记         = 基线（首帧，全链取一次）")
    mk = u.get("marks") or {}
    print(f"  标记 ground(0x11C2F8)={_num(mk.get('ground'))}   "
          f"unit(0xCA664)={_num(mk.get('unit'))}   "
          f"npc(0x11C2F4)={_num(mk.get('npc'))}")
    # ---- D2WIN 侧：与单位指针无关的原始观测量 ----
    print(f"  D2WIN+0xCA664    HoverFlag        = {_num(u.get('flag'))}"
          "    (⚠️ 实测地面物品悬停时也可为 0，不作判据，仅供对照)")
    print(f"  D2WIN+0xCA658    框坐标 x         = {_num(u.get('hx'))}")
    print(f"  D2WIN+0xCA65C    框坐标 y         = {_num(u.get('hy'))}")
    txt = u.get("text") or ""
    print(f"  D2WIN+0xC9E58    悬停文本         = {txt or '-'}"
          "    (游戏此刻画出的那行字，不依赖任何指针)")
    # ---- D2CLIENT 侧 ----
    ut = u.get("hover_type")
    tname = f" {UNIT_TYPE_NAME.get(ut, '未知类型')}" if ut is not None else ""
    print(f"  D2CLIENT+0x119638 HoverUnitId     = {_num(u.get('hover_id'), True)}")
    print(f"  D2CLIENT+0x11964C HoverUnitType   = {_num(ut)}{tname}")
    print(f"  D2CLIENT+0x11C2F4 SelFlag         = {_num(u.get('sel_ptr'))}"
          "    (已判定：标记位，不是指针)")
    print(f"  D2CLIENT+0x11C2F8 SelFlag2        = {_num(u.get('sel2_ptr'))}"
          "    (已判定：标记位，不是指针)")
    print(f"  D2CLIENT+0x11BC38 CurrentViewItem = {_num(u.get('view_item'), True, 8)}")
    ui = u.get("ui") or []
    print(f"  当前打开面板     = {'/'.join(ui) if ui else '-'}"
          "    (仅提示，2026-09-20 起不再阻断解析)")
    # ---- 判定结果 ----
    # ★ 规范 §3.7「禁止推测游戏内状态」：原始值在上面，下面是**程序推断**，
    #   每行都必须带依据（如 HoverFlag=0），便于用户实机对照校验后反馈。
    print("  ---- 判定（程序推断，依据见各行括号内）----")
    print(f"  来源             = {u.get('source') or '-'}")
    if u.get("left"):
        print("  => 该路径标记回落（非 0 -> 0）：判为**已移开**，"
              "下方单位值是这一帧读到的原始值，仅供参考")
    p = u.get("ptr")
    if not p:
        print("  UnitAny          = -    （本次没取到单位指针）")
        if txt:
            print("  => 无单位指针但悬停文本非空：以文本为准"
                  "（地面物品名文本框 / UI 内短名等场景）")
        stale = u.get("stale")
        if stale and stale.get("ptr"):
            nm = ""
            try:
                nm, _src = namer.name(stale["ptr"], stale.get("unit_type"),
                                      stale.get("txt"))
            except Exception:  # noqa: BLE001
                nm = ""
            print(f"  [旧值对照] 若不做门控会解析成 UnitAny=0x{stale['ptr']:08X} "
                  f"类型={_num(stale.get('unit_type'))} txt={_num(stale.get('txt'))} "
                  f"名称={nm or '-'}")
            print("             ^ 仅供对照（--gate 开启时判定不采信）；"
                  "默认无门控时这行不会出现")
        return
    print(f"  UnitAny          = 0x{p:08X}")
    _dump_hover(handle, p, namer)


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
    interval = getattr(args, "interval", 0.15) or 0.15
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
        gate = getattr(args, "gate", False)
        trigger = not getattr(args, "no_trigger", False)
        print("（★ 2026-09-20 起**默认不做门控**：实测鼠标悬停地面物品时 "
              "D2WIN+0xCA664 HoverFlag = 0，而 HoverUnitId/Type 反查出的单位是对的 "
              "—— 门控会把真值屏蔽成空，故该位现在只作读数打印；加 --gate 恢复旧行为）")
        if gate:
            print("（当前 --gate 已开：flag=0 即判「无悬停对象」，不解析单位）")
        if trigger:
            print("（★ 沿触发：**两个标记一起判，谁跳变就从谁那条路取一次**"
                  " —— `ground`=D2CLIENT+0x11C2F8 地面物品；`unit`=D2WIN+0xCA664 "
                  "NPC/物件/UI 内物品。都没跳变就不刷新 ⇒ 移开后不会残留上一个对象；"
                  "标记回落（1->0）判为已移开。`--no-trigger` 退回每帧都取）")
            print("（★ 第三路 `ptr`：两个标记**都没跳**但指针/单位标识变了也算真实变动 "
                  "（典型：从一个物品滑到另一个，标记恒 1 不跳，只有 CurrentViewItem/hover_id 变））")
        print("（输出 = 每次采样的完整结构：D2WIN 开关/框坐标/悬停文本 + D2CLIENT 四个原始值 + 判定；"
              "空值一律打 '-'，不做任何裁剪）")
        print(f"（采样间隔 {interval}s；任一字段变动即取一次完整结构并打印）")
        print("（2026-09-20 取消 UI 阻断：开着背包/仓库悬停 NPC、地面物品照样解析，"
              "面板名只作提示打印）")
        print("（按你的要求：**标记一变就取一次指针** —— flag 升降沿必然触发一次完整读数；"
              "`--raw` = 每帧都打，不加则只在任一字段变化时打）")
        print("（★ 规范 §3.7：本命令**只呈现读数**，不对游戏状态做主观推断；"
              "判定段每行都标了依据，请以实机校验为准，有出入直接反馈）")
        last_marks: dict[str, int | None] = {}
        last_ptrs: dict[str, int | None] = {}
        first = True       # 首帧必打（单次读数也总有输出）
        rc = 0
        limit = watch and getattr(args, "seconds", 30.0) and args.seconds > 0
        deadline = time.time() + getattr(args, "seconds", 30.0) if limit else 0
        while True:
            marks = gm.read_hover_marks(handle, bases)
            ptrs = gm.read_hover_ptrs(handle, bases)
            # 第三路触发：标记没跳，但指针/单位标识变了 => 也是真实变动
            ptr_changed = (not first) and last_ptrs is not None and ptrs != last_ptrs
            if first:
                # 首帧：全链取一次作基线（两条路都覆盖）
                frames: list[str | None] = [None]
            elif not trigger:
                # --no-trigger：退回旧行为，两条路每帧都取
                frames = ["unit", "ground"]
            else:
                # 沿触发：哪个标记跳变就从哪条路取；一个都没变 => 鼠标没换对象，不刷新
                # （`npc`=0x11C2F4 只作观测打印，不单独触发取样）
                frames = [k for k, v in marks.items()
                          if k != "npc" and v is not None and last_marks.get(k) != v]
                if not frames and ptr_changed:
                    frames = ["ptr"]
            if frames or getattr(args, "raw", False):
                if not frames:
                    print(f"[{datetime.now():%H:%M:%S}] 无标记跳变（未触发取样）")
                for k in frames:
                    # ptr / 基线 走全链；ground、unit 走各自路径
                    tk = None if k in (None, "ptr") else k
                    u = gm.read_hover_unit(handle, bases, gate=gate, trigger=tk)
                    u["marks"] = marks
                    u["trigger"] = k or "基线"
                    prev, cur = last_marks.get(k), marks.get(k)
                    u["edge"] = (prev, cur)
                    if k == "ptr":
                        u["ptr_change"] = (last_ptrs, ptrs)
                    # 下降沿（非 0 -> 0）= 该路径的标记回落，鼠标离开了它管的对象
                    if k and k != "ptr" and prev not in (None, 0) and not cur:
                        u["left"] = True
                    _print_hover_frame(handle, u, namer)
            # 每帧都要推进基线（否则没打印的帧会让下一帧误判"又变了"）
            last_marks = marks
            last_ptrs = ptrs
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
    fn = _HANDLERS.get(args.cmd)
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
    ("21", "地面物品枚举（房间邻近表，不依赖悬停）", ["ground"]),
    ("22", "物品词缀 + 属性解析（列出物品与原始词缀 id；命令行 props --index N / --all / --hover 看详情）",
     ["props"]),
    ("8", "状态码循环监控（3 秒一次：p 暂停 / Enter 立即读 / q 退出）",
     ["probe", "FOG+0x4AFE0,+0x8", "--loop", "--interval", "3", "--dump", "0", "--scan", "0"]),
    ("9", "查看临时目录", ["tmp"]),
    ("10", "清空临时目录", ["tmp", "--clean"]),
    ("11", "界面标记监听（0.3 秒轮询，界面切换才输出，Ctrl+C 结束）", ["watch"]),
    ("12", "游戏内 UI 面板监听（0.3 秒轮询，面板开关变化才输出）", ["watch", "--ui"]),
    ("13", "查看游戏内 UI 面板（一次性读数）", ["ui"]),
    ("14", "向游戏投递按键（i/q/c/t/esc，仅窗口消息不写内存）", None),
    ("15", "查看鼠标指向的对象（NPC/怪物/物品，一次性读数；指向物品时给出**完整显示名**）",
     ["hover"]),
    ("16", "鼠标指向对象监听（0.15 秒轮询，无去抖；指向物品时实时给出**完整显示名**，Ctrl+C 结束）",
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
    ppp = sub.add_parser("props", help="物品词缀 + 属性解析（gpt 词缀表 / ItemStatCost / StatList，只读）")
    ppp.add_argument(
        "--target",
        default="loader",
        choices=list(process_targets()),
        help="目标类型: loader=D2loader.exe / game=game.exe",
    )
    ppp.add_argument("--index", type=int, default=0, help="只看第 N 件（1 基，序号同本命令列出的清单）")
    ppp.add_argument("--all", action="store_true", help="对全部物品出报告")
    ppp.add_argument(
        "--hover",
        action="store_true",
        help="对鼠标当前指向的物品出报告，同时打印游戏自绘的悬停文本框（用于对答案）",
    )
    gp = sub.add_parser("ground", help="枚举地面上的物品（房间邻近表，不依赖悬停）")
    gp.add_argument(
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
        "--interval", type=float, default=0.15,
        help="--watch / --scan 的轮询间隔秒数（默认 0.15）",
    )
    hp.add_argument(
        "--scan", action="store_true",
        help="差异扫描：持续采样并找出变成 UnitAny 指针的全局地址（需同时把鼠标移到对象上）",
    )
    hp.add_argument(
        "--raw", action="store_true",
        help="--watch 每帧都打印（不看变化），用于肉眼核对 Sel/Sel2/ViewItem 原始值",
    )
    hp.add_argument(
        "--no-trigger", action="store_true",
        help="关闭「沿触发」（默认开：两个标记谁跳变就从谁那条路取一次单位；"
             "都沒跳变则不刷新，避免移开后残留上一个对象）",
    )
    hp.add_argument(
        "--gate", action="store_true",
        help="开启 HoverFlag 门控（默认**关闭**：实测地面物品悬停时该位=0，"
             "门控会把正确结果屏蔽成空；仅供对照旧行为）",
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


# ★ 子命令 -> 处理函数的**唯一**映射表（2026-09-20 合并）。
# ⚠️ 历史教训：原先有两份（`_dispatch` 一份 + `main()` 里一条 if 链），新增 `ground`
#    时只加了前者 ⇒ 命令行跑它**静默 return 0、毫无输出**，极难发现。
#    现在 `_dispatch()` 与 `main()` 都只查这张表 ⇒ **新增命令只需改这里 + build_parser()**。
# ⚠️ 必须放在文件末尾（要引用下方定义的 cmd_menu 等，早了会 NameError）。
_HANDLERS = {
    "info": cmd_info,
    "find": cmd_find,
    "snap": cmd_snap,
    "state": cmd_state,
    "items": cmd_items,
    "ground": cmd_ground,
    "props": cmd_props,
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


def main(argv=None) -> int:
    logfile = setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        fn = _HANDLERS.get(args.cmd)
        return fn(args) if fn is not None else 0
    except Exception as e:  # 顶层兜底，友好退出，不吐堆栈给用户
        LOGGER.exception("执行失败: %s", e)
        _auto_errsnap(e, argv if argv is not None else sys.argv[1:], args)
        return 2
    finally:
        if logfile is not None:
            LOGGER.info("本次日志已存档: %s", logfile)
        else:
            LOGGER.info("本次未落盘（D2H_LOG=0）")


if __name__ == "__main__":
    sys.exit(main())
