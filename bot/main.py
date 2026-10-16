"""
bot/main.py — FastAPI Bot Server (puerto 8000)

Responsabilidades:
  • Endpoint POST /api/chat que valida el JWT emitido por el backend (puerto 8001).
  • Compatible tanto con formato web Angular (text / reply) como Android (message / response).
  • Asistente IA con Gemini (gemini-flash-lite-latest) y fallback inteligente local
    con inventario en tiempo real desde ecommerce.db para evitar fallos por cuota (429).
  • Integra bot de Telegram si TELEGRAM_BOT_TOKEN está configurado.
  • CORS habilitado para web, emulador Android y red local.
"""

import os
import re
import sqlite3
import logging
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field
from jose import JWTError
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from database import SessionLocal, User, get_db
from auth import decode_access_token

load_dotenv()
TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── GEMINI SETUP ─────────────────────────────────────────────────────────────
if GEMINI_KEY and GEMINI_KEY != "PEGA_TU_GEMINI_KEY_AQUI":
    genai.configure(api_key=GEMINI_KEY)

generation_config = {
    "temperature": 0.4,
    "top_p": 1,
    "top_k": 64,
    "max_output_tokens": 2048,
}

# Modelo rápido y disponible con menor latencia
PRIMARY_MODEL = "gemini-flash-lite-latest"
FALLBACK_MODEL = "gemini-flash-latest"

def get_gemini_model(model_name: str):
    return genai.GenerativeModel(model_name=model_name, generation_config=generation_config)

try:
    gemini_model = get_gemini_model(PRIMARY_MODEL)
except Exception as e:
    logger.warning(f"No se pudo inicializar {PRIMARY_MODEL}: {e}")
    gemini_model = None

# ─── INVENTARIO EN TIEMPO REAL DESDE ECOMMERCE.DB ─────────────────────────────

def get_live_inventory() -> tuple[str, list[dict]]:
    """Consulta la BD real de ecommerce.db para obtener stock y alertas actualizadas."""
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    db_candidates = [
        os.path.join(os.path.dirname(cur_dir), "ecommerce.db"),
        os.path.join(cur_dir, "ecommerce.db"),
        os.path.join(os.getcwd(), "ecommerce.db"),
    ]
    db_path = next((p for p in db_candidates if os.path.exists(p)), None)
    products: list[dict] = []

    if db_path:
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("""
                    SELECT sku, product_name, stock_quantity, warehouse_location, reorder_point 
                    FROM product_inventory
                    ORDER BY stock_quantity ASC
                """)
                products = [dict(row) for row in c.fetchall()]
        except Exception as e:
            logger.warning(f"Error al leer ecommerce.db: {e}")

    if not products:
        products = [
            {"sku": "SKU-00567", "product_name": "Teclado Mecánico RGB", "stock_quantity": 30, "warehouse_location": "B", "reorder_point": 20},
            {"sku": "SKU-00412", "product_name": "Tornillo M8 Acero", "stock_quantity": 190, "warehouse_location": "A", "reorder_point": 100},
            {"sku": "SKU-00891", "product_name": "Cable USB-C 2m", "stock_quantity": 30, "warehouse_location": "B", "reorder_point": 15},
            {"sku": "SKU-01234", "product_name": "Monitor 27\" 144Hz", "stock_quantity": 0, "warehouse_location": "C", "reorder_point": 5},
            {"sku": "SKU-01567", "product_name": "Mousepad XL Gaming", "stock_quantity": 188, "warehouse_location": "B", "reorder_point": 30},
        ]

    lines = []
    for p in products:
        qty = p.get("stock_quantity", 0)
        reorder = p.get("reorder_point") or 10
        loc = p.get("warehouse_location") or "S/L"
        estado = "⚠️ CRÍTICO" if qty <= reorder else "✅ Saludable"
        lines.append(f"- {p.get('sku')} ({p.get('product_name')}): {qty} uds en Zona {loc} ({estado})")

    context_str = "\n".join(lines)
    return context_str, products


# ─── FALLBACK INTELIGENTE LOCAL (CUANDO GEMINI LLEGA A LIMITE 429 U OFFLINE) ───

