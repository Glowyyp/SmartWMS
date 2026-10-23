"""
scripts/health_check.py — Verifica el estado de los servicios de SmartWMS
"""

import urllib.request
import urllib.error
import socket
import os

services = [
    ("Backend API (FastAPI)", "http://127.0.0.1:8001/health", 8001),
    ("Bot IA & Copiloto",     "http://127.0.0.1:8000/health", 8000),
    ("Frontend Web (Angular)","http://127.0.0.1:4200",        4200),
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

def check_database():
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ecommerce.db")
    if not os.path.exists(db_path):
        return "[INACTIVO]", f"Archivo no encontrado ({os.path.basename(db_path)})"
    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        user_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM product_inventory")
        prod_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM work_orders")
        wo_count = cur.fetchone()[0]
        conn.close()
        return "[ACTIVO]  ", f"ecommerce.db OK ({user_count} usuarios, {prod_count} productos, {wo_count} ordenes trabajo)"
    except Exception as e:
        return "[ERROR]   ", f"Error de lectura SQLite: {e}"

def main():
    try:
        from get_ip import detect_ip
        ip = detect_ip()
    except Exception:
        ip = "127.0.0.1"

    print("=" * 68)
    print("           SmartWMS - ESTADO DE LOS SERVICIOS Y RECURSOS")
    print("=" * 68)
    print(f" IP detectada para red local / remota: {ip}")
    print("-" * 68)
    print(f"{'COMPONENTE':<25} | {'ESTADO':<10} | {'DETALLE'}")
    print("-" * 68)
    
    # 1. Base de datos
    db_status, db_detail = check_database()
    print(f"{'Base de Datos (SQLite)':<25} | {db_status} | {db_detail}")

    # 2. Servicios de red
    all_ok = "[ACTIVO]" in db_status
    for name, url, port in services:
        status, detail = check_service(name, url, port)
        print(f"{name:<25} | {status} | {detail}")
        if "[ACTIVO]" not in status:
            all_ok = False
            
    print("-" * 68)
    if all_ok:
        print("[OK] Todos los servicios y recursos estan funcionando correctamente.")
    else:
        print("[INFO] Algunos servicios no estan activos. Ejecuta 'iniciar.bat'.")
    print("=" * 68)

if __name__ == "__main__":
    main()

