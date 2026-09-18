@echo off
setlocal
set "PY=C:\Users\abps\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

rem Pure ASCII on purpose: cmd parses .bat with the local codepage,
rem UTF-8 Chinese here would scramble the script. Chinese UI text is
rem rendered by Python instead (d2h/cli.py watch).

rem Watch the game UI-state marker every 0.3s, print only when it changes.
rem Ctrl+C to stop.

title D2H - UI state watcher (0.3s)
"%PY%" d2h\cli.py watch %*

endlocal