def get_local_fallback_reply(text: str, products: list[dict]) -> dict:
    """
    Motor local de respuestas inteligentes de SmartWMS.
    Garantiza que la aplicación nunca se quede sin respuesta por agotamiento
    de cuota de la API de Gemini (Rate Limit 429).
    """
    tl = text.lower().strip()

    # 1. Comandos de ayuda o saludos
    if tl in ["/ayuda", "ayuda", "help", "/start"] or any(g in tl for g in ["hola", "buenos dias", "buenas tardes", "buenas noches", "saludos"]):
        return {
            "text": (
                "👋 ¡Hola! Soy el **Copiloto IA de SmartWMS**.\n\n"
                "Estoy a tu disposición para ayudarte con operaciones de bodega en tiempo real:\n"
                "• 📦 **Stock de productos:** Consulta cualquier SKU o nombre de producto.\n"
                "• 🔍 **Picking:** Procedimientos de recolección y lectura QR.\n"
                "• 📤 **Packing y Despacho:** Registro de bultos, pesaje y dimensiones.\n"
                "• ⚠️ **Alertas:** Monitoreo de ítems con bajo stock.\n\n"
                "¿En qué te puedo colaborar en este momento?"
            ),
            "buttons": [
                {"label": "📦 Ver Inventario", "cmd": "/stock"},
                {"label": "🔍 Guía de Picking", "cmd": "/picking"},
                {"label": "⚠️ Stock Crítico", "cmd": "/alertas"}
            ]
        }

    # 2. Picking
    if any(k in tl for k in ["picking", "recoleccion", "recolectar", "recolección", "/picking"]):
        return {
            "text": (
                "📋 *Guía de Picking (Recolección de Pedidos):*\n\n"
                "1. **Iniciar Picking:** Ingresa a la sección de Picking en tu aplicación y abre la orden asignada.\n"
                "2. **Seguir la Ruta:** Dirígete a la ubicación física señalada respetando la secuencia de pasillos (A ➔ B ➔ C ➔ D).\n"
                "3. **Validación QR:** Escanea el código de barras o QR de la etiqueta del producto para confirmar el SKU exacto.\n"
                "4. **Conteo:** Verifica que la cantidad recolectada coincida con la solicitud.\n"
                "5. **Finalizar:** Marca la orden como completada para trasladar los ítems a la mesa de empaque."
            ),
            "buttons": [{"label": "📦 Consultar Stock", "cmd": "/stock"}]
        }

    # 3. Packing y Despacho
    if any(k in tl for k in ["packing", "empaque", "embalaje", "despacho", "despachar", "paquete", "bulto"]):
        return {
            "text": (
                "📦 *Procedimiento de Packing y Despacho:*\n\n"
                "1. **Revisión de Ítems:** Asegúrate de que todos los productos recolectados en picking estén presentes y en buen estado.\n"
                "2. **Empaque Seguro:** Selecciona la caja adecuada según volumen y peso.\n"
                "3. **Medidas y Peso:** Ingresa las dimensiones (largo x ancho x alto en cm) y el peso neto en kg en la pantalla de Despacho.\n"
                "4. **Confirmar Despacho:** Al presionar **Confirmar**, se descontará el stock físico automáticamente y se generará el comprobante de salida."
            ),
            "buttons": [{"label": "📋 Volver a Picking", "cmd": "/picking"}]
        }

    # 4. Alertas de Stock Crítico
    if any(k in tl for k in ["alerta", "alertas", "critico", "crítico", "agotado", "reorden", "bajo stock", "/alertas"]):
        criticos = [p for p in products if p.get("stock_quantity", 0) <= (p.get("reorder_point") or 10)]
        if not criticos:
            return {"text": "✅ *Estado del Inventario:* Todos los SKUs se encuentran con niveles saludables de stock."}
        
        items_txt = []
        for p in criticos[:8]:
            loc = p.get('warehouse_location') or 'S/L'
            items_txt.append(f"• **{p.get('sku')}** ({p.get('product_name')}): `{p.get('stock_quantity')} uds` en Zona {loc} (Punto reorden: {p.get('reorder_point', 10)})")

        return {
            "text": (
                f"⚠️ *Alertas de Stock Crítico ({len(criticos)} ítems detectados):*\n\n"
                + "\n".join(items_txt)
                + "\n\nSe sugiere al Supervisor emitir orden de compra para reabastecimiento."
            ),
            "buttons": [{"label": "📦 Ver Todo el Stock", "cmd": "/stock"}]
        }

    # 5. Consulta de Stock de un SKU o Producto específico
    found = None
    for p in products:
        sku = p.get("sku", "").lower()
        name = p.get("product_name", "").lower()
        if sku in tl or name in tl:
            found = p
            break

    # Búsqueda por palabras clave parciales (ej: "teclado", "tornillo", "cable", "monitor", "mousepad")
    if not found:
        tokens = [w for w in re.split(r'\W+', tl) if len(w) >= 4 and w not in ["stock", "cual", "donde", "cuanto", "cuantos", "tienen", "queda", "quedan"]]
        for t in tokens:
            for p in products:
                if t in p.get("sku", "").lower() or t in p.get("product_name", "").lower():
                    found = p
                    break
            if found:
                break

    if found:
        qty = found.get("stock_quantity", 0)
        reorder = found.get("reorder_point") or 10
        loc = found.get("warehouse_location") or "Sin asignar"
        estado = "⚠️ En nivel crítico" if qty <= reorder else "✅ Nivel adecuado"
        return {
            "text": (
                f"📦 *Información de Inventario:*\n\n"
                f"• **Producto:** {found.get('product_name')}\n"
                f"• **SKU:** `{found.get('sku')}`\n"
                f"• **Stock Actual:** `{qty} unidades`\n"
                f"• **Ubicación en Bodega:** `Zona {loc}`\n"
                f"• **Punto de Reorden:** `{reorder} unidades` ({estado})\n"
            ),
            "buttons": [
                {"label": "🔍 Proceder a Picking", "cmd": "/picking"},
                {"label": "📦 Ver Otros SKUs", "cmd": "/stock"}
            ]
        }

    # 6. Resumen general de Stock (/stock)
    if any(k in tl for k in ["stock", "inventario", "/stock"]):
        summary = []
        for p in products[:6]:
            loc = p.get('warehouse_location') or 'S/L'
            summary.append(f"• `{p.get('sku')}` - {p.get('product_name')}: **{p.get('stock_quantity')} uds** (Zona {loc})")
        return {
            "text": (
                f"📦 *Resumen de Inventario en Bodega (Total: {len(products)} SKUs):*\n\n"
                + "\n".join(summary)
                + "\n\nPuedes consultar el stock detallado de cualquier producto escribiendo su nombre o SKU (ej: *'Stock SKU-00567'*)."
            ),
            "buttons": [
                {"label": "⚠️ Ver Stock Crítico", "cmd": "/alertas"},
                {"label": "🔍 Guía de Picking", "cmd": "/picking"}
            ]
        }

    # 7. Respuesta por defecto
    return {
        "text": (
            "🤖 *Copiloto SmartWMS:*\n\n"
            "Puedo asistirte con cualquier tarea operativa de la bodega:\n"
            "• Consulta de stock por producto o SKU (ej: *'Stock Teclado'*)\n"
            "• Instrucciones de picking y lectura de QR\n"
            "• Procedimiento de packing y despacho\n"
            "• Revisión de alertas de reabastecimiento\n\n"
            "¿Deseas consultar inventario o guías de operación?"
        ),
        "buttons": [
            {"label": "📦 Consultar Stock", "cmd": "/stock"},
            {"label": "🔍 Guía de Picking", "cmd": "/picking"}
        ]
    }


