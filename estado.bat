@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title SmartWMS - Comprobacion de Estado y Salud del Sistema
cd /d "%~dp0"

echo =====================================================================
echo             SmartWMS - Verificacion de Estado de Servicios
echo =====================================================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python no esta instalado o no se encuentra en el PATH.
    echo Por favor ejecuta instalar.bat para preparar el entorno.
    echo.
    pause
    exit /b 1
)

python "%~dp0scripts\health_check.py"

echo.
echo Presiona cualquier tecla para cerrar esta ventana.
pause >nul
