@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set "PY=C:\Users\abps\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"

rem If args given, pass through directly (e.g. run.bat info / run.bat find --target game)
if not "%~1"=="" (
  "%PY%" d2h\cli.py %*
  goto end
)

:menu
cls
echo ====================================
echo          D2H Tool (read-only)
echo ====================================
echo 1. Project info (info)
echo 2. Find game PID [default D2loader.exe]
echo 3. Find game PID - choose target type
echo 4. Take snapshot (snap, game online)
echo 5. List snapshots (list)
echo 6. Parse snapshot (parse)
echo 7. Current item list (items, game online)
echo 8. Watch state code step-by-key (probe FOG+0x4AFE0,+0x8)
echo q. Quit
echo ====================================
set "CHOICE="
set /p CHOICE=Select [1-8/q]:
if "%CHOICE%"=="1" goto do_info
if "%CHOICE%"=="2" goto do_find
if "%CHOICE%"=="3" goto choose_target
if "%CHOICE%"=="4" goto do_snap
if "%CHOICE%"=="5" goto do_list
if "%CHOICE%"=="6" goto do_parse
if "%CHOICE%"=="7" goto do_items
if "%CHOICE%"=="8" goto do_probe
if /i "%CHOICE%"=="q" goto end
echo Invalid selection, try again.
goto menu

:do_info
call :run info
goto menu

:do_find
call :run find
goto menu

:do_snap
call :run snap
goto menu

:do_list
call :run list
goto menu

:do_parse
call :run parse
goto menu

:do_items
call :run items
goto menu

:do_probe
call :run probe "FOG+0x4AFE0,+0x8" --loop --interval 3 --dump 0 --scan 0
goto menu

:choose_target
cls
echo Target process type:
echo   l. D2loader.exe (default)
echo   g. game.exe
echo   x. Back to menu
set "T="
set /p T=Select [l/g/x]:
if /i "%T%"=="l" goto do_find_loader
if /i "%T%"=="g" goto do_find_game
if /i "%T%"=="x" goto menu
echo Invalid selection.
goto choose_target

:do_find_loader
call :run find --target loader
goto menu

:do_find_game
call :run find --target game
goto menu

:run
"%PY%" d2h\cli.py %*
echo.
echo [Press any key to return to menu]
pause >nul
goto :eof

:end
endlocal
