# -*- coding: utf-8 -*-
"""把 cli 子命令的 stdout 抓成 UTF-8 文件（绕开 PowerShell 捕获中文乱码）。

背景：PowerShell 工具不回传 stdout，用 `| Out-File` 捕获时 cp936 与 UTF-8 打架，
中文会变成乱码甚至触发 UnicodeEncodeError。本脚本在 Python 内部 redirect_stdout
到 StringIO，再一次性写 UTF-8 文件，然后用 Read 工具读即可。

用法：
    python tools/capture.py ui
    python tools/capture.py hover --watch     # 会一直跑，需 Ctrl+C，慎用

结果写到 <项目根>/temp/ui_out.txt；异常 traceback 与退出码一并记录。
"""
import sys
import io
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d2h import cli  # noqa: E402

argv = sys.argv[1:] or ["ui"]
buf = io.StringIO()
old = sys.stdout
sys.stdout = buf
rc = 0
err = ""
try:
    cli.main(argv)
except SystemExit as e:  # argparse / cli 主动退出
    rc = e.code if isinstance(e.code, int) else 0
except BaseException:
    rc = 99
    err = traceback.format_exc()
finally:
    sys.stdout = old

out = ROOT / "temp" / "ui_out.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(buf.getvalue() + ("\n[EXC]\n" + err if err else ""), encoding="utf-8")
print(f"rc={rc}  ->  {out}")
sys.exit(0)
