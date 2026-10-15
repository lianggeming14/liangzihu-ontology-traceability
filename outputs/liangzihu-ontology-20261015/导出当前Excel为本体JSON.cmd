@echo off
setlocal
chcp 65001 >nul
call "%~dp0..\..\tools\ontology_export\导出本体JSON.cmd" "%~dp0梁子湖项目_本体与关系全量结构导出.xlsx" "%~dp0reviewed_packages"
echo.
echo 本操作仅离线生成和校验JSON，不写现有数据库。
pause
