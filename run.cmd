@echo off
rem JobHunt launcher — double-clickable.
rem Starts the web UI (http://127.0.0.1:8765). Closing this window stops it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
echo.
echo Server stopped.
pause
