@echo off
cd /d "%~dp0"
py -3 -m forever_notify run %*
pause
