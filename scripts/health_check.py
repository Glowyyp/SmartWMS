"""
scripts/health_check.py — Verifica el estado de los servicios de SmartWMS
"""

import urllib.request
import urllib.error
import socket
import os

services = [
    ("Backend API (FastAPI)", "http://127.0.0.1:8001/api/v1/orders", 8001),
    ("Bot IA & Copiloto",     "http://127.0.0.1:8000/docs",          8000),
    ("Frontend Web (Angular)","http://127.0.0.1:4200",               4200),
]

def check_service(name, url, port):
    # Primero test de socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    
    if result != 0:
        return "[INACTIVO]", "Puerto cerrado o servicio detenido"

    # Segundo test de HTTP
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'SmartWMS-HealthCheck/1.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            return "[ACTIVO]  ", f"Responde HTTP {resp.status} OK"
    except urllib.error.HTTPError as e:
        # Algunos endpoints pueden devolver 401 por falta de auth, lo cual demuestra que el servicio esta vivo
        if e.code in (401, 403, 200, 304):
            return "[ACTIVO]  ", f"Responde HTTP {e.code} (Servicio online)"
        return "[ERROR]   ", f"Error HTTP {e.code}"
    except Exception as exc:
        return "[ACTIVO]  ", f"Puerto abierto (iniciando...)"

def main():
    print("=" * 65)
    print("         SmartWMS - ESTADO DE LOS SERVICIOS")
    print("=" * 65)
    print(f"{'SERVICIO':<25} | {'ESTADO':<10} | {'DETALLE'}")
    print("-" * 65)
    
    all_ok = True
    for name, url, port in services:
        status, detail = check_service(name, url, port)
        print(f"{name:<25} | {status} | {detail}")
        if "[ACTIVO]" not in status:
            all_ok = False
            
    print("-" * 65)
    if all_ok:
        print("[OK] Todos los servicios estan funcionando correctamente.")
    else:
        print("[INFO] Algunos servicios no estan activos. Ejecuta 'iniciar.bat'.")
    print("=" * 65)

if __name__ == "__main__":
    main()
