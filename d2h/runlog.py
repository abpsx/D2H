#!/usr/bin/env python3
"""运行日志：把控制台的一切输出（``print()`` 与 ``logging``）同时落盘到 logs/。

为什么需要（2026-09-20 用户要求「bat 内所有打印调用都加上保存本地日志」）：
    cli.py 里绝大多数输出走 ``print()``，只有少量走 ``LOGGER``。原
    ``setup_logging()`` 只给 LOGGER 挂了 FileHandler ⇒ **满屏 print 一条都没落盘**，
    logs/ 里每个文件只有几百字节（只有启动/结束两行 INFO），排障时等于没有日志。
    本模块把 ``sys.stdout`` / ``sys.stderr`` 整体包成 :class:`Tee`，
    从此「屏幕上出现的」= 「盘里有的」。

结构（三者共用**同一个** :class:`Sink`，即同一份字节额度）::

    sys.stdout ─┐
    sys.stderr ─┴─> Tee ─┐
                         ├─> Sink ─> logs/d2h_<时间戳>_<src>.txt
    LOGGER ─> handler ───┘         （UTF-8 行缓冲，超限停写）

⚠️ 为什么 LOGGER 也要走 Sink（2026-09-20 实测发现的坑）：
    ``watch`` 类命令（`cmd_watch` / `watch --ui`）的输出**全部走 LOGGER**。若 logging
    的 handler 直接写原始文件句柄，就会绕过上限 —— 上限形同虚设，长跑一晚上照样
    能把盘写满。所以 handler 的 stream 必须是 Sink 本身。

硬约束（规范 §12 输出约定 / §16 临时文件）：
    · 只写项目内 logs/（``paths.LOGS``），**禁止**写系统临时目录；
    · 文件一律 UTF-8，与控制台代码页无关（控制台 GBK 只影响控制台）；
    · 控制台字节原样透传，**绝不吞输出、绝不改内容**（§12 的老教训）；
    · 日志设施自身故障**不能**让程序崩，也不能掩盖原逻辑 —— 只告警一次并停写盘。

命名 / 开关（bat 内设置环境变量）::

    logs/d2h_<时间戳>_<src>.txt   src = D2H_LOG_SRC（run / watch / uiwatch / agent / cli）
    logs/latest.txt               永远指向「最近一次」日志（bat 结尾提示用）
    D2H_LOG=0                     关闭落盘（批量抓取时用，免得刷出一堆空文件）
    D2H_LOG_MAX_MB=8              单文件上限，超限停写文件并告警一次

⚠️ 安装顺序有讲究，见 :func:`install`：必须**先**让 logging 的 StreamHandler
   捕获原始 stdout，**再**把 ``sys.stdout`` 换成 Tee。反了的话 LOGGER 的输出会经
   Tee 二次落盘（同一行在文件里出现两遍）。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ENV_ON = "D2H_LOG"
ENV_SRC = "D2H_LOG_SRC"
ENV_MAX = "D2H_LOG_MAX_MB"

DEFAULT_SRC = "cli"
DEFAULT_MAX_MB = 8.0

#: 指向「最近一次日志」的固定文件名（bat 结尾只需提示这个路径）
LATEST_NAME = "latest.txt"


# --------------------------------------------------------------------------- #
# 环境开关
# --------------------------------------------------------------------------- #
def enabled() -> bool:
    """落盘总开关：``D2H_LOG`` 为 0/off/false/no 时关闭。"""
    raw = (os.environ.get(ENV_ON) or "").strip().lower()
    return raw not in ("0", "off", "false", "no")


def source_tag() -> str:
    """日志文件名里的来源标签（来自 D2H_LOG_SRC，bat 内设置）。"""
    raw = (os.environ.get(ENV_SRC) or "").strip() or DEFAULT_SRC
    keep = "".join(c for c in raw if c.isalnum() or c in "-_")
    return (keep or DEFAULT_SRC)[:16]


def max_bytes() -> int:
    """单文件字节上限（D2H_LOG_MAX_MB，默认 8 MiB）。"""
    raw = (os.environ.get(ENV_MAX) or "").strip()
    try:
        mb = float(raw) if raw else DEFAULT_MAX_MB
    except ValueError:
        mb = DEFAULT_MAX_MB
    if mb <= 0:
        mb = DEFAULT_MAX_MB
    return int(mb * 1024 * 1024)


def new_path(logs_dir) -> Path:
    """本次运行的日志路径：``logs/d2h_<时间戳>_<src>.txt``。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(logs_dir) / f"d2h_{ts}_{source_tag()}.txt"


