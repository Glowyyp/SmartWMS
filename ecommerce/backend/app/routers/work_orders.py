"""
routers/work_orders.py — CRUD y lógica de Pedidos de Bodega

Endpoints:
  GET    /api/v1/work-orders                → Listar pedidos (filtrable por status)
  POST   /api/v1/work-orders                → Crear pedido (solo supervisor/admin)
  GET    /api/v1/work-orders/{id}           → Detalle de un pedido
  POST   /api/v1/work-orders/{id}/dispatch  → Despachar pedido (solo operario/supervisor/admin)
  POST   /api/v1/work-orders/{id}/cancel    → Cancelar pedido (solo supervisor/admin)

Invariantes de stock:
  - Al crear: se valida que stock_disponible >= cantidad solicitada.
  - Al despachar: transacción atómica con SELECT FOR UPDATE que descuenta stock_quantity.
  - Al cancelar: libera la reserva automáticamente (solo retira el pedido de la suma pending).
  - Un pedido 'dispatched' o 'cancelled' no puede volver a 'pending'.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.inventory import ProductInventory
from app.models.user import User
from app.models.work_order import WorkOrder, WorkOrderItem
from app.routers.auth import get_current_user, require_supervisor_or_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/work-orders", tags=["Pedidos de Bodega"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas inline
# ─────────────────────────────────────────────────────────────────────────────

class WorkOrderItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, description="Cantidad solicitada (debe ser > 0)")


class WorkOrderCreate(BaseModel):
    items: List[WorkOrderItemIn] = Field(min_length=1)
    # Operario asignado (opcional). Si es None, cualquier operario puede ver el pedido.
    assigned_operario_email: Optional[str] = None


class WorkOrderItemOut(BaseModel):
    id: int
    sku: str
    product_name: str
    quantity: int

    model_config = {"from_attributes": True}


class WorkOrderOut(BaseModel):
    id: int
    order_number: str
    status: str
    created_by_email: Optional[str]
    assigned_operario_email: Optional[str]
    dispatched_by_email: Optional[str]
    created_at: datetime
    dispatched_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    items: List[WorkOrderItemOut] = []

    model_config = {"from_attributes": True}


class OperarioOut(BaseModel):
    """Schema simple para listar operarios disponibles."""
    id: int
    email: str
    full_name: Optional[str]

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reserved_qty_for_sku(sku: str, db: Session) -> int:
    """
    Calcula el total de unidades reservadas para un SKU sumando
    los ítems de pedidos en estado 'pending'.
    """
    result = db.execute(
        select(func.coalesce(func.sum(WorkOrderItem.quantity), 0))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(WorkOrder.status == "pending")
        .where(WorkOrderItem.sku == sku)
    ).scalar()
    return int(result or 0)


def _next_order_number(db: Session) -> str:
    """Genera el próximo número de pedido correlativo: WO-0001, WO-0002, ..."""
    count = db.query(WorkOrder).count()
    return f"WO-{count + 1:04d}"


def _available_qty(product: ProductInventory, db: Session) -> int:
    reserved = _reserved_qty_for_sku(product.sku, db)
    return product.stock_quantity - reserved


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/work-orders
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[WorkOrderOut], summary="Listar pedidos de bodega")
def list_work_orders(
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,  # email del operario asignado
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Retorna todos los pedidos de bodega, opcionalmente filtrados por status
    y/o por operario asignado.
    - assigned_to: filtra por email del operario asignado. Si el pedido tiene
      assigned_operario_email=NULL se considera de acceso libre (visible para todos).
    """
    q = db.query(WorkOrder)
    if status:
        q = q.filter(WorkOrder.status == status)
    if assigned_to:
        # Muestra los pedidos asignados a este operario O los sin asignar (NULL)
        from sqlalchemy import or_
        q = q.filter(
            or_(
                WorkOrder.assigned_operario_email == assigned_to,
                WorkOrder.assigned_operario_email.is_(None)
            )
        )
    return q.order_by(WorkOrder.created_at.desc()).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/work-orders/operarios  (supervisor: lista de operarios para asignar)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/operarios", response_model=List[OperarioOut], summary="Listar operarios disponibles")
