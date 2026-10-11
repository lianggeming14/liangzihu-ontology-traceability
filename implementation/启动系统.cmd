@echo off
setlocal
cd /d "%~dp0"
"C:\ProgramData\anaconda3\python.exe" -X utf8 run_server.py --open-browser
if errorlevel 1 pause
