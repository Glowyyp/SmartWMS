"""
main.py — FastAPI Application Factory para SmartWMS E-Commerce

Monta la aplicación, registra middlewares, routers y ejecuta tareas
de inicialización (crear tablas, seed de datos de prueba).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    level=logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO,
)
logger = logging.getLogger(__name__)


# =============================================================================
# Lifespan: inicialización y teardown de la app
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ejecuta tareas de inicio y limpieza de la aplicación.
    En FastAPI >= 0.93 reemplaza a on_event("startup").
    """
    logger.info("🚀 Iniciando SmartWMS E-Commerce API...")

    # Importar y crear tablas
    from app.database import create_tables
    create_tables()
    logger.info("✅ Tablas de BD verificadas/creadas")

    # Seed de datos de prueba (solo si inventario está vacío)
    from app.database import SessionLocal
    from app.services.order_service import seed_inventory
    with SessionLocal() as db:
        seed_inventory(db)

    yield  # La app corre aquí

    logger.info("🛑 Apagando SmartWMS E-Commerce API...")


# =============================================================================
# Instancia de FastAPI
# =============================================================================

app = FastAPI(
    title="SmartWMS E-Commerce API",
    description=(
        "API para recepción y procesamiento de órdenes de e-commerce via webhooks. "
        "Gestiona inventario con transacciones atómicas y es compatible con GCP Cloud SQL."
    ),
    version="1.0.0",
    docs_url="/docs",       # Swagger UI
    redoc_url="/redoc",     # ReDoc
    lifespan=lifespan,
)


# =============================================================================
# Middlewares
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        # Android emulator (10.0.2.2 apunta al localhost de la PC host)
        "http://10.0.2.2:4200",
        # Permitir cualquier origen local para desarrollo (Android device en la misma red)
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)


# =============================================================================
# Routers
# =============================================================================

from app.routers import webhooks  # noqa: E402
from app.routers import auth     # noqa: E402
from app.routers import inventory  # noqa: E402
from app.routers import users    # noqa: E402
from app.routers import orders   # noqa: E402
from app.routers import work_orders  # noqa: E402

app.include_router(webhooks.router)
app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(users.router)
app.include_router(orders.router)
app.include_router(work_orders.router)


# =============================================================================
# Endpoints de salud
# =============================================================================

@app.get("/health", tags=["Sistema"])
async def health_check():
    """Health check básico para Cloud Run / load balancers."""
    return {"status": "ok", "service": "smartwms-ecommerce", "version": "1.0.0"}


# =============================================================================
# Punto de entrada para ejecución directa
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8001")),
        reload=os.getenv("DEBUG", "false").lower() == "true",
    )
