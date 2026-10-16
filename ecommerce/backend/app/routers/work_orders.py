"""
routers/work_orders.py — CRUD y lógica de Pedidos de Bodega

Endpoints:
  GET    /api/v1/work-orders                → Listar pedidos (filtrable por status y operario)
  GET    /api/v1/work-orders/operarios      → Listar operarios activos disponibles
  POST   /api/v1/work-orders                → Crear pedido (solo supervisor/admin)
  GET    /api/v1/work-orders/{id}           → Detalle de un pedido
  PUT    /api/v1/work-orders/{id}           → Editar pedido completo (supervisor/admin)
  PUT    /api/v1/work-orders/{id}/assign    → Asignar/desasignar operario (supervisor/admin)
  POST   /api/v1/work-orders/{id}/dispatch  → Despachar pedido (operario/supervisor/admin)
  POST   /api/v1/work-orders/{id}/cancel    → Cancelar pedido (supervisor/admin)

Invariantes de stock y flujo:
  - Sin operario asignado: status = 'por_asignar'
  - Con operario asignado: status = 'pending'
  - Reserva de stock: Todo pedido en 'por_asignar', 'pending', 'waiting_stock', 'in_preparation', 'in_progress' reserva stock.
  - Al despachar: transacción atómica con SELECT FOR UPDATE que descuenta stock_quantity.
  - Al cancelar: libera la reserva automáticamente.
  - Un pedido 'dispatched' o 'cancelled' no puede volver a 'pending' ni modificar sus items.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.inventory import ProductInventory
from app.models.user import User
from app.models.work_order import WorkOrder, WorkOrderItem, WorkOrderPackage
from app.routers.auth import get_current_user, require_supervisor_or_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/work-orders", tags=["Pedidos de Bodega"])

RESERVED_STATUSES = [
    "por_asignar",
    "pending",
    "waiting_stock",
    "assigned",
    "in_preparation",
    "in_progress",
]

VALID_STATUSES = [
    "por_asignar",
    "pending",
    "in_preparation",
    "in_progress",
    "dispatched",
    "completed",
    "cancelled",
    "waiting_stock",
]


# ─────────────────────────────────────────────────────────────────────────────
# Schemas inline
# ─────────────────────────────────────────────────────────────────────────────

class WorkOrderItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, description="Cantidad solicitada (debe ser > 0)")


class WorkOrderCreate(BaseModel):
    items: List[WorkOrderItemIn] = Field(min_length=1)
    assigned_operario_id: Optional[int] = None
    assigned_operario_email: Optional[str] = None


class WorkOrderUpdate(BaseModel):
    status: Optional[str] = None
    assigned_operario_id: Optional[int] = None
    assigned_operario_email: Optional[str] = None
    items: Optional[List[WorkOrderItemIn]] = None


class AssignOperarioIn(BaseModel):
    assigned_operario_id: Optional[int] = None
    assigned_operario_email: Optional[str] = None


class WorkOrderItemOut(BaseModel):
    id: int
    sku: str
    product_name: str
    quantity: int
    unit_price: Optional[float] = None
    subtotal: Optional[float] = None

    model_config = {"from_attributes": True}


class DispatchPackageIn(BaseModel):
    length: float | None = None
    width: float | None = None
    height: float | None = None
    weight: float | None = None


class DispatchIn(BaseModel):
    packages: List[DispatchPackageIn] = []
    total_weight: float | None = None
    total_volume: float | None = None


class WorkOrderPackageOut(BaseModel):
    id: int
    length: float | None = None
    width: float | None = None
    height: float | None = None
    weight: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkOrderOut(BaseModel):
    id: int
    order_number: str
    status: str
    created_by_id: Optional[int] = None
    created_by_email: Optional[str] = None
    assigned_operario_id: Optional[int] = None
    assigned_operario_email: Optional[str] = None
    dispatched_by_id: Optional[int] = None
    dispatched_by_email: Optional[str] = None
    created_at: datetime
    dispatched_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    total_weight: float | None = None
    total_volume: float | None = None
    packages_count: int = 0
    total_items: int = 0
    total_amount: float = 0.0
    items: List[WorkOrderItemOut] = []
    packages: List[WorkOrderPackageOut] = []

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
    los ítems de pedidos activos no despachados ni cancelados.
    """
    result = db.execute(
        select(func.coalesce(func.sum(WorkOrderItem.quantity), 0))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(WorkOrder.status.in_(RESERVED_STATUSES))
        .where(WorkOrderItem.sku == sku)
    ).scalar()
    return int(result or 0)