# ─── LÓGICA PRINCIPAL DE PROCESAMIENTO DEL BOT ────────────────────────────────

def get_bot_reply(text: str) -> dict:
    """Procesa el texto con Gemini y cuenta con fallback local automático."""
    raw_text = (text or "").strip()
    if not raw_text:
        return {"text": "Por favor escribe tu consulta para el Copiloto IA."}

    context_str, products = get_live_inventory()
    tl = raw_text.lower().strip()

    # Comandos rápidos directos
    if tl in ["/ayuda", "/stock", "/picking", "/alertas"]:
        return get_local_fallback_reply(tl, products)

    # Intentar con Gemini
    if GEMINI_KEY and GEMINI_KEY != "PEGA_TU_GEMINI_KEY_AQUI":
        try:
            active_model = gemini_model or get_gemini_model(PRIMARY_MODEL)
            contexto = (
                "Eres el Copiloto IA de SmartWMS, un asistente inteligente para operarios y supervisores de bodega.\n"
                "Reglas obligatorias:\n"
                "1. Responde de forma concisa, profesional y directa en español. Usa Markdown para destacar SKUs y ubicaciones.\n"
                "2. Si te preguntan algo no relacionado con bodega, logística o inventario, indica amablemente que solo atiendes temas de bodega.\n"
                f"3. INVENTARIO REAL ACTUAL EN BODEGA:\n{context_str}\n"
                "4. Si preguntan sobre picking: indicar que deben ir a la sección Picking de la app, seguir la ruta optimizada (pasillos A->B->C->D) y escanear el QR del producto.\n"
                "5. Si preguntan sobre packing: indicar que deben empaquetar, ingresar peso/dimensiones y confirmar despacho.\n\n"
                f"Pregunta del usuario: {raw_text}"
            )
            response = active_model.generate_content(contexto)
            if response and response.text:
                return {"text": response.text.strip()}
        except Exception as e:
            err_msg = str(e)
            logger.warning(f"Gemini devolvió error, activando fallback local: {err_msg}")
            # Si es por cuota o cualquier fallo de Gemini, el fallback inteligente responde de inmediato
            return get_local_fallback_reply(raw_text, products)

    # Si no hay key configurada, responder con fallback local
    return get_local_fallback_reply(raw_text, products)


