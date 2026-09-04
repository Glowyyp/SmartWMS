@echo off
cd /d "%~dp0"
echo ===================================================
echo   Iniciando el servidor backend de SmartWMS...
echo ===================================================
echo.

cd bot

echo [1/2] Verificando e instalando dependencias (esto puede tardar un poco la primera vez)...
pip install --user -r requirements.txt
echo.

echo [2/2] Iniciando aplicacion principal...
echo Por favor, NO CIERRES ESTA VENTANA mientras usas la aplicacion.
echo.
python main.py

pause
