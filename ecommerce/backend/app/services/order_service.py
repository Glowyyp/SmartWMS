"""
services/order_service.py — Lógica de Negocio Transaccional

Esta capa encapsula toda la interacción con la BD para procesar una orden.
El endpoint no toca directamente la BD; delega aquí.

Flujo atómico de process_order():
  1. Verificar que la orden no esté duplicada (idempotencia)
  2. Crear registro Order → flush (obtiene ID sin commit)
  3. Para cada ítem:
     a. Buscar ProductInventory con SELECT FOR UPDATE (bloqueo a nivel de fila)
     b. Verificar stock suficiente → raise StockInsuficienteError si no alcanza
     c. Descontar stock → crear OrderItem
  4. db.commit() → todo o nada
  5. En caso de error → rollback automático (SQLAlchemy revierte al salir del bloque)
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.inventory import ProductInventory
from app.schemas.webhook import OrderWebhookPayload, WebhookResponse

logger = logging.getLogger(__name__)


# =============================================================================
# Excepciones de dominio
# =============================================================================

class OrderAlreadyExistsError(Exception):
    """Se lanza cuando ya existe una orden con el mismo external_order_id (duplicado)."""
    def __init__(self, order_id: str):
        super().__init__(f"La orden '{order_id}' ya fue procesada anteriormente.")
        self.order_id = order_id


class StockInsuficienteError(Exception):
    """Se lanza cuando un producto no tiene suficiente stock para cubrir la orden."""
    def __init__(self, sku: str, requested: int, available: int):
        super().__init__(
            f"Stock insuficiente para SKU '{sku}': "
            f"solicitado={requested}, disponible={available}"
        )
        self.sku = sku
        self.requested = requested
        self.available = available


class ProductoNoEncontradoError(Exception):
    """Se lanza cuando un SKU del webhook no existe en el inventario."""
    def __init__(self, sku: str):
        super().__init__(f"SKU '{sku}' no encontrado en el inventario.")
        self.sku = sku


# =============================================================================
# Servicio principal
# =============================================================================

def process_order(payload: OrderWebhookPayload, db: Session) -> WebhookResponse:
    """
    Procesa una orden recibida via webhook en una sola transacción atómica.

    Args:
        payload:  Datos validados del webhook (Pydantic).
        db:       Sesión SQLAlchemy inyectada por FastAPI.

    Returns:
        WebhookResponse con el ID interno generado y el estado final.

    Raises:
        OrderAlreadyExistsError:   Si la orden ya fue procesada (idempotencia).
        ProductoNoEncontradoError: Si algún SKU no existe en inventario.
        StockInsuficienteError:    Si no hay stock suficiente para algún ítem.
        Exception:                 Cualquier error de BD genera rollback automático.
    """
    # ------------------------------------------------------------------
    # Paso 1: Idempotencia — verificar duplicados por external_order_id
    # ------------------------------------------------------------------
    existing = db.execute(
        select(Order).where(Order.external_order_id == payload.order_id)
    ).scalar_one_or_none()

    if existing:
        logger.warning(
            "Orden duplicada recibida: external_id=%s internal_id=%s",
            payload.order_id, existing.id,
        )
        raise OrderAlreadyExistsError(payload.order_id)

    # ------------------------------------------------------------------
    # Paso 2: Crear cabecera de la Orden (sin commit aún)
    # ------------------------------------------------------------------
    order = Order(
        external_order_id=payload.order_id,
        customer_id=payload.customer.id,
        customer_name=payload.customer.name,
        customer_email=payload.customer.email,
        total=payload.total,
        status="processing",
        event_timestamp=payload.timestamp,
    )
    db.add(order)
    db.flush()  # Genera order.id sin hacer commit → disponible para los OrderItems

    logger.info(
        "Procesando orden external_id=%s internal_id=%s con %d ítem(s)",
        payload.order_id, order.id, len(payload.items),
    )

    # ------------------------------------------------------------------
    # Paso 3: Procesar cada ítem — validar y descontar stock
    # ------------------------------------------------------------------
    for item_data in payload.items:
        # 3a: SELECT FOR UPDATE — bloqueo a nivel de fila para evitar race conditions
        # (Nota: SQLite no soporta FOR UPDATE; en PostgreSQL sí funciona)
        inventory_item: ProductInventory | None = db.execute(
            select(ProductInventory)
            .where(ProductInventory.sku == item_data.sku)
            .with_for_update()  # BLOQUEO DE FILA: solo un proceso modifica este SKU a la vez
        ).scalar_one_or_none()

        # 3b: Verificar que el producto existe
        if inventory_item is None:
            logger.error("SKU no encontrado en inventario: %s", item_data.sku)
            db.rollback()
            raise ProductoNoEncontradoError(item_data.sku)

        # 3c: Verificar stock suficiente
        if inventory_item.stock_quantity < item_data.quantity:
            logger.error(
                "Stock insuficiente para SKU=%s: solicitado=%d, disponible=%d",
                item_data.sku, item_data.quantity, inventory_item.stock_quantity,
            )
            db.rollback()
            raise StockInsuficienteError(
                sku=item_data.sku,
                requested=item_data.quantity,
                available=inventory_item.stock_quantity,
            )

        # 3d: Descontar stock
        inventory_item.stock_quantity -= item_data.quantity

        if inventory_item.is_low_stock:
            logger.warning(
                "⚠️  STOCK BAJO — SKU=%s: %d unidades restantes (reorder_point=%d)",
                item_data.sku,
                inventory_item.stock_quantity,
                inventory_item.reorder_point,
            )

        # 3e: Crear ítem de la orden
        order_item = OrderItem(
            order_id=order.id,
            sku=item_data.sku,
            quantity=item_data.quantity,
            unit_price=item_data.unit_price,
            subtotal=item_data.subtotal,
        )
        db.add(order_item)

    # ------------------------------------------------------------------
    # Paso 4: Marcar orden como completada y hacer COMMIT final
    # ------------------------------------------------------------------
    order.status = "completed"
    db.commit()
    db.refresh(order)

    logger.info(
        "✅ Orden procesada exitosamente: external_id=%s internal_id=%s",
        payload.order_id, order.id,
    )

    return WebhookResponse(
        message="Orden procesada y stock actualizado correctamente.",
        order_id=payload.order_id,
        internal_id=order.id,
        status=order.status,
    )


# =============================================================================
# Utilidad: Seed de inventario inicial (para pruebas)
# =============================================================================

def seed_inventory(db: Session) -> None:
    """
    Carga productos de ejemplo en ProductInventory si la tabla está vacía.
    Solo para entornos de desarrollo/prueba. No llamar en producción.
    """
    existing_count = db.query(ProductInventory).count()
    if existing_count > 0:
        logger.info("Inventario ya tiene %d productos. Seed omitido.", existing_count)
        return

    sample_products = [
        ProductInventory(sku="SKU-00567", product_name="Teclado Mecánico RGB",     stock_quantity=145, unit_price=Decimal("29.99"), reorder_point=20,  warehouse_location="B"),
        ProductInventory(sku="SKU-00412", product_name="Tornillo M8 Acero",        stock_quantity=50,  unit_price=Decimal("0.50"),  reorder_point=100, warehouse_location="A"),
        ProductInventory(sku="SKU-00891", product_name="Cable USB-C 2m",            stock_quantity=80,  unit_price=Decimal("14.99"), reorder_point=15,  warehouse_location="B"),
        ProductInventory(sku="SKU-01234", product_name="Monitor 27\" 144Hz",        stock_quantity=12,  unit_price=Decimal("399.99"), reorder_point=5,  warehouse_location="C"),
        ProductInventory(sku="SKU-01567", product_name="Mousepad XL Gaming",        stock_quantity=200, unit_price=Decimal("19.99"), reorder_point=30,  warehouse_location="B"),
        ProductInventory(sku="SKU-01890", product_name="Auriculares Inalámbricos",  stock_quantity=35,  unit_price=Decimal("89.99"), reorder_point=10,  warehouse_location="C"),
    ]

    db.add_all(sample_products)
    db.commit()
    logger.info("✅ Seed de inventario completado: %d productos cargados.", len(sample_products))

