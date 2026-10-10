@echo off
rem Builds dist\ForeverNotify.exe (a single file; no Python needed to run it).
cd /d "%~dp0"
py -3 -m pip install -r requirements-build.txt || goto :error
rem Optional, never committed: baked_config.toml is built into the exe and used whenever
rem config.toml is missing, so a personal build works with no setup.
set BAKED=
if exist baked_config.toml (
    set BAKED=--add-data "baked_config.toml;."
    echo Including baked_config.toml ^(your webhooks are inside this exe; don't share it^)
)
rem Team webhooks: forever_notify\team_data.py (encrypted by make_team_hooks.py, committed) is
rem used by any config.toml without its own webhook_url, so teammates only pick their WoW folder.
if exist forever_notify\team_data.py echo Including encrypted team webhooks from forever_notify\team_data.py
py -3 -m PyInstaller --noconfirm --clean --onefile --console --name ForeverNotify ^
    --add-data "config.example.toml;." --add-data "..\addon\ForeverNotify;addon\ForeverNotify" %BAKED% ^
    --hidden-import forever_notify.team_data ^
    --exclude-module numpy --exclude-module tkinter ^
    ForeverNotify.py || goto :error
rem numpy/tkinter: optional Pillow extras we never use; numpy alone adds ~16 MB if it's installed.
copy /y config.example.toml dist\ >nul
echo.
echo Built dist\ForeverNotify.exe
exit /b 0
:error
echo Build failed.
exit /b 1
