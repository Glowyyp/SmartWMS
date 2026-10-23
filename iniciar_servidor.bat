@echo off
cd /d "%~dp0"
echo ===================================================
echo   SmartWMS — Redirigiendo al Iniciador Principal
echo ===================================================
echo.
echo Ejecutando iniciar.bat para levantar todos los servicios...
echo.
call "%~dp0iniciar.bat"
