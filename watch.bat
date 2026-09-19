@echo off
setlocal
set "PY=C:\Users\abps\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

rem Pure ASCII on purpose: cmd parses .bat with the local codepage,
rem UTF-8 Chinese here would scramble the script. Chinese UI text is
rem rendered by Python instead (d2h/cli.py watch).

rem Log source tag -> logs\d2h_<timestamp>_watch.txt (see d2h/runlog.py).
rem Everything printed here is saved to that file; logs\latest.txt points
rem at the newest log. Ctrl+C to stop.
set "D2H_LOG_SRC=watch"

title D2H - UI state watcher (0.3s)
"%PY%" d2h\cli.py watch %*

if exist "logs\latest.txt" echo Log file: logs\latest.txt   (all output above is saved)
endlocal
