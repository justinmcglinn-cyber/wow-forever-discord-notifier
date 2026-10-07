@echo off
rem Builds dist\ForeverNotify.exe (a single file; no Python needed to run it).
cd /d "%~dp0"
py -3 -m pip install -r requirements-build.txt || goto :error
py -3 -m PyInstaller --noconfirm --clean --onefile --console --name ForeverNotify ^
    --add-data "config.example.toml;." --add-data "..\addon\ForeverNotify;addon\ForeverNotify" ^
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
