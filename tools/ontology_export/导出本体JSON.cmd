@echo off
setlocal
chcp 65001 >nul
if "%~1"=="" (
  echo 用法: 导出本体JSON.cmd "工作簿.xlsx" ["输出目录"]
  echo 也可将工作簿拖到本文件；只离线导出，不导入数据库。
  exit /b 2
)
set "ONTOLOGY_EXPORT_RUNTIME=python"
if exist "%ProgramData%\anaconda3\python.exe" set "ONTOLOGY_EXPORT_RUNTIME=%ProgramData%\anaconda3\python.exe"
if defined ONTOLOGY_EXPORT_PYTHON set "ONTOLOGY_EXPORT_RUNTIME=%ONTOLOGY_EXPORT_PYTHON%"
if "%~2"=="" (
  "%ONTOLOGY_EXPORT_RUNTIME%" -B -X utf8 "%~dp0workbook_to_packages.py" "%~1"
) else (
  "%ONTOLOGY_EXPORT_RUNTIME%" -B -X utf8 "%~dp0workbook_to_packages.py" "%~1" --output-dir "%~2"
)
set "ONTOLOGY_EXPORT_EXIT=%ERRORLEVEL%"
if not "%ONTOLOGY_EXPORT_EXIT%"=="0" echo 校验未通过；请按工作表和行号修正。未导入数据库。
exit /b %ONTOLOGY_EXPORT_EXIT%
