@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
set "PY=C:\Users\abps\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"
"%PY%" d2h\cli.py %*
endlocal
