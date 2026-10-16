@echo off
setlocal enabledelayedexpansion
title SmartWMS - Instalador de Dependencias y Preparacion
cd /d "%~dp0"

echo ====================================================================
echo             SmartWMS - INSTALACION Y PREPARACION DEL SISTEMA
echo ====================================================================
echo.

REM 1. Verificar Python
echo [1/5] Verificando instalacion de Python...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python no esta instalado o no se encuentra en el PATH.
    echo Por favor instala Python 3.10 o superior desde https://www.python.org/
    echo Asegurate de marcar la casilla "Add python.exe to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo       Detectado: %%v OK.

REM 2. Verificar Node.js y npm
echo.
echo [2/5] Verificando instalacion de Node.js y npm...
node -v >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js no esta instalado o no se encuentra en el PATH.
    echo Por favor instala Node.js LTS (18 o superior) desde https://nodejs.org/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node -v') do echo       Detectado Node.js: %%v OK.
for /f "tokens=*" %%v in ('npm -v') do echo       Detectado npm:     v%%v OK.

REM 3. Crear archivo .env si no existe
echo.
echo [3/5] Verificando archivo de configuracion .env...
if not exist ".env" (
    echo       Creando .env a partir de .env.example...
    copy ".env.example" ".env" >nul
    echo       Archivo .env creado correctamente.
) else (
    echo       Archivo .env ya existe. Conservando configuracion actual.
)

REM 4. Instalar dependencias de Python
echo.
echo [4/5] Instalando dependencias de Backend y Bot IA (Python)...
echo       Instalando paquetes de Backend (FastAPI)...
python -m pip install -r "ecommerce\backend\requirements.txt" --quiet
if %ERRORLEVEL% neq 0 (
    echo [ADVERTENCIA] Ocurrio un aviso al instalar dependencias del Backend.
) else (
    echo       Dependencias de Backend instaladas correctamente.
)

echo       Instalando paquetes del Bot IA...
python -m pip install -r "bot\requirements.txt" --quiet
if %ERRORLEVEL% neq 0 (
    echo [ADVERTENCIA] Ocurrio un aviso al instalar dependencias del Bot.
) else (
    echo       Dependencias del Bot instaladas correctamente.
)

REM 5. Instalar dependencias de Node.js (Angular)
echo.
echo [5/5] Instalando dependencias del Frontend Web (Angular)...
cd /d "%~dp0ecommerce\frontend\smartwms-angular"
call npm install --silent
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Fallo npm install en el frontend. Revisa tu conexion a Internet.
    cd /d "%~dp0"
    pause
    exit /b 1
)
cd /d "%~dp0"
echo       Dependencias de Angular instaladas correctamente.

REM 6. Inicializar base de datos
echo.
echo [*] Verificando estructura de Base de Datos y usuarios iniciales...
python scripts\init_db.py
if %ERRORLEVEL% neq 0 (
    echo [ADVERTENCIA] Error al ejecutar inicializador de base de datos.
)

echo.
echo ====================================================================
echo        INSTALACION COMPLETADA EXITOSAMENTE
echo ====================================================================
echo  Ya puedes iniciar el sistema ejecutando: iniciar.bat
echo ====================================================================
echo.
pause
