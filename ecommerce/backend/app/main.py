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
        "http://10.0.2.2:4200",
    ],
    # Permite acceso desde cualquier IP de la red local, VPN (Tailscale) o emulador
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
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
# Proxy para el Bot IA (puerto 8000)
# =============================================================================

import httpx
from fastapi import Request, Response

@app.post("/api/chat", tags=["Bot IA"])
async def proxy_chat(request: Request):
    """
    Proxy transparente hacia el Bot IA (puerto 8000).
    Permite que los clientes (Android, Web) que tengan configurado el puerto 8001
    puedan chatear con el bot sin necesidad de abrir puertos adicionales.
    """
    bot_url = os.getenv("BOT_URL", "http://127.0.0.1:8000/api/chat")
    body = await request.body()
    forward_headers = {}
    for h in ["authorization", "content-type"]:
        if h in request.headers:
            forward_headers[h] = request.headers[h]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(bot_url, content=body, headers=forward_headers)
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json"
            )
    except Exception as e:
        logger.error(f"Error al conectar con el servicio Bot en {bot_url}: {e}")
        return Response(
            content='{"response": "El servicio de Bot IA no está disponible temporalmente.", "reply": {"text": "El servicio de Bot IA no está disponible temporalmente."}}',
            status_code=503,
            media_type="application/json"
        )


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