def _reserved_qty_for_sku_excluding_order(sku: str, exclude_order_id: int, db: Session) -> int:
    """
    Calcula las unidades reservadas por OTROS pedidos para un SKU,
    excluyendo el pedido especificado (útil al editar pedidos).
    """
    result = db.execute(
        select(func.coalesce(func.sum(WorkOrderItem.quantity), 0))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(WorkOrder.id != exclude_order_id)
        .where(WorkOrder.status.in_(RESERVED_STATUSES))
        .where(WorkOrderItem.sku == sku)
    ).scalar()
    return int(result or 0)


def _next_order_number(db: Session) -> str:
    """Genera el próximo número de pedido correlativo: WO-0001, WO-0002, ..."""
    count = db.query(WorkOrder).count()
    return f"WO-{count + 1:04d}"


def _available_qty(product: ProductInventory, db: Session) -> int:
    reserved = _reserved_qty_for_sku(product.sku, db)
    return max(0, product.stock_quantity - reserved)


def _validate_and_get_operario(
    db: Session,
    operario_id: Optional[int] = None,
    operario_email: Optional[str] = None,
) -> Optional[User]:
    """
    Valida que el operario exista, esté activo y tenga rol de operario.
    Retorna la instancia de User o None si se solicitó desasignar.
    """
    if operario_id is None and not operario_email:
        return None

    user = None
    if operario_id is not None:
        user = db.query(User).filter(User.id == operario_id).first()
        if not user:
            raise HTTPException(
                http_status.HTTP_404_NOT_FOUND,
                detail=f"Operario con ID {operario_id} no existe",
            )
    elif operario_email:
        clean_email = operario_email.strip()
        if not clean_email:
            return None
        user = db.query(User).filter(User.email == clean_email).first()
        if not user:
            raise HTTPException(
                http_status.HTTP_404_NOT_FOUND,
                detail=f"Operario con email '{clean_email}' no existe",
            )

    if not user.is_active:
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            detail=f"El operario '{user.email}' no está activo y no puede recibir pedidos",
        )

    if user.role != "operario":
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario '{user.email}' tiene rol '{user.role}', pero solo se pueden asignar pedidos a usuarios con rol 'operario'",
        )

    return user


