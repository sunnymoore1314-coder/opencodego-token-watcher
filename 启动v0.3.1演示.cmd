@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "OpenCode用量监测 v0.3.1" "D:\Python\pythonw.exe" "%~dp0main.py"
