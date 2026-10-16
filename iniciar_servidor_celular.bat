@echo off
cd /d "%~dp0"
echo ===================================================
echo   SmartWMS — Servidor Local para Celular Fisico
echo ===================================================
echo.

REM Obtener IP local de la maquina dinamicamente (compatible con cualquier rango de IP: 192.168, 10.x, 172.x)
for /f "tokens=*" %%a in ('python scripts\get_ip.py 2^>nul') do set LOCAL_IP=%%a
if "%LOCAL_IP%"=="" (
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /R "IPv4"') do (
        if not defined LOCAL_IP set LOCAL_IP=%%a
    )
)
set LOCAL_IP=%LOCAL_IP: =%

echo [INFO] Tu IP en la red WiFi es: %LOCAL_IP%
echo [INFO] Asegurate de que tu celular este en la MISMA red WiFi.
echo.

REM Abrir puertos en el Firewall de Windows (requiere permisos de Admin)
echo [FIREWALL] Abriendo puertos 8000 y 8001...
netsh advfirewall firewall delete rule name="SmartWMS-8001" >nul 2>&1
netsh advfirewall firewall delete rule name="SmartWMS-8000" >nul 2>&1
netsh advfirewall firewall add rule name="SmartWMS-8001" dir=in action=allow protocol=TCP localport=8001 >nul 2>&1
netsh advfirewall firewall add rule name="SmartWMS-8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
echo [FIREWALL] Puertos 8000 y 8001 abiertos OK.
echo.

REM Iniciar el backend principal (puerto 8001) en ventana separada
echo [1/2] Iniciando Backend API (puerto 8001)...
cd /d "%~dp0ecommerce\backend"
start "SmartWMS Backend :8001" cmd /k "python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"

timeout /t 3 /nobreak >nul

REM Iniciar el bot (puerto 8000) en ventana separada
echo [2/2] Iniciando Bot IA (puerto 8000)...
cd /d "%~dp0bot"
start "SmartWMS Bot IA :8000" cmd /k "python main.py"

cd /d "%~dp0"

echo.
echo ===================================================
echo   SERVIDORES INICIADOS
echo ===================================================
echo.
echo   Backend API  -> http://%LOCAL_IP%:8001
echo   Bot IA       -> http://%LOCAL_IP%:8000
echo   Swagger API  -> http://%LOCAL_IP%:8001/docs
echo.
echo   En tu celular (misma WiFi):
echo   Instala el APK del flavor "device" generado con
echo   Build ^> Select Build Variant ^> deviceDebug
echo.
echo ===================================================
echo.
echo Presiona cualquier tecla para cerrar ESTA ventana.
echo (Las ventanas de los servidores seguiran corriendo)
pause >nul