def _enrich_work_order(wo: WorkOrder, db: Session) -> WorkOrderOut:
    """
    Enriquece un WorkOrder con precios unitarios, subtotales, totales
    y asegura coherencia entre assigned_operario_id y assigned_operario_email.
    """
    # Sincronizar ID / Email si uno de ellos estuviera vacío
    if wo.assigned_operario_id and not wo.assigned_operario_email:
        u = db.query(User).filter(User.id == wo.assigned_operario_id).first()
        if u:
            wo.assigned_operario_email = u.email
    elif wo.assigned_operario_email and not wo.assigned_operario_id:
        u = db.query(User).filter(User.email == wo.assigned_operario_email).first()
        if u:
            wo.assigned_operario_id = u.id

    skus = [it.sku for it in (wo.items or [])]
    price_map: dict[str, float] = {}
    if skus:
        prods = db.query(ProductInventory).filter(ProductInventory.sku.in_(skus)).all()
        for p in prods:
            price_map[p.sku] = float(p.unit_price) if p.unit_price is not None else 0.0

    items_out: List[WorkOrderItemOut] = []
    total_qty = 0
    total_amt = 0.0
    for it in (wo.items or []):
        u_price = price_map.get(it.sku, 0.0)
        subtotal = round(u_price * it.quantity, 2)
        total_qty += it.quantity
        total_amt += subtotal
        items_out.append(
            WorkOrderItemOut(
                id=it.id,
                sku=it.sku,
                product_name=it.product_name,
                quantity=it.quantity,
                unit_price=u_price,
                subtotal=subtotal,
            )
        )

    pkgs_out = [
        WorkOrderPackageOut.model_validate(p) for p in (wo.packages or [])
    ]

    return WorkOrderOut(
        id=wo.id,
        order_number=wo.order_number,
        status=wo.status,
        created_by_id=wo.created_by_id,
        created_by_email=wo.created_by_email,
        assigned_operario_id=wo.assigned_operario_id,
        assigned_operario_email=wo.assigned_operario_email,
        dispatched_by_id=wo.dispatched_by_id,
        dispatched_by_email=wo.dispatched_by_email,
        created_at=wo.created_at,
        dispatched_at=wo.dispatched_at,
        cancelled_at=wo.cancelled_at,
        total_weight=float(wo.total_weight) if wo.total_weight is not None else None,
        total_volume=float(wo.total_volume) if wo.total_volume is not None else None,
        packages_count=wo.packages_count,
        total_items=total_qty,
        total_amount=round(total_amt, 2),
        items=items_out,
        packages=pkgs_out,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/work-orders
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[WorkOrderOut], summary="Listar pedidos de bodega")
def list_work_orders(
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,  # email o ID del operario asignado
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retorna todos los pedidos de bodega, opcionalmente filtrados por status
    y/o por operario asignado.
    - Si el usuario es 'operario', solo visualiza pedidos asignados directamente a él
      o pedidos que él haya despachado.
    - Supervisores y administradores pueden ver todos los pedidos y filtrar libremente.
    """
    q = db.query(WorkOrder)

    if status:
        if "," in status:
            s_list = [s.strip().lower() for s in status.split(",") if s.strip()]
            q = q.filter(func.lower(WorkOrder.status).in_(s_list))
        else:
            q = q.filter(func.lower(WorkOrder.status) == status.strip().lower())

    if current_user.role == "operario":
        # Restricción estricta de seguridad: el operario solo ve sus propias tareas asignadas
        q = q.filter(
            or_(
                WorkOrder.assigned_operario_id == current_user.id,
                WorkOrder.assigned_operario_email == current_user.email,
                WorkOrder.dispatched_by_id == current_user.id,
                WorkOrder.dispatched_by_email == current_user.email,
            )
        )
    elif assigned_to:
        clean_assigned = assigned_to.strip()
        if clean_assigned.isdigit():
            user_id = int(clean_assigned)
            q = q.filter(
                or_(
                    WorkOrder.assigned_operario_id == user_id,
                    WorkOrder.assigned_operario_email == clean_assigned,
                )
            )
        else:
            q = q.filter(WorkOrder.assigned_operario_email == clean_assigned)

    orders = q.order_by(WorkOrder.created_at.desc()).limit(limit).all()
    return [_enrich_work_order(wo, db) for wo in orders]


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/work-orders/operarios  (supervisor: lista de operarios para asignar)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/operarios", response_model=List[OperarioOut], summary="Listar operarios disponibles")
def list_operarios(
    db: Session = Depends(get_db),
    _: User = Depends(require_supervisor_or_admin),
):
    """Retorna todos los usuarios activos con rol 'operario' para asignación de pedidos."""
    return db.query(User).filter(
        User.role == "operario",
        User.is_active == True,
    ).order_by(User.email).all()


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/work-orders/{id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{order_id}", response_model=WorkOrderOut, summary="Detalle de un pedido")
def get_work_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wo = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not wo:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"Pedido {order_id} no encontrado")

    if current_user.role == "operario":
        is_assigned = (
            wo.assigned_operario_id == current_user.id
            or wo.assigned_operario_email == current_user.email
            or wo.dispatched_by_id == current_user.id
            or wo.dispatched_by_email == current_user.email
        )
        if not is_assigned:
            raise HTTPException(
                http_status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para visualizar este pedido",
            )

    return _enrich_work_order(wo, db)


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
    - Sin operario asignado: estado inicial = 'por_asignar'
    - Con operario asignado: estado inicial = 'pending'
    - Valida que el operario exista y esté activo.
    - Valida disponibilidad de stock físico para cada SKU.
    """
    # Validar operario
    op_user = _validate_and_get_operario(
        db, payload.assigned_operario_id, payload.assigned_operario_email
    )

    enriched_items = []
    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cantidad inválida ({item.quantity}) para SKU '{item.sku}'",
            )

        product = db.query(ProductInventory).filter(
            ProductInventory.sku == item.sku
        ).first()
        if not product:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"SKU '{item.sku}' no existe en el inventario",
            )

        available_physical = _available_qty(product, db)
        if available_physical <= 0 or item.quantity > available_physical:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                detail=(
                    f"Stock insuficiente para '{item.sku}': "
                    f"disponible físico={available_physical}, solicitado={item.quantity}. "
                    "No se pueden agregar artículos sin stock a los pedidos."
                ),
            )
        enriched_items.append((item, product))

    # Regla: Sin operario -> 'por_asignar'. Con operario -> 'pending'.
    initial_status = "pending" if op_user is not None else "por_asignar"

    wo = WorkOrder(
        order_number=_next_order_number(db),
        status=initial_status,
        created_by_id=current_user.id,
        created_by_email=current_user.email,
        assigned_operario_id=op_user.id if op_user else None,
        assigned_operario_email=op_user.email if op_user else None,
    )
    db.add(wo)
    db.flush()

    for item, product in enriched_items:
        db.add(WorkOrderItem(
            work_order_id=wo.id,
            sku=item.sku,
            product_name=product.product_name,
            quantity=item.quantity,
        ))

    db.commit()
    db.refresh(wo)
    logger.info("📦 Pedido creado: %s status=%s operario=%s", wo.order_number, wo.status, wo.assigned_operario_email)
    return _enrich_work_order(wo, db)