def open_stream(path):
    """以 UTF-8 **行缓冲**打开日志流（与 Sink 共用同一句柄）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return open(p, "a", encoding="utf-8", buffering=1)


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
def _emergency(stream, msg: str) -> None:
    """往「不可再失败的」通道打一行告警（写不进去也只能咽下）。"""
    try:
        if stream is not None:
            stream.write(msg + "\n")
            stream.flush()
    except Exception:  # noqa: BLE001  告警失败绝不能掩盖原错误
        pass


def _warn_console(msg: str) -> None:
    """告警打到**真实终端**（``sys.__stdout__``）。

    刻意不用 ``sys.stdout``：它此刻已是 Tee，且抓取场景下可能是 StringIO，
    告警不该混进被抓取的正文里。
    """
    _emergency(getattr(sys, "__stdout__", None), msg)


class Sink:
    """带额度控制的文件写入器 —— Tee 与 logging handler **共用同一个实例**。

    行为：
      · 达到上限（``D2H_LOG_MAX_MB``，默认 8 MiB）后**停写文件**、告警一次，
        控制台输出照常（宁可少存档，也不能把盘写满）；
      · 写盘失败同样只告警一次并停写，绝不上抛（日志设施故障不得影响观测逻辑）；
      · 每行 flush —— 进程被 Ctrl+C / 被杀，最后一行也已落盘。
    """

    __slots__ = ("_stream", "_label", "limit", "used", "capped", "failed", "_warn")

    def __init__(self, stream, limit: int, label: str = "log", warn=None) -> None:
        self._stream = stream
        self._label = label
        self.limit = limit
        self.used = 0
        self.capped = False
        self.failed = False
        self._warn = warn

    # ---- 主入口 ----
    def write(self, text: str) -> None:
        if self._stream is None or self.capped or self.failed:
            return
        if not isinstance(text, str):
            text = str(text)
        try:
            size = len(text.encode("utf-8", "replace"))
            if self.used + size > self.limit:
                self.capped = True
                self._stream.write(
                    f"\n[{self._label}] log size limit reached ({self.limit} bytes, "
                    f"see D2H_LOG_MAX_MB); file writing stopped, console output "
                    f"continues.\n"
                )
                self._stream.flush()
                self._alert(
                    f"[WARN] log file size limit reached ({self.limit} bytes); "
                    f"file writing stopped (raise D2H_LOG_MAX_MB for more)."
                )
                return
            self.used += size
            self._stream.write(text)
            self._stream.flush()
        except Exception as exc:  # noqa: BLE001
            self.failed = True
            self._alert(f"[WARN] log write failed, file logging disabled: {exc!r}")

    def _alert(self, msg: str) -> None:
        if self._warn is not None:
            self._warn(msg)

    # ---- 文件对象接口（logging.StreamHandler 会用到 write / flush）----
    def flush(self) -> None:
        try:
            if self._stream is not None:
                self._stream.flush()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        self.flush()  # 真正的句柄归调用方管，这里只冲缓冲

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    @property
    def encoding(self):
        return "utf-8"

    @property
    def errors(self):
        return "replace"

    @property
    def closed(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return f"<d2h-log {self._label}>"


class Tee:
    """把写入转发给「日志 Sink + 控制台」。

    · **先写文件，后写控制台** —— 控制台若因 GBK 抛 ``UnicodeEncodeError``，
      盘里仍留有完整内容（原行为是屏幕炸 + 什么也没留下）。
    · 返回值与异常跟原对象一致，绝不吞输出、不裁剪内容。
    """

    __slots__ = ("_console", "_sink", "_label")

    def __init__(self, console, sink: Sink, label: str) -> None:
        self._console = console
        self._sink = sink
        self._label = label

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        self._sink.write(text)             # 先落盘（这里是不会抛的）
        return self._console.write(text)   # 再上屏；异常照抛，与未包装时一致

    def flush(self) -> None:
        for s in (self._sink, self._console):
            try:
                if s is not None:
                    s.flush()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        self.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._console, "isatty", lambda: False)())

    def fileno(self):
        return self._console.fileno()

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def reconfigure(self, **kw):
        fn = getattr(self._console, "reconfigure", None)
        if fn is not None:
            fn(**kw)

    @property
    def encoding(self):
        return getattr(self._console, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._console, "errors", "replace")

    @property
    def newlines(self):
        return getattr(self._console, "newlines", None)

    @property
    def closed(self) -> bool:
        return False

    @property
    def name(self):
        return getattr(self._console, "name", "<stream>")


def make_sink(stream, label: str = "log") -> Sink:
    """建一个带额度控制的落盘 Sink（``label`` 只出现在告警里）。"""
    return Sink(stream, max_bytes(), label=label, warn=_warn_console)


def install(sink: Sink) -> tuple[Tee, Tee]:
    """把 ``sys.stdout`` / ``sys.stderr`` 换成 Tee（共用同一个 Sink）。

    ⚠️ 调用时机：必须在 logging 的 StreamHandler **捕获原始 stdout 之后**再调用，
    否则 LOGGER 的输出会经 Tee 二次落盘。见 ``cli.setup_logging()``。
    """
    out = Tee(sys.stdout, sink, "stdout")
    err = Tee(sys.stderr, sink, "stderr")
    sys.stdout, sys.stderr = out, err
    return out, err


def write_header(stream, argv=None) -> None:
    """写文件头元信息（只进文件，不进控制台）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    args = list(sys.argv if argv is None else argv)
    block = "\n".join(
        [
            "=" * 72,
            f"D2H run log | {ts}",
            f"src    = {source_tag()}   (D2H_LOG_SRC)",
            f"argv   = {' '.join(args)}",
            f"cwd    = {os.getcwd()}",
            f"python = {sys.version.split()[0]}   ({sys.executable})",
            f"limit  = {max_bytes()} bytes   (D2H_LOG_MAX_MB)",
            "=" * 72,
            "",
        ]
    )
    try:
        stream.write(block)
        stream.flush()
    except Exception:  # noqa: BLE001  头部失败不影响正文
        pass


def write_latest(logs_dir, path) -> Path:
    """``logs/latest.txt`` 永远指向最近一次日志（bat 结尾提示用）。"""
    ptr = Path(logs_dir) / LATEST_NAME
    try:
        ptr.parent.mkdir(parents=True, exist_ok=True)
        ptr.write_text(str(path) + "\n", encoding="utf-8")
    except OSError:
        pass
    return ptr
