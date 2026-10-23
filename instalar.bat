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
    echo [AVISO] Python no esta disponible en el PATH actual.
    echo Intentando detectar si winget esta disponible para instalacion automatica...
    where winget >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        echo Se detecto Windows Package Manager (winget).
        echo Instalando Python 3.12 LTS automaticamente...
        winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts;!PATH!"
    ) else (
        echo Descargando e instalando Python 3.12 via PowerShell...
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Write-Host 'Descargando instalador de Python...'; $wc=New-Object System.Net.WebClient; $wc.DownloadFile('https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe', '$env:TEMP\python_setup.exe'); Write-Host 'Instalando Python en silencio...'; Start-Process '$env:TEMP\python_setup.exe' -ArgumentList '/quiet PrependPath=1 SimpleInstall=1 Include_pip=1' -Wait; Remove-Item '$env:TEMP\python_setup.exe' -ErrorAction SilentlyContinue"
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts;!PATH!"
    )
)

python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] No se pudo encontrar ni instalar Python automaticamente.
    echo Por favor instala Python 3.10 o superior manualmente desde: https://www.python.org/
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
    echo [AVISO] Node.js no esta disponible en el PATH actual.
    where winget >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        echo Se detecto winget. Instalando Node.js LTS automaticamente...
        winget install --id OpenJS.NodeJS.LTS -e --silent --accept-package-agreements --accept-source-agreements
        set "PATH=%ProgramFiles%\nodejs;%APPDATA%\npm;!PATH!"
    ) else (
        echo Descargando e instalando Node.js LTS via PowerShell...
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Write-Host 'Descargando Node.js LTS...'; $wc=New-Object System.Net.WebClient; $wc.DownloadFile('https://nodejs.org/dist/v20.18.0/node-v20.18.0-x64.msi', '$env:TEMP\nodejs_setup.msi'); Write-Host 'Instalando Node.js...'; Start-Process 'msiexec.exe' -ArgumentList '/i $env:TEMP\nodejs_setup.msi /qn' -Wait; Remove-Item '$env:TEMP\nodejs_setup.msi' -ErrorAction SilentlyContinue"
        set "PATH=%ProgramFiles%\nodejs;%APPDATA%\npm;!PATH!"
    )
)

node -v >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js no esta instalado o no se encuentra en el PATH.
    echo Por favor instala Node.js LTS (version 18 o superior) desde: https://nodejs.org/
    echo Luego vuelve a ejecutar este instalador.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node -v') do echo       Detectado Node.js: %%v OK.
for /f "tokens=*" %%v in ('npm -v') do echo       Detectado npm:     v%%v OK.

REM 3. Crear y verificar archivo .env
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
echo       Instalando paquetes de Backend (FastAPI, TOTP pyotp, segno QR)...
python -m pip install -r "ecommerce\backend\requirements.txt" --quiet
if %ERRORLEVEL% neq 0 (
    echo [ADVERTENCIA] Hubo advertencias al instalar dependencias del Backend. Reintentando con verbose...
    python -m pip install -r "ecommerce\backend\requirements.txt"
) else (
    echo       Dependencias de Backend instaladas correctamente.
)

echo       Instalando paquetes del Bot IA...
python -m pip install -r "bot\requirements.txt" --quiet
if %ERRORLEVEL% neq 0 (
    echo [ADVERTENCIA] Hubo advertencias al instalar dependencias del Bot. Reintentando con verbose...
    python -m pip install -r "bot\requirements.txt"
) else (
    echo       Dependencias del Bot instaladas correctamente.
)

REM 5. Instalar dependencias de Node.js (Angular)
echo.
echo [5/5] Instalando dependencias del Frontend Web (Angular)...
cd /d "%~dp0ecommerce\frontend\smartwms-angular"
call npm install --silent
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Fallo npm install en el frontend. Reintentando con salida detallada...
    call npm install
    if !ERRORLEVEL! neq 0 (
        echo [ERROR] No se pudieron instalar las dependencias de Angular.
        cd /d "%~dp0"
        pause
        exit /b 1
    )
)
cd /d "%~dp0"
echo       Dependencias de Angular instaladas correctamente.

REM 6. Inicializar base de datos y migraciones MFA
echo.
echo [*] Verificando estructura de Base de Datos y migraciones de esquema MFA...
python scripts\init_db.py
if %ERRORLEVEL% neq 0 (
    echo [ADVERTENCIA] Error al ejecutar inicializador de base de datos.
)

echo.
echo ====================================================================
echo        INSTALACION COMPLETADA EXITOSAMENTE
echo ====================================================================
echo  El sistema esta listo. Puedes iniciarlo ejecutando:
echo       iniciar.bat
echo ====================================================================
echo.
pause