# ─────────────────────────────────────────────────────────────────────────────
# PUT /api/v1/work-orders/{id} (edición completa de pedido)
# ─────────────────────────────────────────────────────────────────────────────

@router.put(
    "/{order_id}",
    response_model=WorkOrderOut,
    summary="Editar pedido de bodega completo (supervisor / admin)",
)
def update_work_order(
    order_id: int,
    payload: WorkOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    """
    Edita un pedido existente: operario asignado, estado e ítems.
    Reglas de transición de estado:
      - Si estaba en 'por_asignar' y se asigna un operario -> pasa automáticamente a 'pending'.
      - Si estaba en 'pending' y se desasigna el operario -> vuelve a 'por_asignar'.
      - Si estaba en 'in_preparation', 'in_progress', 'dispatched' o 'cancelled',
        cambiar el operario NO lo reinicia automáticamente a 'pending'.
      - El usuario puede modificar el estado explícitamente a cualquier estado válido.
      - Un pedido 'dispatched' o 'cancelled' no puede reactivarse ni modificar sus ítems.
    """
    wo = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not wo:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"Pedido {order_id} no encontrado")

    # Invariante: pedidos finalizados no pueden reactivarse ni cambiar sus ítems
    if wo.status in ["dispatched", "cancelled"]:
        if payload.items is not None:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                detail=f"Un pedido en estado '{wo.status}' no puede modificar sus ítems",
            )
        if payload.status and payload.status.lower() not in ["dispatched", "cancelled", "completed"]:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                detail=f"Un pedido en estado '{wo.status}' no puede reactivarse a '{payload.status}'",
            )

    # 1. Modificar Operario
    if payload.assigned_operario_id is not None or payload.assigned_operario_email is not None:
        op_user = _validate_and_get_operario(
            db, payload.assigned_operario_id, payload.assigned_operario_email
        )
        if op_user is not None:
            wo.assigned_operario_id = op_user.id
            wo.assigned_operario_email = op_user.email
            # Transición automática: solo si no se pasó un nuevo estado explícito
            if payload.status is None:
                if wo.status in ["por_asignar", "assigned"]:
                    wo.status = "pending"
        else:
            # Desasignar
            wo.assigned_operario_id = None
            wo.assigned_operario_email = None
            if payload.status is None:
                if wo.status in ["pending", "assigned"]:
                    wo.status = "por_asignar"

    # 2. Modificar Estado Explícito
    if payload.status is not None:
        target_status = payload.status.strip().lower()
        if target_status not in VALID_STATUSES:
            raise HTTPException(
                http_status.HTTP_400_BAD_REQUEST,
                detail=f"Estado '{payload.status}' no es válido. Estados permitidos: {', '.join(VALID_STATUSES)}",
            )

        if target_status == "completed":
            target_status = "dispatched"

        if target_status == "cancelled" and wo.status != "cancelled":
            wo.cancelled_at = datetime.now(timezone.utc)
        elif target_status != "cancelled":
            wo.cancelled_at = None

        wo.status = target_status

    # 3. Modificar Ítems
    if payload.items is not None:
        if len(payload.items) == 0:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El pedido debe tener al menos un producto",
            )

        enriched_items = []
        for item in payload.items:
            if item.quantity <= 0:
                raise HTTPException(
                    http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cantidad inválida ({item.quantity}) para SKU '{item.sku}'",
                )

            product = db.query(ProductInventory).filter(
                ProductInventory.sku == item.sku
            ).first()
            if not product:
                raise HTTPException(
                    http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"SKU '{item.sku}' no existe en el inventario",
                )

            # Stock disponible excluyendo la reserva actual de este mismo pedido
            reserved_others = _reserved_qty_for_sku_excluding_order(item.sku, wo.id, db)
            available_for_order = product.stock_quantity - reserved_others

            if item.quantity > available_for_order:
                raise HTTPException(
                    http_status.HTTP_409_CONFLICT,
                    detail=(
                        f"Stock insuficiente para '{item.sku}': "
                        f"disponible={max(0, available_for_order)}, solicitado={item.quantity}"
                    ),
                )
            enriched_items.append((item, product))

        # Reemplazar ítems existentes
        db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == wo.id).delete()
        for item, product in enriched_items:
            db.add(WorkOrderItem(
                work_order_id=wo.id,
                sku=item.sku,
                product_name=product.product_name,
                quantity=item.quantity,
            ))

    db.commit()
    db.refresh(wo)
    logger.info("✏️ Pedido %s actualizado: status=%s operario=%s", wo.order_number, wo.status, wo.assigned_operario_email)
    return _enrich_work_order(wo, db)


