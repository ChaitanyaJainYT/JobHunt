@echo off
rem JobHunt one-time setup — double-clickable launcher.
rem Runs setup.ps1 with a process-scoped policy bypass (nothing changed
rem on your system) and keeps the window open so you can read the result.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