# ─── TELEGRAM BOT HANDLERS ────────────────────────────────────────────────────

async def command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text
    reply = get_bot_reply(text)
    keyboard = [[InlineKeyboardButton(b['label'], callback_data="cmd_" + b['cmd'])] for b in reply.get("buttons", [])]
    await update.message.reply_text(
        reply["text"], parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    cmd = (query.data or "").replace("cmd_", "")
    reply = get_bot_reply(cmd)
    keyboard = [[InlineKeyboardButton(b['label'], callback_data="cmd_" + b['cmd'])] for b in reply.get("buttons", [])]
    await query.answer()
    await query.edit_message_text(
        reply["text"], parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

tg_app = Application.builder().token(TOKEN).build() if TOKEN and TOKEN != "PEGA_TU_API_KEY_AQUI" else None

if tg_app:
    tg_app.add_handler(MessageHandler(filters.TEXT, command_handler))
    tg_app.add_handler(CallbackQueryHandler(button_handler))


# ─── FASTAPI SETUP ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    if tg_app:
        try:
            await tg_app.initialize()
            await tg_app.start()
            await tg_app.updater.start_polling()
            logger.info("Telegram Bot iniciado exitosamente")
        except Exception as e:
            logger.warning(f"No se pudo iniciar Telegram Bot: {e}")
    yield
    if tg_app:
        try:
            await tg_app.updater.stop()
            await tg_app.stop()
            await tg_app.shutdown()
        except Exception as e:
            logger.warning(f"Error al detener Telegram Bot: {e}")

app = FastAPI(
    title="SmartWMS Bot API",
    description="Bot de Copiloto IA — valida JWT emitido por el backend (puerto 8001).",
    version="1.1.0",
    lifespan=lifespan,
)

# ─── CORS: permite Angular, Android y red local ──────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "http://10.0.2.2:4200",
    ],
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Validación JWT ───────────────────────────────────────────────────────────
BACKEND_AUTH_URL = os.getenv("BACKEND_AUTH_URL", "http://127.0.0.1:8001/api/auth/login")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=BACKEND_AUTH_URL, auto_error=False)

def get_current_user_from_token(token: str | None = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(token)
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─── ENDPOINT CHAT ────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    # Acepta tanto 'text' (Angular) como 'message' (Android)
    text: str = ""
    message: str = ""

    class Config:
        extra = "allow"


@app.post(
    "/api/chat",
    summary="Consultar al Copiloto IA de SmartWMS",
    description="Recibe el mensaje del usuario y retorna la respuesta. Requiere Bearer JWT del backend.",
)
async def api_chat(
    msg: ChatMessage,
    current_user: dict = Depends(get_current_user_from_token),
):
    query_text = (msg.text or msg.message or "").strip()
    logger.info(f"Chat request de usuario: {current_user.get('sub')} (rol: {current_user.get('role')}) -> '{query_text}'")
    reply = get_bot_reply(query_text)
    
    # Retorna tanto 'reply' (objeto con text y buttons) como 'response' (string directo)
    # para soportar de manera nativa Angular, Android y clientes REST
    reply_text = reply.get("text", "")
    return {
        "reply": reply,
        "response": reply_text
    }


@app.get("/health", tags=["Sistema"])
async def health_check():
    """Health check para el bot."""
    return {"status": "ok", "service": "smartwms-bot", "version": "1.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