def list_operarios(
    db: Session = Depends(get_db),
    _: User = Depends(require_supervisor_or_admin),
):
    """Retorna todos los usuarios con rol 'operario' activos para asignarlos a pedidos."""
    from app.models.user import User as UserModel
    return db.query(UserModel).filter(
        UserModel.role == "operario",
        UserModel.is_active == True
    ).order_by(UserModel.email).all()


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/work-orders/{id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{order_id}", response_model=WorkOrderOut, summary="Detalle de un pedido")
def get_work_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not wo:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"Pedido {order_id} no encontrado")
    return wo


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/work-orders  (solo supervisor / admin)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=WorkOrderOut,
    status_code=http_status.HTTP_201_CREATED,
    summary="Crear pedido de bodega (supervisor)",
)
def create_work_order(
    payload: WorkOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    """
    El Supervisor crea un pedido seleccionando SKUs ya existentes.
    Las cantidades quedan RESERVADAS (no descuentan físicamente el stock_quantity).
    Validaciones:
      - SKU debe existir en ProductInventory.
      - stock_disponible (stock_quantity - sum_pendientes) >= cantidad solicitada.
      - quantity > 0.
    """
    # Validar todos los ítems antes de crear nada
    enriched_items = []
    for item in payload.items:
        product = db.query(ProductInventory).filter(
            ProductInventory.sku == item.sku
        ).first()
        if not product:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"SKU '{item.sku}' no existe en el inventario",
            )
        available = _available_qty(product, db)
        if item.quantity > available:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                detail=(
                    f"Stock insuficiente para '{item.sku}': "
                    f"disponible={available}, solicitado={item.quantity}"
                ),
            )
        enriched_items.append((item, product))

    # Crear el pedido
    wo = WorkOrder(
        order_number=_next_order_number(db),
        status="pending",
        created_by_id=current_user.id,
        created_by_email=current_user.email,
        assigned_operario_email=payload.assigned_operario_email,
    )
    db.add(wo)
    db.flush()  # Obtener wo.id sin commit

    for item, product in enriched_items:
        db.add(WorkOrderItem(
            work_order_id=wo.id,
            sku=item.sku,
            product_name=product.product_name,
            quantity=item.quantity,
        ))

    db.commit()
    db.refresh(wo)
    logger.info("📦 Pedido creado: %s por %s", wo.order_number, current_user.email)
    return wo


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/work-orders/{id}/dispatch
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{order_id}/dispatch",
    response_model=WorkOrderOut,
    summary="Despachar pedido (operario)",
)
def dispatch_work_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    El Operario confirma el despacho físico.

    Transacción atómica con SELECT FOR UPDATE:
      - Verifica estado = 'pending'.
      - Para cada ítem: bloquea la fila de inventario y descuenta stock_quantity.
      - Marca el pedido como 'dispatched'.
      - Si algo falla, rollback completo.

    Idempotencia: si el pedido ya fue despachado, retorna 409.
    """
    # Cargar el pedido (sin lock aún — validación rápida primero)
    wo = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not wo:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"Pedido {order_id} no encontrado")

    if wo.status == "dispatched":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="El pedido ya fue despachado")
    if wo.status == "cancelled":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="El pedido está cancelado y no puede despacharse")

    try:
        # Procesar cada ítem con bloqueo de fila (SELECT FOR UPDATE)
        for item in wo.items:
            inventory_row: ProductInventory | None = db.execute(
                select(ProductInventory)
                .where(ProductInventory.sku == item.sku)
                .with_for_update()
            ).scalar_one_or_none()

            if inventory_row is None:
                db.rollback()
                raise HTTPException(
                    http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"SKU '{item.sku}' ya no existe en inventario",
                )

            if inventory_row.stock_quantity < item.quantity:
                db.rollback()
                raise HTTPException(
                    http_status.HTTP_409_CONFLICT,
                    detail=(
                        f"Stock insuficiente para '{item.sku}': "
                        f"físico={inventory_row.stock_quantity}, requerido={item.quantity}"
                    ),
                )

            # Descontar stock físico
            inventory_row.stock_quantity -= item.quantity
            logger.info(
                "🚚 Despacho: SKU=%s qty=%d nuevo_stock=%d",
                item.sku, item.quantity, inventory_row.stock_quantity,
            )

        # Marcar pedido como despachado
        wo.status = "dispatched"
        wo.dispatched_by_id    = current_user.id
        wo.dispatched_by_email = current_user.email
        wo.dispatched_at       = datetime.now(timezone.utc)

        db.commit()
        db.refresh(wo)
        logger.info("✅ Pedido despachado: %s por %s", wo.order_number, current_user.email)
        return wo

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Error al despachar pedido %s: %s", order_id, exc)
        raise HTTPException(http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno al despachar")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/work-orders/{id}/cancel
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{order_id}/cancel",
    response_model=WorkOrderOut,
    summary="Cancelar pedido (supervisor)",
)
def cancel_work_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    """
    Cancela un pedido pendiente. Libera automáticamente la reserva de stock.
    No se puede cancelar un pedido ya despachado.
    """
    wo = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not wo:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"Pedido {order_id} no encontrado")

    if wo.status == "dispatched":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="No se puede cancelar un pedido ya despachado")
    if wo.status == "cancelled":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="El pedido ya está cancelado")

    wo.status       = "cancelled"
    wo.cancelled_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(wo)
    logger.info("❌ Pedido cancelado: %s por %s", wo.order_number, current_user.email)
    return wo
