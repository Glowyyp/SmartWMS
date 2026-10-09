"""
routers/orders.py — Listado y consulta de Órdenes

GET /api/v1/orders           → Listar órdenes (filtrable por status)
GET /api/v1/orders/{id}      → Detalle de una orden con sus items
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.order import Order
from app.models.order_item import OrderItem
from app.routers.auth import get_current_user
from app.models.user import User

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/orders", tags=["Órdenes"])


# ─── Schemas de respuesta (inline para no contaminar schemas/webhook.py) ──────

class OrderItemOut(BaseModel):
    id: int
    sku: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: int
    external_order_id: str
    customer_id: str
    customer_name: str
    customer_email: str
    total: Decimal
    status: str
    received_at: datetime
    event_timestamp: datetime
    items: List[OrderItemOut] = []

    model_config = {"from_attributes": True}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[OrderOut],
    summary="Listar órdenes con filtro opcional por estado",
)
def list_orders(
    status: Optional[str] = Query(
        default=None,
        description="Filtrar por estado: received | processing | completed | failed | cancelled",
        examples={"completed": {"value": "completed"}},
    ),
    limit: int = Query(default=50, le=200, description="Máximo de registros a retornar"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Retorna las órdenes más recientes. Filtrable por status.
    Accesible por cualquier usuario autenticado (supervisor, operario, admin).
    """
    query = db.query(Order)
    if status:
        query = query.filter(Order.status == status)
    orders = query.order_by(Order.received_at.desc()).limit(limit).all()
    return orders


@router.get(
    "/{order_id}",
    response_model=OrderOut,
    summary="Detalle de una orden",
)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Retorna el detalle completo de una orden incluyendo todos sus items."""
    from fastapi import HTTPException, status as http_status
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Orden con id={order_id} no encontrada",
        )
    return order
