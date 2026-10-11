@echo off
cd /d "%~dp0"
"C:\ProgramData\anaconda3\python.exe" -X utf8 tools\sync_to_github.py
if errorlevel 1 pause
