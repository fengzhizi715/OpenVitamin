@echo off
title Frontend

cd /d "%~dp0frontend"

if not exist node_modules (
    echo Installing dependencies...
    npm install
)

echo Starting Frontend...
npm run dev