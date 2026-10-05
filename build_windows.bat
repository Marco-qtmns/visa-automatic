@echo off
setlocal
cd /d "%~dp0"
py -m pip install -r requirements.txt "pyinstaller>=6,<7"
if errorlevel 1 goto :error
py tools\build_windows.py
if errorlevel 1 goto :error
echo Installer ready: release\956A_Generator_Setup.exe
pause
exit /b 0
:error
echo Build failed. Check the error above; Inno Setup 6 is required.
pause
exit /b 1
