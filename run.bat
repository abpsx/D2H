@echo off
setlocal
set "PY=C:\Users\abps\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

rem Keep this file pure ASCII: cmd parses .bat using the local codepage,
rem UTF-8 Chinese here would scramble the whole script (double-click flash-crash).
rem All Chinese UI text is rendered by Python instead: d2h/cli.py menu

rem With args -> pass through to the single entry (e.g. run.bat info)
if not "%~1"=="" (
  "%PY%" d2h\cli.py %*
  goto end
)

rem Without args -> interactive Chinese menu, rendered and looped by Python
"%PY%" d2h\cli.py menu

:end
endlocal
