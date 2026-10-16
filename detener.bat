@echo off
setlocal enabledelayedexpansion
title SmartWMS - Detener Servicios
cd /d "%~dp0"

echo ====================================================================
echo                 SmartWMS - DETENIENDO SERVICIOS
echo ====================================================================
echo.

set KILLED=0

REM 1. Puerto 8001 (Backend API)
echo [1/3] Verificando Backend API en puerto 8001...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8001 " ^| findstr "LISTENING"') do (
    echo       Cerrando proceso con PID: %%a...
    taskkill /F /PID %%a >nul 2>&1
    set /a KILLED+=1
)

REM 2. Puerto 8000 (Bot IA)
echo [2/3] Verificando Bot IA en puerto 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo       Cerrando proceso con PID: %%a...
    taskkill /F /PID %%a >nul 2>&1
    set /a KILLED+=1
)

REM 3. Puerto 4200 (Angular)
echo [3/3] Verificando Frontend Angular en puerto 4200...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":4200 " ^| findstr "LISTENING"') do (
    echo       Cerrando proceso con PID: %%a...
    taskkill /F /PID %%a >nul 2>&1
    set /a KILLED+=1
)

echo.
if !KILLED! gtr 0 (
    echo [OK] Todos los servicios de SmartWMS han sido detenidos correctamente.
) else (
    echo [INFO] No habia servidores de SmartWMS activos en este momento.
)

echo.
echo Presiona cualquier tecla para cerrar esta ventana.
pause >nul
