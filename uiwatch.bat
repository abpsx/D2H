@echo off
setlocal
set "PY=C:\Users\abps\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

rem Pure ASCII on purpose: cmd parses .bat with the local codepage,
rem UTF-8 Chinese here would scramble the script. Chinese UI text is
rem rendered by Python instead (d2h/cli.py watch --ui).

rem Watch in-game UI PANEL markers every 0.3s (multi-level pointer:
rem p = *(D2CLIENT.dll + 0x50D00), flags at p+off as 4-byte DWORDs).
rem Prints only when a panel opens/closes. Ctrl+C to stop.
rem Extra args are passed through, e.g.: uiwatch.bat --interval 1

rem Log source tag -> logs\d2h_<timestamp>_uiwatch.txt (see d2h/runlog.py).
rem Everything printed here is saved to that file; logs\latest.txt points
rem at the newest log.
set "D2H_LOG_SRC=uiwatch"

title D2H - in-game UI panel watcher (0.3s)
"%PY%" d2h\cli.py watch --ui %*

if exist "logs\latest.txt" echo Log file: logs\latest.txt   (all output above is saved)
endlocal
