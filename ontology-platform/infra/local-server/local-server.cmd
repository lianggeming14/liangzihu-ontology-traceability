@echo off
setlocal
set "LZO_ROOT=%~dp0..\.."
set "LZO_PY=%LZO_ROOT%\.venv-local-server\Scripts\python.exe"
if not exist "%LZO_PY%" (
  echo Python runtime missing. Run powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  pause
  exit /b 1
)
set "LZO_CONFIG=%LZO_ROOT%\.runtime\local-server\config.json"
if not "%LZO_LOCAL_CONFIG%"=="" set "LZO_CONFIG=%LZO_LOCAL_CONFIG%"
if "%~1"=="" (
  "%LZO_PY%" "%LZO_ROOT%\scripts\run_local_server.py" --config "%LZO_CONFIG%" start
  if errorlevel 1 (
    pause
    exit /b 1
  )
  "%LZO_PY%" "%LZO_ROOT%\scripts\run_local_server.py" --config "%LZO_CONFIG%" open
) else (
  "%LZO_PY%" "%LZO_ROOT%\scripts\run_local_server.py" --config "%LZO_CONFIG%" %*
)
endlocal
