@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\python.exe -m pip install -e ".[test]"
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\ean8-server.exe %*
