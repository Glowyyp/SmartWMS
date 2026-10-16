"""
scripts/get_ip.py — Obtiene la IP local real de la máquina para mostrarla en los scripts de inicio
"""

import socket
import os

def detect_ip():
    # 1. Revisar si hay un archivo .env con SERVER_IP especificada manualmente
    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("SERVER_IP=") and not line.startswith("#"):
                        val = line.split("=", 1)[1].strip()
                        if val and val not in ("127.0.0.1", "localhost", "0.0.0.0"):
                            return val
        except Exception:
            pass

    # 2. Detectar IP activa en la interfaz de red local
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

if __name__ == "__main__":
    print(detect_ip())
