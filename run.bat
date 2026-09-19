@echo off
setlocal
set "PY=C:\Users\abps\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

rem Keep this file pure ASCII: cmd parses .bat using the local codepage,
rem UTF-8 Chinese here would scramble the whole script (double-click flash-crash).
rem All Chinese UI text is rendered by Python instead: d2h/cli.py menu

rem Log source tag -> part of the log file name:
rem   logs\d2h_<timestamp>_run.txt
rem Every console output (print / logging / traceback) is tee'd into it,
rem see d2h/runlog.py. logs\latest.txt always points at the newest log.
rem D2H_LOG=0 disables file logging; D2H_LOG_MAX_MB=N changes the size cap.
set "D2H_LOG_SRC=run"

rem With args -> pass through to the single entry (e.g. run.bat info)
if not "%~1"=="" (
  "%PY%" d2h\cli.py %*
  goto end
)

rem Without args -> interactive Chinese menu, rendered and looped by Python
"%PY%" d2h\cli.py menu

:end
if exist "logs\latest.txt" echo Log file: logs\latest.txt   (all output above is saved)
endlocal
