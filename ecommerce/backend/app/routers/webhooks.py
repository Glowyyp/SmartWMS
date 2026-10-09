"""
routers/webhooks.py — Endpoint receptor de webhooks de órdenes

Responsabilidades de este router:
  - Recibir el POST con el payload JSON
  - Pydantic valida automáticamente (422 si falla)
  - Verificar firma HMAC opcional (X-Webhook-Secret header)
  - Delegar procesamiento al order_service
  - Retornar respuestas HTTP semánticamente correctas
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.webhook import OrderWebhookPayload, WebhookResponse, WebhookErrorResponse
from app.services.order_service import (
    process_order,
    OrderAlreadyExistsError,
    ProductoNoEncontradoError,
    StockInsuficienteError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/webhooks",
    tags=["Webhooks"],
)

WEBHOOK_SECRET: str | None = os.getenv("WEBHOOK_SECRET")


# =============================================================================
# Dependencia: Verificación de firma HMAC (opcional pero recomendada)
# =============================================================================

def verify_webhook_signature(
    request: Request,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
) -> None:
    """
    Verifica la firma del webhook si WEBHOOK_SECRET está configurado.
    Comparación en tiempo constante (hmac.compare_digest) para evitar timing attacks.

    Si WEBHOOK_SECRET no está en .env, la verificación se omite (modo desarrollo).
    """
    if not WEBHOOK_SECRET:
        logger.debug("Verificación de firma omitida (WEBHOOK_SECRET no configurado)")
        return

    if x_webhook_secret is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header 'X-Webhook-Secret' requerido cuando WEBHOOK_SECRET está configurado.",
        )

    if not hmac.compare_digest(x_webhook_secret, WEBHOOK_SECRET):
        logger.warning("⛔ Intento de webhook con firma inválida")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Firma del webhook inválida. Acceso denegado.",
        )


# =============================================================================
# Endpoint principal
# =============================================================================

@router.post(
    "/orders",
    status_code=status.HTTP_202_ACCEPTED,  # 202: recibido y en proceso (semántica webhook)
    response_model=WebhookResponse,
    responses={
        202: {"description": "Orden recibida y procesada exitosamente"},
        400: {"model": WebhookErrorResponse, "description": "Error de negocio (stock, duplicado, SKU)"},
        401: {"description": "Header de autenticación faltante"},
        403: {"description": "Firma del webhook inválida"},
        422: {"description": "Payload inválido — fallo de validación Pydantic"},
    },
    summary="Recibir evento de orden creada",
    description=(
        "Endpoint receptor de webhooks de e-commerce. "
        "Procesa eventos `order.created`, valida el stock y registra la orden "
        "en la base de datos en una transacción atómica."
    ),
)
async def receive_order_webhook(
    payload: OrderWebhookPayload,
    db: Session = Depends(get_db),
    _: None = Depends(verify_webhook_signature),
) -> WebhookResponse:
    """
    Procesa un evento webhook de tipo 'order.created'.

    Flujo:
    1. FastAPI + Pydantic validan el JSON automáticamente → 422 si falla
    2. Se verifica la firma HMAC (opcional)
    3. Se delega al order_service para procesamiento transaccional
    4. Retorna 202 con el ID interno y estado de la orden
    """
    logger.info(
        "📦 Webhook recibido: event_type=%s order_id=%s customer=%s",
        payload.event_type,
        payload.order_id,
        payload.customer.email,
    )

    try:
        result = process_order(payload=payload, db=db)
        return result

    except OrderAlreadyExistsError as e:
        # 409 Conflict — idempotencia: retornamos 202 igual para no exponer info
        # Algunos sistemas usan 200 aquí también. Documentamos como 400 con detalle.
        logger.warning("Orden duplicada: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    except ProductoNoEncontradoError as e:
        logger.error("Producto no encontrado: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    except StockInsuficienteError as e:
        logger.error("Stock insuficiente: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    except Exception as e:
        # Error inesperado de BD u otro: loggear y no exponer detalles internos
        logger.exception("Error inesperado procesando webhook order_id=%s", payload.order_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al procesar la orden. Contacte al administrador.",
        )
