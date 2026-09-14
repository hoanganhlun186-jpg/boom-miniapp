@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m pip install -r requirements.txt
goto finish
:use_python
python -m pip install -r requirements.txt
:finish
pause
