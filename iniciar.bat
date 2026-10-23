@echo off
setlocal enabledelayedexpansion
title SmartWMS - Centro de Control
cd /d "%~dp0"

echo ====================================================================
echo                   SmartWMS - INICIANDO SISTEMA
echo ====================================================================
echo.

REM 1. Verificaciones previas de dependencias del entorno
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python no esta disponible en el PATH del sistema.
    echo Por favor ejecuta primero "instalar.bat" para configurar el entorno automaticamente.
    echo.
    pause
    exit /b 1
)

where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js no esta disponible en el PATH del sistema.
    echo Por favor ejecuta primero "instalar.bat" para configurar el entorno automaticamente.
    echo.
    pause
    exit /b 1
)

if not exist "ecommerce\frontend\smartwms-angular\node_modules" (
    echo [AVISO] No se detecto la carpeta node_modules del frontend web.
    echo Es necesario instalar las dependencias antes del primer inicio.
    echo Ejecutando instalar.bat ahora...
    call "instalar.bat"
)

REM 2. Archivo de configuracion .env y validacion de BD
if not exist ".env" (
    echo [INFO] Creando archivo de configuracion .env desde .env.example...
    copy ".env.example" ".env" >nul
    python scripts\init_db.py
)

REM 3. Detectar IP del servidor para conexiones locales y de red
echo [1/4] Detectando direccion IP de la maquina...
set SERVER_IP=
for /f "tokens=*" %%i in ('python scripts\get_ip.py 2^>nul') do set SERVER_IP=%%i
if "%SERVER_IP%"=="" set SERVER_IP=127.0.0.1
echo       IP del Servidor detectada: %SERVER_IP%

REM 4. Intentar habilitar puertos en Firewall de Windows (silencioso si no es admin)
echo.
echo [2/4] Verificando reglas de Firewall de Windows para red local...
netsh advfirewall firewall add rule name="SmartWMS-8001" dir=in action=allow protocol=TCP localport=8001 >nul 2>&1
netsh advfirewall firewall add rule name="SmartWMS-8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
netsh advfirewall firewall add rule name="SmartWMS-4200" dir=in action=allow protocol=TCP localport=4200 >nul 2>&1

REM 5. Comprobar disponibilidad de puertos
echo.
echo [3/4] Comprobando disponibilidad de puertos (8001, 8000, 4200)...
netstat -ano | findstr ":8001 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 echo       [AVISO] El puerto 8001 (Backend API) ya esta ocupado.

netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 echo       [AVISO] El puerto 8000 (Bot IA) ya esta ocupado.

netstat -ano | findstr ":4200 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 echo       [AVISO] El puerto 4200 (Angular) ya esta ocupado.

REM 6. Iniciar los 3 servicios en ventanas independientes
echo.
echo [4/4] Levantando servicios de SmartWMS...

echo   * [1/3] Iniciando Backend API (puerto 8001 con soporte MFA)...
cd /d "%~dp0ecommerce\backend"
start "SmartWMS - Backend API (8001)" cmd /k "python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"

echo   * [2/3] Iniciando Bot IA y Asistente Copiloto (puerto 8000)...
cd /d "%~dp0bot"
start "SmartWMS - Bot IA (8000)" cmd /k "python main.py"

echo   * [3/3] Iniciando Frontend Web Angular (puerto 4200)...
cd /d "%~dp0ecommerce\frontend\smartwms-angular"
start "SmartWMS - Frontend Angular (4200)" cmd /k "npm start"

cd /d "%~dp0"
ping 127.0.0.1 -n 3 >nul

cls
echo ====================================================================
echo                 SmartWMS - SISTEMA EN EJECUCION
echo ====================================================================
echo.
echo   La aplicacion esta disponible en las siguientes direcciones:
echo.
echo   * En ESTE computador (Localhost):
echo       - Panel Web (Supervisor / Operario): http://localhost:4200
echo       - Backend API y Docs (Swagger):       http://localhost:8001/docs
echo       - Bot Asistente IA:                  http://localhost:8000
echo.
echo   * Desde OTRO computador, celular o tablet (Misma red WiFi / LAN):
echo       - Panel Web (Navegador):             http://%SERVER_IP%:4200
echo       - Backend API:                       http://%SERVER_IP%:8001
echo       - App Android Operario (Configurar): http://%SERVER_IP%:8001
echo.
echo ====================================================================
echo   CREDENCIALES DISPONIBLES (Autenticacion con MFA / TOTP):
echo ====================================================================
echo   - Supervisor:  supervisor@smartwms.com  /  supervisor123
echo   - Operario:    operario@smartwms.com    /  operario123
echo   - Admin:       admin@smartwms.com       /  admin123
echo.
echo   Nota: En el primer login, el sistema te solicitara escanear el QR
echo   con Google Authenticator, Microsoft Authenticator o Aegis.
echo ====================================================================
echo.
echo   Herramientas de gestion:
echo   - Para verificar el estado de salud:  estado.bat
echo   - Para cerrar todos los servidores:   detener.bat
echo.
echo Presiona cualquier tecla para minimizar este centro de control.
pause >nul
