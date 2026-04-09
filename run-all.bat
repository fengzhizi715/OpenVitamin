@echo off
title Project Launcher

echo Starting Backend and Frontend...
echo.

:: Start Backend in new window
start "Backend" cmd /k "run-backend.bat"

:: Start Frontend in new window
start "Frontend" cmd /k "run-frontend.bat"

echo.
echo Both services started!
echo Close the windows to stop.
pause