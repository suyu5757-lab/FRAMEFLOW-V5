@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo FRAMEFLOW 工作台启动中...
echo 浏览器访问：http://localhost:8787
python server.py