# ─────────────────────────────────────────────────────────────────────────────
# PUT /api/v1/work-orders/{id}/assign (asignación rápida desde dropdown)
# ─────────────────────────────────────────────────────────────────────────────

@router.put(
    "/{order_id}/assign",
    response_model=WorkOrderOut,
    summary="Asignar operario a pedido (supervisor)",
)
def assign_work_order(
    order_id: int,
    payload: AssignOperarioIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    """
    Asigna o reasigna un pedido a un operario específico.
    Reglas:
      - Si el pedido estaba en 'por_asignar' y se le asigna un operario -> pasa a 'pending'.
      - Si se le quita la asignación y no ha comenzado a procesarse -> vuelve a 'por_asignar'.
      - Si ya está en 'in_preparation', 'in_progress', etc. -> conserva su estado actual.
    """
    wo = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not wo:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"Pedido {order_id} no encontrado")

    if wo.status in ["dispatched", "cancelled"]:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"No se puede asignar un pedido en estado {wo.status}")

    op_user = _validate_and_get_operario(
        db, payload.assigned_operario_id, payload.assigned_operario_email
    )

    if op_user is not None:
        wo.assigned_operario_id = op_user.id
        wo.assigned_operario_email = op_user.email
        if wo.status in ["por_asignar", "assigned"]:
            wo.status = "pending"
    else:
        wo.assigned_operario_id = None
        wo.assigned_operario_email = None
        if wo.status in ["pending", "assigned"]:
            wo.status = "por_asignar"

    db.commit()
    db.refresh(wo)
    logger.info("👤 Pedido %s asignado a %s (status: %s)", wo.order_number, wo.assigned_operario_email, wo.status)
    return _enrich_work_order(wo, db)


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
    payload: DispatchIn | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    El Operario confirma el despacho físico.
    Transacción atómica con SELECT FOR UPDATE que descuenta stock_quantity.
    """
    wo = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not wo:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"Pedido {order_id} no encontrado")

    if wo.status not in ["pending", "assigned", "in_preparation", "in_progress"]:
        if wo.status == "waiting_stock":
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail="El pedido está esperando stock y no es despachable")
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"El pedido está en estado {wo.status} y no puede despacharse")

    calc_total_weight = 0.0
    calc_total_volume = 0.0

    try:
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

            if inventory_row.weight:
                calc_total_weight += float(inventory_row.weight) * item.quantity

            if getattr(inventory_row, "estimated_volume", None):
                calc_total_volume += float(inventory_row.estimated_volume) * item.quantity
            elif inventory_row.length and inventory_row.width and inventory_row.height:
                calc_total_volume += (float(inventory_row.length) * float(inventory_row.width) * float(inventory_row.height)) * item.quantity

            inventory_row.stock_quantity -= item.quantity
            logger.info("🚚 Despacho: SKU=%s qty=%d nuevo_stock=%d", item.sku, item.quantity, inventory_row.stock_quantity)

        wo.status = "dispatched"
        wo.dispatched_by_id = current_user.id
        wo.dispatched_by_email = current_user.email
        wo.dispatched_at = datetime.now(timezone.utc)

        if payload and payload.packages:
            wo.total_weight = payload.total_weight or calc_total_weight
            wo.total_volume = payload.total_volume or calc_total_volume
            wo.packages_count = len(payload.packages)
            for pkg_in in payload.packages:
                pkg = WorkOrderPackage(
                    work_order_id=wo.id,
                    length=pkg_in.length,
                    width=pkg_in.width,
                    height=pkg_in.height,
                    weight=pkg_in.weight,
                )
                db.add(pkg)
        else:
            wo.total_weight = calc_total_weight
            wo.total_volume = calc_total_volume
            wo.packages_count = 1
            estimated_side = round(math.pow(calc_total_volume, 1.0 / 3.0), 2) if calc_total_volume > 0 else 0.0
            pkg = WorkOrderPackage(
                work_order_id=wo.id,
                length=estimated_side,
                width=estimated_side,
                height=estimated_side,
                weight=calc_total_weight,
            )
            db.add(pkg)

        db.commit()
        db.refresh(wo)
        logger.info("✅ Pedido despachado: %s por %s", wo.order_number, current_user.email)
        return _enrich_work_order(wo, db)

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Error al despachar pedido %s: %s", order_id, exc)
        raise HTTPException(http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al despachar: {str(exc)}")


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
    Cancela un pedido. Libera automáticamente la reserva de stock.
    No se puede cancelar un pedido ya despachado.
    """
    wo = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not wo:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"Pedido {order_id} no encontrado")

    if wo.status == "dispatched":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="No se puede cancelar un pedido ya despachado")
    if wo.status == "cancelled":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="El pedido ya está cancelado")

    wo.status = "cancelled"
    wo.cancelled_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(wo)
    logger.info("❌ Pedido cancelado: %s por %s", wo.order_number, current_user.email)
    return _enrich_work_order(wo, db)
