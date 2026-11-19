"""
routers/orders.py — Listado y consulta de Órdenes

GET /api/v1/orders           → Listar órdenes (filtrable por status)
GET /api/v1/orders/{id}      → Detalle de una orden con sus items
"""

from __future__ import annotations

import logging
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.inventory import ProductInventory
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.work_order import WorkOrder, WorkOrderItem
from app.routers.auth import get_current_user, require_supervisor_or_admin
from app.routers.work_orders import RESERVED_STATUSES
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
    product_name: Optional[str] = None
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
    payment_status: str = "pending"
    received_at: datetime
    event_timestamp: datetime
    items: List[OrderItemOut] = []

    model_config = {"from_attributes": True}


class OrderStatusUpdate(BaseModel):
    status: Literal["received", "processing", "rejected"]


class PrepareWorkOrderRequest(BaseModel):
    order_ref: str
    existing_quantities: Dict[str, int] = {}


class PreparedOrderItem(BaseModel):
    sku: str
    product_name: str
    quantity: int
    available_qty: int


class InsufficientStockItem(BaseModel):
    sku: str
    product_name: str
    requested: int
    available: int


class PrepareWorkOrderResponse(BaseModel):
    ok: bool
    order_id: int
    external_order_id: str
    customer_name: str
    items: List[PreparedOrderItem] = []
    insufficient_items: List[InsufficientStockItem] = []
    error_message: Optional[str] = None


def _serialize_orders_with_names(orders: List[Order], db: Session) -> List[OrderOut]:
    """Serializa órdenes adjuntando product_name desde ProductInventory en una sola consulta."""
    skus = {item.sku for o in orders for item in o.items}
    names_by_sku: dict[str, str] = {}
    if skus:
        rows = db.query(ProductInventory.sku, ProductInventory.product_name).filter(
            ProductInventory.sku.in_(skus)
        ).all()
        names_by_sku = {sku: name for sku, name in rows}

    result: List[OrderOut] = []
    for o in orders:
        out = OrderOut.model_validate(o)
        for item in out.items:
            item.product_name = names_by_sku.get(item.sku)
        result.append(out)
    return result


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
        if status == "received":
            query = query.filter(Order.status.in_(["received", "completed"]))
        else:
            query = query.filter(Order.status == status)
    orders = query.order_by(Order.received_at.desc()).limit(limit).all()
    return _serialize_orders_with_names(orders, db)


@router.post(
    "/prepare-work-order",
    response_model=PrepareWorkOrderResponse,
    summary="Buscar orden por número/ID y validar stock real para crear pedido",
)
def prepare_work_order_from_order(
    payload: PrepareWorkOrderRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_supervisor_or_admin),
):
    """
    Busca una orden por ID interno o external_order_id y valida el stock real
    disponible (físico - reservado) en la BD para todos sus productos.
    """
    raw_ref = payload.order_ref.strip()
    if not raw_ref:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Ingresa un número o ID de orden válido.",
        )

    clean_ref = raw_ref.lstrip("#").strip()
    order = db.query(Order).filter(
        func.lower(Order.external_order_id) == raw_ref.lower()
    ).first()
    if not order and clean_ref != raw_ref:
        order = db.query(Order).filter(
            func.lower(Order.external_order_id) == clean_ref.lower()
        ).first()
    if not order and clean_ref.isdigit():
        order = db.query(Order).filter(Order.id == int(clean_ref)).first()

    if not order:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró ninguna orden con el número '{raw_ref}'.",
        )
    if order.status == "rejected":
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"La orden #{order.id} ({order.external_order_id}) está en estado Rechazado.",
        )
    if not order.items:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"La orden #{order.id} no tiene productos asociados.",
        )

    # Agrupar cantidades de la orden por SKU por si hubiera líneas repetidas
    qty_by_sku: dict[str, int] = {}
    for it in order.items:
        qty_by_sku[it.sku] = qty_by_sku.get(it.sku, 0) + it.quantity

    skus = list(qty_by_sku.keys())
    inv_rows = db.query(ProductInventory).filter(ProductInventory.sku.in_(skus)).all()
    inv_by_sku = {p.sku: p for p in inv_rows}

    reserved_rows = db.execute(
        select(WorkOrderItem.sku, func.sum(WorkOrderItem.quantity).label("reserved"))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(WorkOrder.status.in_(RESERVED_STATUSES))
        .where(WorkOrderItem.sku.in_(skus))
        .group_by(WorkOrderItem.sku)
    ).all()
    reserved_by_sku = {row.sku: int(row.reserved) for row in reserved_rows}

    prepared: List[PreparedOrderItem] = []
    insufficient: List[InsufficientStockItem] = []

    for sku, order_qty in qty_by_sku.items():
        inv = inv_by_sku.get(sku)
        prod_name = inv.product_name if inv else sku
        available = max(0, inv.stock_quantity - reserved_by_sku.get(sku, 0)) if inv else 0
        total_needed = payload.existing_quantities.get(sku, 0) + order_qty

        if inv is None or total_needed > available:
            insufficient.append(
                InsufficientStockItem(
                    sku=sku,
                    product_name=prod_name,
                    requested=total_needed,
                    available=available,
                )
            )
        else:
            prepared.append(
                PreparedOrderItem(
                    sku=sku,
                    product_name=prod_name,
                    quantity=order_qty,
                    available_qty=available,
                )
            )

    if insufficient:
        if len(insufficient) == 1:
            one = insufficient[0]
            msg = f"No se pudo completar pedido por falta de stock de: {one.sku} - {one.product_name}."
        else:
            lines = "\n".join(f"- {it.sku} - {it.product_name}." for it in insufficient)
            msg = f"No se pudo completar pedido por falta de stock de:\n{lines}"
        return PrepareWorkOrderResponse(
            ok=False,
            order_id=order.id,
            external_order_id=order.external_order_id,
            customer_name=order.customer_name,
            items=[],
            insufficient_items=insufficient,
            error_message=msg,
        )

    return PrepareWorkOrderResponse(
        ok=True,
        order_id=order.id,
        external_order_id=order.external_order_id,
        customer_name=order.customer_name,
        items=prepared,
        insufficient_items=[],
        error_message=None,
    )


@router.patch(
    "/{order_id}/status",
    response_model=OrderOut,
    summary="Actualizar estado de una orden (Supervisor/Admin)",
)
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    """Persiste el nuevo estado de la orden ('received' | 'processing' | 'rejected') en BD."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Orden con id={order_id} no encontrada",
        )
    old_status = order.status
    order.status = payload.status
    db.commit()
    db.refresh(order)
    logger.info(
        "Estado de orden #%d (%s) cambiado de '%s' -> '%s' por %s",
        order.id, order.external_order_id, old_status, order.status, current_user.email,
    )
    return _serialize_orders_with_names([order], db)[0]


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
    return _serialize_orders_with_names([order], db)[0]
