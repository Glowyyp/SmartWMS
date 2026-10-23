"""
scripts/get_ip.py — Obtiene la IP local real de la máquina para mostrarla en los scripts de inicio
"""

import socket
import os

def get_all_ips():
    """Retorna una lista ordenada de todas las IPs IPv4 válidas encontradas."""
    ips = []
    
    # 1. Chequear variable explícita SERVER_IP en .env o entorno
    env_ip = os.getenv("SERVER_IP")
    if not env_ip:
        env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("SERVER_IP=") and not line.startswith("#"):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val and val not in ("127.0.0.1", "localhost", "0.0.0.0"):
                                env_ip = val
                                break
            except Exception:
                pass
    if env_ip and env_ip not in ("127.0.0.1", "localhost", "0.0.0.0"):
        ips.append(env_ip)

    # 2. Probar conexión UDP saliente (detecta la interfaz con ruta por defecto)
    for probe_host in ('8.8.8.8', '1.1.1.1', '10.255.255.255', '192.168.1.255'):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe_host, 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                if ip not in ips:
                    ips.append(ip)
                break
        except Exception:
            continue

    # 3. Enumerar todas las interfaces asociadas al hostname local (offline friendly)
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            candidate = info[4][0]
            if candidate and not candidate.startswith("127.") and not candidate.startswith("169.254."):
                if candidate not in ips:
                    ips.append(candidate)
    except Exception:
        pass

    return ips

def detect_ip():
    ips = get_all_ips()
    if ips:
        # Priorizar IPs privadas típicas de red local (192.168, 10., 172.16-31, 100. Tailscale)
        for ip in ips:
            if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172.") or ip.startswith("100."):
                return ip
        return ips[0]
    return "127.0.0.1"

if __name__ == "__main__":
    import sys
    if "--all" in sys.argv:
        all_candidates = get_all_ips()
        print(", ".join(all_candidates) if all_candidates else "127.0.0.1")
    else:
        print(detect_ip())

