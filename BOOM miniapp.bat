@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 netshort_studio.py
goto finish
:use_python
python netshort_studio.py
:finish
if errorlevel 1 pause
