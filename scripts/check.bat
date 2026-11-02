@echo off
setlocal
cd /d "%~dp0.."
.venv\Scripts\python.exe scripts/check_style.py
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\python.exe -m pytest tests/test_barcode.py -q
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\python.exe -m coverage run --branch --source=ean8_service.api -m pytest tests/test_api_mbt.py tests/test_execution_mbt.py -q
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\python.exe -m coverage report --fail-under=100
if errorlevel 1 exit /b %errorlevel%
.venv\Scripts\python.exe -m coverage html -d output/coverage
.venv\Scripts\python.exe -m coverage json -o output/coverage.json
