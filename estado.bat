@echo off
chcp 65001 >nul
title SmartWMS - Comprobación de Estado

echo =====================================================================
echo             SmartWMS - Verificación de Estado de Servicios
echo =====================================================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python no está instalado o no se encuentra en el PATH.
    echo Por favor instala Python 3.10+ para ejecutar esta verificación.
    echo.
    pause
    exit /b 1
)

python scripts\health_check.py

echo.
pause
