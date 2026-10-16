"""
routers/inventory.py — CRUD REST de Inventario

GET    /api/v1/inventory       → Listar productos (requiere JWT)
POST   /api/v1/inventory       → Agregar producto (requiere JWT admin)
PUT    /api/v1/inventory/{id}  → Editar producto   (requiere JWT admin)
DELETE /api/v1/inventory/{id}  → Eliminar producto (requiere JWT admin)
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.inventory import ProductInventory
from app.models.work_order import WorkOrder, WorkOrderItem
from app.models.pending_reception import PendingReception
from app.routers.auth import get_current_user, require_admin, require_supervisor_or_admin
from app.schemas.inventory import (
    ProductCreate, ProductOut, ProductUpdate,
    PendingReceptionCreate, PendingReceptionOut, PendingReceptionConfirm
)
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/inventory", tags=["Inventario"])


# ─── GET /api/v1/inventory ────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[ProductOut],
    summary="Listar todos los productos con stock físico, reservado y disponible",
)
def list_products(
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),   # cualquier usuario autenticado
):
    """
    Devuelve todos los productos del inventario ordenados por SKU.
    Incluye reserved_qty (suma de pedidos pendientes) y available_qty calculados
    con una sola consulta GROUP BY — sin N+1 queries.
    """
    products = db.query(ProductInventory).order_by(ProductInventory.sku).all()

    # Una sola query para obtener el total reservado por SKU
    reserved_by_sku: dict[str, int] = {}
    rows = db.execute(
        select(WorkOrderItem.sku, func.sum(WorkOrderItem.quantity).label("reserved"))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(WorkOrder.status.in_(["pending", "waiting_stock", "por_asignar", "assigned", "in_preparation", "in_progress"]))
        .group_by(WorkOrderItem.sku)
    ).all()
    for row in rows:
        reserved_by_sku[row.sku] = int(row.reserved)

    result = []
    for p in products:
        reserved = reserved_by_sku.get(p.sku, 0)
        out = ProductOut.model_validate(p)
        out.reserved_qty  = reserved
        out.available_qty = max(0, p.stock_quantity - reserved)
        if out.estimated_volume is None and p.length and p.width and p.height:
            out.estimated_volume = p.length * p.width * p.height
        result.append(out)

    return result


# ─── POST /api/v1/inventory ───────────────────────────────────────────────────

@router.post(
    "",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar producto al inventario",
)
def create_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    """Crea un nuevo producto. El SKU debe ser único. Requiere rol supervisor o admin."""
    existing = db.query(ProductInventory).filter(
        ProductInventory.sku == product_in.sku
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un producto con SKU '{product_in.sku}'",
        )

    data = product_in.model_dump()
    if data.get("estimated_volume") is None and data.get("length") and data.get("width") and data.get("height"):
        data["estimated_volume"] = data["length"] * data["width"] * data["height"]

    product = ProductInventory(**data)
    db.add(product)
    db.commit()
    db.refresh(product)
    logger.info("📦 Producto creado: %s — %s", product.sku, product.product_name)
    return product


# ─── PUT /api/v1/inventory/{id} ───────────────────────────────────────────────

@router.put(
    "/{product_id}",
    response_model=ProductOut,
    summary="Editar producto del inventario",
)
def update_product(
    product_id: int,
    product_in: ProductUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    """Actualiza los campos indicados del producto. Requiere rol supervisor o admin."""
    product = db.query(ProductInventory).filter(
        ProductInventory.id == product_id
    ).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con id={product_id} no encontrado",
        )

    update_data = product_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    # Recalcular volumen estimado si hay dimensiones disponibles
    l = getattr(product, "length", None)
    w = getattr(product, "width", None)
    h = getattr(product, "height", None)
    if l and w and h and ("estimated_volume" not in update_data or getattr(product, "estimated_volume", None) is None):
        product.estimated_volume = l * w * h

    db.commit()
    db.refresh(product)
    logger.info("✏️  Producto actualizado: id=%d SKU=%s", product.id, product.sku)
    return product


# ─── DELETE /api/v1/inventory/{id} ────────────────────────────────────────────

@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar producto del inventario",
)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    """Elimina un producto permanentemente. Requiere rol admin."""
    product = db.query(ProductInventory).filter(
        ProductInventory.id == product_id
    ).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con id={product_id} no encontrado",
        )

    db.delete(product)
    db.commit()
    logger.info("🗑️  Producto eliminado: id=%d SKU=%s", product_id, product.sku)


# ─── PENDING RECEPTIONS ───────────────────────────────────────────────────────

@router.get(
    "/receptions",
    response_model=List[PendingReceptionOut],
    summary="Listar todas las recepciones pendientes o completadas",
)
def list_receptions(
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    return db.query(PendingReception).order_by(PendingReception.created_at.desc()).all()


@router.post(
    "/receptions",
    response_model=PendingReceptionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un registro de stock pendiente (Supervisor/Admin)",
)
def create_pending_reception(
    reception_in: PendingReceptionCreate,
    db: Session = Depends(get_db),
    current_user: object = Depends(require_supervisor_or_admin),
):
    product = db.query(ProductInventory).filter(ProductInventory.sku == reception_in.sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    reception = PendingReception(**reception_in.model_dump())
    reception.created_by_id = current_user.id
    db.add(reception)
    
    # Actualizamos el pending_quantity del producto
    product.pending_quantity += reception.expected_quantity
    
    db.commit()
    db.refresh(reception)
    return reception


@router.post(
    "/receptions/{reception_id}/confirm",
    response_model=PendingReceptionOut,
    summary="Confirmar recepción total o parcial de stock (Supervisor/Admin)",
)
def confirm_pending_reception(
    reception_id: int,
    confirm_in: PendingReceptionConfirm,
    db: Session = Depends(get_db),
    current_user: object = Depends(require_supervisor_or_admin),
):
    reception = db.query(PendingReception).filter(PendingReception.id == reception_id).first()
    if not reception:
        raise HTTPException(status_code=404, detail="Recepción no encontrada")
    if reception.status in ["completed", "cancelled"]:
        raise HTTPException(status_code=400, detail=f"La recepción ya está {reception.status}")
    
    product = db.query(ProductInventory).filter(ProductInventory.sku == reception.sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado (pudo haber sido borrado)")
    
    # Restamos lo que estaba pendiente originalmente para esta recepción y 
    # si es parcial, dejamos la diferencia como pendiente? 
    # El usuario dijo: "Si se recibe una cantidad inferior a la esperada... mantener pendiente la diferencia"
    # Entonces: 
    added_to_received = confirm_in.received_quantity
    
    if (reception.received_quantity + added_to_received) >= reception.expected_quantity:
        reception.status = "completed"
    else:
        reception.status = "partial"
        
    reception.received_quantity += added_to_received
    reception.received_by_id = current_user.id
    reception.received_at = datetime.now(timezone.utc)
    
    # Actualizar inventario físico
    product.stock_quantity += added_to_received
    product.pending_quantity = max(0, product.pending_quantity - added_to_received)
    
    db.commit()
    
    # Revisar pedidos que están esperando stock (esperando_stock = "waiting_stock")
    # Los pasamos a "pending" (ready_for_dispatch) si todos sus ítems tienen suficiente stock_quantity
    # Ordenamos por los más viejos primero (FIFO)
    waiting_orders = db.query(WorkOrder).filter(WorkOrder.status == "waiting_stock").order_by(WorkOrder.created_at).all()
    
    for wo in waiting_orders:
        can_fulfill = True
        for item in wo.items:
            prod = db.query(ProductInventory).filter(ProductInventory.sku == item.sku).first()
            # En un entorno real, restaríamos el inventario virtualmente aquí para múltiples órdenes,
            # pero dado que el reserved_qty ya protege el stock, si sumamos el requerimiento
            # de órdenes más antiguas, podemos validar:
            # Aquí lo hacemos simple verificando si hay stock_quantity suficiente para el item.
            # Nota: Esto asume que reserved_qty protege a las órdenes 'pending' y 'waiting_stock'.
            # Para mayor rigor, calculamos si product.stock_quantity >= suma(pedidos pending) + este item
            if not prod:
                can_fulfill = False
                break
            
            # Cantidad reservada SOLO en órdenes despachables o activas
            already_reserved_despachable = db.execute(
                select(func.sum(WorkOrderItem.quantity))
                .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
                .where(WorkOrder.status.in_(["pending", "por_asignar", "in_preparation", "in_progress"]), WorkOrderItem.sku == prod.sku)
            ).scalar() or 0
            
            if (prod.stock_quantity - already_reserved_despachable) < item.quantity:
                can_fulfill = False
                break
                
        if can_fulfill:
            wo.status = "pending" if (wo.assigned_operario_id is not None or wo.assigned_operario_email) else "por_asignar"
            
    db.commit()
    db.refresh(reception)
    return reception
