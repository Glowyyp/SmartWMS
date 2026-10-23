"""
core/env.py — Carga centralizada de configuración (.env)

Orden de prioridad (el primero que defina un valor NO vacío gana):
  1. Variables de entorno reales del proceso (p. ej. definidas por el .bat o el sistema)
  2. <raíz del proyecto>/.env            ← archivo de configuración central
  3. ecommerce/backend/.env             ← compatibilidad con instalaciones antiguas

Todas las rutas se calculan relativas a este archivo, por lo que el proyecto
funciona desde cualquier carpeta, unidad o usuario de Windows.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

# app/core/env.py → parents: [0]=core [1]=app [2]=backend [3]=ecommerce [4]=raíz
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(os.getenv("SMARTWMS_HOME") or Path(__file__).resolve().parents[4])
ROOT_ENV_FILE = PROJECT_ROOT / ".env"

_loaded = False


def load_project_env() -> None:
    """Carga los archivos .env una sola vez (idempotente)."""
    global _loaded
    if _loaded:
        return
    for env_file in (ROOT_ENV_FILE, BACKEND_DIR / ".env"):
        if not env_file.is_file():
            continue
        for key, value in dotenv_values(env_file).items():
            if value and not os.environ.get(key):
                os.environ[key] = value
    _loaded = True


def persist_env_value(key: str, value: str) -> bool:
    """
    Agrega KEY=valor al .env central si la clave no existe todavía.
    Se usa solo para generar automáticamente secretos faltantes en un PC nuevo.
    Devuelve True si se escribió el valor.
    """
    try:
        existing = ROOT_ENV_FILE.read_text(encoding="utf-8") if ROOT_ENV_FILE.exists() else ""
        for line in existing.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{key}=") and stripped.split("=", 1)[1].strip():
                return False
        lines = [ln for ln in existing.splitlines() if not ln.strip().startswith(f"{key}=")]
        lines.append(f"{key}={value}")
        ROOT_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False
