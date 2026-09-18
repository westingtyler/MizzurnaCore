@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
where python >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=python"
if not defined PYTHON_EXE if exist "C:\Python311\python.exe" set "PYTHON_EXE=C:\Python311\python.exe"

if not defined PYTHON_EXE exit /b 1

"%PYTHON_EXE%" "%~dp0mizzurna_one_click_rescue_v33.py"
exit /b
