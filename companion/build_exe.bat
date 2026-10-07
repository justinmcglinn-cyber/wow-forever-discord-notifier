@echo off
rem Builds dist\ForeverNotify.exe (a single file; no Python needed to run it).
cd /d "%~dp0"
py -3 -m pip install -r requirements-build.txt || goto :error
py -3 -m PyInstaller --noconfirm --clean --onefile --console --name ForeverNotify ^
    --add-data "config.example.toml;." ForeverNotify.py || goto :error
copy /y config.example.toml dist\ >nul
echo.
echo Built dist\ForeverNotify.exe
exit /b 0
:error
echo Build failed.
exit /b 1
