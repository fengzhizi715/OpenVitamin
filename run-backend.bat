@echo off
title Backend

cd /d "%~dp0backend"

echo Starting Backend...
conda run -n ai-inference-platform --no-capture-output python main.py