@echo off
setlocal enabledelayedexpansion
title SmartWMS - Servidor para Dispositivo Movil / Operario
cd /d "%~dp0"

echo ====================================================================
echo   SmartWMS — Servidor Local para Celular / App Operario Android
echo ====================================================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python no esta disponible en el PATH del sistema.
    echo Por favor ejecuta primero "instalar.bat".
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [INFO] Creando archivo .env desde plantilla .env.example...
    copy ".env.example" ".env" >nul
    python scripts\init_db.py
)

REM Obtener IP local de la maquina dinamicamente
set LOCAL_IP=
for /f "tokens=*" %%a in ('python scripts\get_ip.py 2^>nul') do set LOCAL_IP=%%a
if "%LOCAL_IP%"=="" set LOCAL_IP=127.0.0.1

echo [INFO] IP detectada en tu red local / WiFi: %LOCAL_IP%
echo [INFO] Asegurate de que tu telefono este en la MISMA red WiFi o VPN (Tailscale).
echo.

REM Reglas de Firewall de Windows
echo [FIREWALL] Verificando puertos 8000 y 8001 en el firewall...
netsh advfirewall firewall add rule name="SmartWMS-8001" dir=in action=allow protocol=TCP localport=8001 >nul 2>&1
netsh advfirewall firewall add rule name="SmartWMS-8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1

REM Iniciar Backend API (puerto 8001)
echo.
echo [1/2] Iniciando Backend API (puerto 8001 con soporte MFA)...
cd /d "%~dp0ecommerce\backend"
start "SmartWMS Backend :8001" cmd /k "python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"

ping 127.0.0.1 -n 3 >nul

REM Iniciar Bot IA (puerto 8000)
echo [2/2] Iniciando Bot IA Copiloto (puerto 8000)...
cd /d "%~dp0bot"
start "SmartWMS Bot IA :8000" cmd /k "python main.py"

cd /d "%~dp0"

echo.
echo ====================================================================
echo                   SERVIDORES MOVILES ACTIVOS
echo ====================================================================
echo.
echo   * URL de la API:          http://%LOCAL_IP%:8001
echo   * Swagger Docs:           http://%LOCAL_IP%:8001/docs
echo   * Asistente Bot IA:       http://%LOCAL_IP%:8000
echo.
echo   CONFIGURACION EN LA APP ANDROID OPERARIO:
echo   1. Abre la app en tu telefono celular.
echo   2. En la pantalla de login, toca el icono de engranaje (Configuracion).
echo   3. En el campo 'URL del Servidor', escribe exactamente:
echo        http://%LOCAL_IP%:8001
echo   4. Guarda y vuelve a iniciar sesion (operario@smartwms.com / operario123).
echo   5. Ingresa el codigo de 6 digitos de tu app autenticadora (MFA).
echo ====================================================================
echo.
echo Presiona cualquier tecla para minimizar esta ventana.
echo (Las ventanas de los servidores continuaran ejecutandose).
pause >nul
