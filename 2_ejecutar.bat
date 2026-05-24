@echo off
title Logo Stamper
python main.py
if %errorlevel% neq 0 (
    echo.
    echo Ocurrio un error. Asegurate de haber corrido 1_instalar.bat primero.
    pause
)
