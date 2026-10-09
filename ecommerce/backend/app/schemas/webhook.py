"""
schemas/webhook.py — Modelos Pydantic para validación del payload de webhook

Diseño: validación estricta con tipos Pydantic v2.
Cada campo tiene su razón de ser documentada con Field(description=...).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# =============================================================================
# Sub-modelos
# =============================================================================

class OrderItemSchema(BaseModel):
    """Representa un único producto dentro de una orden."""

    sku: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Stock Keeping Unit — identificador único del producto",
        examples=["SKU-00567"],
    )
    quantity: int = Field(
        ...,
        gt=0,
        description="Cantidad de unidades pedidas. Debe ser estrictamente positivo.",
        examples=[3],
    )
    unit_price: Decimal = Field(
        ...,
        gt=Decimal("0"),
        decimal_places=2,
        description="Precio unitario del producto. Debe ser > 0.",
        examples=["29.99"],
    )
    subtotal: Decimal = Field(
        ...,
        ge=Decimal("0"),
        decimal_places=2,
        description="Subtotal del ítem (quantity × unit_price). Calculado por el emisor.",
        examples=["89.97"],
    )

    @field_validator("subtotal")
    @classmethod
    def subtotal_must_be_coherent(cls, subtotal: Decimal, info) -> Decimal:
        """
        Valida que el subtotal enviado sea coherente con quantity × unit_price.
        Permite una tolerancia de ±$0.02 por redondeos del emisor.
        """
        data = info.data
        if "quantity" in data and "unit_price" in data:
            expected = Decimal(str(data["quantity"])) * data["unit_price"]
            if abs(subtotal - expected) > Decimal("0.02"):
                raise ValueError(
                    f"subtotal {subtotal} no coincide con quantity × unit_price "
                    f"({data['quantity']} × {data['unit_price']} = {expected})"
                )
        return subtotal

    model_config = {"json_encoders": {Decimal: str}}


class CustomerSchema(BaseModel):
    """Datos del cliente que realizó la orden."""

    id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="ID único del cliente en el sistema de origen",
        examples=["CUST-4821"],
    )
    name: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Nombre completo del cliente",
        examples=["María González"],
    )
    email: EmailStr = Field(
        ...,
        description="Email válido del cliente",
        examples=["maria.gonzalez@example.com"],
    )


# =============================================================================
# Payload principal del webhook
# =============================================================================

class OrderWebhookPayload(BaseModel):
    """
    Payload completo de un evento webhook de tipo 'order.created'.

    El sistema emisor (e-commerce externo) envía este JSON via POST
    al endpoint /api/v1/webhooks/orders.
    """

    event_type: Literal["order.created"] = Field(
        ...,
        description="Tipo de evento. Solo se acepta 'order.created'.",
    )
    order_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="ID único de la orden en el sistema origen",
        examples=["ORD-20240917-001"],
    )
    customer: CustomerSchema = Field(
        ...,
        description="Datos del cliente que realizó la compra",
    )
    items: List[OrderItemSchema] = Field(
        ...,
        min_length=1,
        description="Lista de productos en la orden. Debe tener al menos 1 ítem.",
    )
    total: Decimal = Field(
        ...,
        gt=Decimal("0"),
        decimal_places=2,
        description="Total de la orden. Debe ser > 0.",
        examples=["299.97"],
    )
    timestamp: datetime = Field(
        ...,
        description="Timestamp ISO 8601 de cuando se creó la orden en el sistema origen",
        examples=["2024-09-17T18:30:00Z"],
    )

    @model_validator(mode="after")
    def total_must_match_items(self) -> "OrderWebhookPayload":
        """
        Valida que el total declarado coincida con la suma de subtotales de los ítems.
        Permite ±$0.05 de tolerancia por redondeos o descuentos globales.
        """
        computed_total = sum(item.subtotal for item in self.items)
        if abs(self.total - computed_total) > Decimal("0.05"):
            raise ValueError(
                f"El total {self.total} no coincide con la suma de subtotales "
                f"de los ítems ({computed_total}). Diferencia: {abs(self.total - computed_total)}"
            )
        return self

    model_config = {
        "json_encoders": {Decimal: str},
        "json_schema_extra": {
            "example": {
                "event_type": "order.created",
                "order_id": "ORD-20240917-001",
                "customer": {
                    "id": "CUST-4821",
                    "name": "María González",
                    "email": "maria.gonzalez@example.com",
                },
                "items": [
                    {
                        "sku": "SKU-00567",
                        "quantity": 2,
                        "unit_price": "29.99",
                        "subtotal": "59.98",
                    },
                    {
                        "sku": "SKU-00412",
                        "quantity": 1,
                        "unit_price": "14.99",
                        "subtotal": "14.99",
                    },
                ],
                "total": "74.97",
                "timestamp": "2024-09-17T18:30:00Z",
            }
        },
    }


# =============================================================================
# Respuestas de la API
# =============================================================================

class WebhookResponse(BaseModel):
    """Respuesta estándar al recibir un webhook exitosamente."""

    message: str
    order_id: str
    internal_id: int
    status: str


class WebhookErrorResponse(BaseModel):
    """Respuesta de error con detalle del fallo."""

    error: str
    detail: str
