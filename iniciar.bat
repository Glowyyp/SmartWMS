@echo off
setlocal enabledelayedexpansion
title SmartWMS - Centro de Control
cd /d "%~dp0"

echo ====================================================================
echo                   SmartWMS - INICIANDO SISTEMA
echo ====================================================================
echo.

REM 1. Verificar si existe .env, si no crearlo
if not exist ".env" (
    echo [INFO] Creando archivo de configuracion .env desde .env.example...
    copy ".env.example" ".env" >nul
)

REM 2. Detectar IP del servidor
echo [1/4] Detectando direccion IP de la maquina...
for /f "tokens=*" %%i in ('python scripts\get_ip.py 2^>nul') do set SERVER_IP=%%i
if "%SERVER_IP%"=="" set SERVER_IP=127.0.0.1
echo       IP del Servidor detectada: %SERVER_IP%

REM 3. Intentar habilitar puertos en Firewall de Windows (silencioso si no es admin)
echo.
echo [2/4] Verificando reglas de Firewall de Windows...
netsh advfirewall firewall add rule name="SmartWMS-8001" dir=in action=allow protocol=TCP localport=8001 >nul 2>&1
netsh advfirewall firewall add rule name="SmartWMS-8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
netsh advfirewall firewall add rule name="SmartWMS-4200" dir=in action=allow protocol=TCP localport=4200 >nul 2>&1

REM 4. Verificar puertos en uso
echo.
echo [3/4] Comprobando disponibilidad de puertos (8001, 8000, 4200)...
netstat -ano | findstr ":8001 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 echo       [AVISO] El puerto 8001 ya tiene un proceso escuchando.

netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 echo       [AVISO] El puerto 8000 ya tiene un proceso escuchando.

netstat -ano | findstr ":4200 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 echo       [AVISO] El puerto 4200 ya tiene un proceso escuchando.

REM 5. Iniciar los 3 servicios en ventanas independientes
echo.
echo [4/4] Levantando servicios...

echo   -> [1/3] Iniciando Backend API (puerto 8001)...
start "SmartWMS - Backend API (8001)" cmd /k "cd /d "%~dp0ecommerce\backend" && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"

echo   -> [2/3] Iniciando Bot IA y Chatbot (puerto 8000)...
start "SmartWMS - Bot IA (8000)" cmd /k "cd /d "%~dp0bot" && python main.py"

echo   -> [3/3] Iniciando Frontend Web Angular (puerto 4200)...
start "SmartWMS - Frontend Angular (4200)" cmd /k "cd /d "%~dp0ecommerce\frontend\smartwms-angular" && npm start"

timeout /t 3 /nobreak >nul

cls
echo ====================================================================
echo                 SmartWMS - SISTEMA EN EJECUCION
echo ====================================================================
echo.
echo   La aplicacion esta disponible en las siguientes direcciones:
echo.
echo   * En ESTE computador (Local):
echo       - Panel Web (Supervisor/Operario): http://localhost:4200
echo       - Backend API (Documentacion):     http://localhost:8001/docs
echo       - Bot IA y Asistente:             http://localhost:8000
echo.
echo   * Desde OTRO computador, celular o tablet (Misma red / WiFi):
echo       - Panel Web (Navegador):          http://%SERVER_IP%:4200
echo       - Backend API:                    http://%SERVER_IP%:8001
echo       - App Android (Operario):         Configurar en la app: http://%SERVER_IP%:8001
echo.
echo ====================================================================
echo   CREDENCIALES POR DEFECTO PARA INICIAR SESION:
echo ====================================================================
echo   - Supervisor:  supervisor@smartwms.com  /  supervisor123
echo   - Operario:    operario@smartwms.com    /  operario123
echo   - Admin:       admin@smartwms.com       /  admin123
echo ====================================================================
echo.
echo   Para verificar la salud del sistema ejecuta: estado.bat
echo   Para cerrar todos los servidores ejecuta:    detener.bat
echo.
echo Presiona cualquier tecla para minimizar este centro de control.
pause >nul
