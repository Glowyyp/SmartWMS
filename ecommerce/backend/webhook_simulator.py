"""
webhook_simulator.py — Simulador de eventos webhook de e-commerce

╔══════════════════════════════════════════════════════════════════╗
║  DECISIÓN DE DISEÑO: Script httpx vs Microservicio FastAPI       ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Opción A: Script puro httpx (esta implementación) ✅ GANADORA   ║
║  ─────────────────────────────────────────────────────────────── ║
║  + No acopla el emisor al receptor (arquetipo real)              ║
║  + Cero dependencias extra (httpx ya está en requirements)       ║
║  + Fácil de integrar en CI/CD como script de prueba              ║
║  + Modo --count N (ráfaga) o interactivo (demanda)               ║
║  + Soporte async nativo con httpx.AsyncClient                    ║
║                                                                  ║
║  Opción B: Microservicio emulador en FastAPI ❌ DESCARTADA        ║
║  ─────────────────────────────────────────────────────────────── ║
║  - Overhead de mantener un segundo proceso FastAPI corriendo     ║
║  - Acopla el emisor al mismo stack del receptor                  ║
║  - Complica el setup local (dos puertos, dos procesos)           ║
║  - Overkill para pruebas locales                                 ║
║  ✓ Sí tiene sentido en producción para plataformas SaaS que      ║
║    necesitan reintentos, logging persistente y dashboards.       ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝

Uso:
  # Enviar 1 orden inmediatamente
  python webhook_simulator.py

  # Enviar 5 órdenes con 2 segundos de intervalo
  python webhook_simulator.py --count 5 --interval 2

  # Enviar al endpoint de staging
  python webhook_simulator.py --url https://my-staging.run.app/api/v1/webhooks/orders

  # Modo verbose (muestra el payload completo)
  python webhook_simulator.py --count 3 --verbose

  # Simular un payload inválido (para probar los 422)
  python webhook_simulator.py --invalid
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Configuración
# =============================================================================

DEFAULT_TARGET_URL = "http://127.0.0.1:8001/api/v1/webhooks/orders"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Catálogo de productos disponibles en el simulador
PRODUCT_CATALOG = [
    {"sku": "SKU-00567", "name": "Teclado Mecánico RGB",    "price": "29.99"},
    {"sku": "SKU-00412", "name": "Tornillo M8 Acero",       "price": "0.50"},
    {"sku": "SKU-00891", "name": "Cable USB-C 2m",           "price": "14.99"},
    {"sku": "SKU-01234", "name": "Monitor 27\" 144Hz",       "price": "399.99"},
    {"sku": "SKU-01567", "name": "Mousepad XL Gaming",       "price": "19.99"},
    {"sku": "SKU-01890", "name": "Auriculares Inalámbricos", "price": "89.99"},
]

# Clientes de prueba
SAMPLE_CUSTOMERS = [
    {"id": "CUST-0001", "name": "María González",    "email": "maria.gonzalez@example.com"},
    {"id": "CUST-0002", "name": "Carlos Rodríguez",  "email": "carlos.rodriguez@example.com"},
    {"id": "CUST-0003", "name": "Ana Martínez",      "email": "ana.martinez@example.com"},
    {"id": "CUST-0004", "name": "Pedro Sánchez",     "email": "pedro.sanchez@example.com"},
    {"id": "CUST-0005", "name": "Laura Torres",      "email": "laura.torres@example.com"},
]


# =============================================================================
# Generador de payloads dinámicos
# =============================================================================

def generate_order_payload(order_index: int) -> dict:
    """
    Genera un payload dinámico y realista de tipo 'order.created'.

    Cada llamada produce un order_id único, un cliente aleatorio y
    entre 1 y 4 items seleccionados aleatoriamente del catálogo.
    """
    customer = random.choice(SAMPLE_CUSTOMERS)
    num_items = random.randint(1, min(4, len(PRODUCT_CATALOG)))
    selected_products = random.sample(PRODUCT_CATALOG, num_items)

    items = []
    for product in selected_products:
        quantity = random.randint(1, 5)
        unit_price = Decimal(product["price"])
        subtotal = (unit_price * quantity).quantize(Decimal("0.01"))
        items.append({
            "sku": product["sku"],
            "quantity": quantity,
            "unit_price": str(unit_price),
            "subtotal": str(subtotal),
        })

    total = sum(Decimal(item["subtotal"]) for item in items)

    # Order ID único: timestamp + índice + random
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    order_id = f"ORD-{timestamp_ms}-{order_index:04d}"

    return {
        "event_type": "order.created",
        "order_id": order_id,
        "customer": customer,
        "items": items,
        "total": str(total.quantize(Decimal("0.01"))),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def generate_invalid_payload() -> dict:
    """Genera un payload intencionalmente inválido para probar la validación (422)."""
    return {
        "event_type": "order.deleted",     # ❌ Literal incorrecto
        "order_id": "",                    # ❌ String vacío
        "customer": {
            "id": "C1",
            "name": "X",                   # ❌ Nombre demasiado corto (min_length=2)
            "email": "no-es-un-email",     # ❌ Email inválido
        },
        "items": [],                       # ❌ Lista vacía (min_length=1)
        "total": "-50.00",                 # ❌ Monto negativo
        "timestamp": "not-a-date",        # ❌ Timestamp inválido
    }


# =============================================================================
# Lógica de envío async
# =============================================================================

async def send_webhook(
    client: httpx.AsyncClient,
    payload: dict,
    target_url: str,
    order_index: int,
    verbose: bool = False,
) -> None:
    """Envía un payload al endpoint y muestra el resultado con colores ANSI."""

    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"

    headers = {"Content-Type": "application/json"}
    if WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = WEBHOOK_SECRET

    if verbose:
        print(f"\n{CYAN}{'─'*60}")
        print(f"  📤 Payload #{order_index}:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"{'─'*60}{RESET}")

    try:
        response = await client.post(target_url, json=payload, headers=headers, timeout=10.0)

        order_id = payload.get("order_id", "N/A")
        status_icon = "✅" if response.status_code in (200, 202) else "❌"
        color = GREEN if response.status_code in (200, 202) else (YELLOW if response.status_code == 409 else RED)

        print(
            f"  {status_icon} [{color}{BOLD}{response.status_code}{RESET}] "
            f"order_id={order_id:<30} → {response.json()}"
        )

    except httpx.ConnectError:
        print(
            f"  {RED}❌ CONEXIÓN RECHAZADA{RESET} — ¿Está corriendo el backend? "
            f"(uvicorn app.main:app --port 8001)"
        )
    except httpx.TimeoutException:
        print(f"  {YELLOW}⏱️  TIMEOUT{RESET} — El servidor tardó demasiado en responder")
    except Exception as e:
        print(f"  {RED}💥 ERROR INESPERADO{RESET}: {e}")


async def run_simulator(
    target_url: str,
    count: int,
    interval: float,
    verbose: bool,
    send_invalid: bool,
) -> None:
    """Bucle principal del simulador."""

    BOLD = "\033[1m"
    CYAN = "\033[96m"
    RESET = "\033[0m"

    print(f"\n{CYAN}{BOLD}{'═'*65}")
    print(f"  🎯 SmartWMS Webhook Simulator")
    print(f"  Target  : {target_url}")
    print(f"  Órdenes : {count} {'(+ 1 inválida)' if send_invalid else ''}")
    print(f"  Intervalo: {interval}s entre envíos")
    print(f"{'═'*65}{RESET}\n")

    async with httpx.AsyncClient() as client:
        # Enviar payload inválido primero si se solicitó
        if send_invalid:
            print(f"  🔴 Enviando payload INVÁLIDO para probar validación (422 esperado)...")
            invalid_payload = generate_invalid_payload()
            await send_webhook(client, invalid_payload, target_url, order_index=0, verbose=verbose)
            if count > 0:
                await asyncio.sleep(interval)

        # Enviar órdenes válidas
        for i in range(1, count + 1):
            payload = generate_order_payload(order_index=i)
            await send_webhook(client, payload, target_url, order_index=i, verbose=verbose)

            if i < count:
                await asyncio.sleep(interval)

    print(f"\n{'─'*65}")
    print(f"  ✅ Simulación completada. Revisa los logs del backend.")
    print(f"  📄 Swagger UI disponible en: http://127.0.0.1:8001/docs\n")


# =============================================================================
# CLI Entry Point
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulador de webhooks de órdenes para SmartWMS E-Commerce",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url", "-u",
        default=DEFAULT_TARGET_URL,
        help=f"URL del endpoint receptor (default: {DEFAULT_TARGET_URL})",
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=1,
        help="Número de órdenes válidas a enviar (default: 1)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=1.0,
        help="Segundos de espera entre envíos (default: 1.0)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Mostrar el payload JSON completo antes de enviarlo",
    )
    parser.add_argument(
        "--invalid",
        action="store_true",
        help="Enviar primero un payload inválido para probar la validación Pydantic (422)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        run_simulator(
            target_url=args.url,
            count=args.count,
            interval=args.interval,
            verbose=args.verbose,
            send_invalid=args.invalid,
        )
    )
