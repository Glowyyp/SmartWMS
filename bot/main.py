"""
bot/main.py — FastAPI Bot Server (puerto 8000)

Responsabilidades:
  • Mantiene el endpoint POST /api/chat que valida el JWT emitido
    por el backend (puerto 8001) antes de responder.
  • Integra el bot de Telegram si TELEGRAM_BOT_TOKEN está configurado.
  • CORS habilitado para http://localhost:4200 y http://127.0.0.1:4200.

Autenticación:
  El endpoint /api/chat requiere Authorization: Bearer <token>.
  El token es el mismo JWT emitido por POST /api/auth/login del backend.
  El bot NO emite tokens propios; solo los valida.
"""

import os
import logging
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session
from jose import JWTError
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from database import SessionLocal, User, get_db
from auth import get_password_hash, verify_password, create_access_token, decode_access_token

load_dotenv()
TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── GEMINI SETUP ─────────────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_KEY)
generation_config = {
    "temperature": 0.4,
    "top_p": 1,
    "top_k": 64,
    "max_output_tokens": 2048,
}
model = genai.GenerativeModel(
    model_name="gemini-flash-latest",
    generation_config=generation_config
)

# ─── LÓGICA COMPARTIDA DEL BOT ────────────────────────────────────────────────

def get_bot_reply(text: str) -> dict:
    """Procesa el texto con Gemini y devuelve la respuesta."""
    tl = text.lower().strip()

    # Comandos predefinidos rápidos (sin gastar API)
    if tl == "/ayuda":
        return {
            "text": "📋 *Comandos disponibles:*\n\n/ayuda - Mostrar este mensaje\n/stock - Consultar inventario\n/picking - Guía de picking",
            "buttons": [{"label": "📦 Ver Stock", "cmd": "/stock"}]
        }

    # Para todo lo demás, consultamos a Gemini
    try:
        if GEMINI_KEY and GEMINI_KEY != "PEGA_TU_GEMINI_KEY_AQUI":
            contexto = (
                "Eres el Copiloto IA de SmartWMS, un asistente inteligente para operarios y supervisores de bodega.\n"
                "Reglas:\n"
                "1. Nunca te salgas de tu rol. Si te preguntan algo no relacionado con la bodega o inventario, di que solo puedes ayudar con temas logísticos.\n"
                "2. Sé amable, conciso y directo. Usa formato Markdown para destacar cosas importantes.\n"
                "3. Inventario actual:\n"
                "- SKU-00567 (Teclado Mecánico): 145 uds en C-03-B (Saludable)\n"
                "- SKU-00412 (Tornillo M8): 3 uds en A-03-B (CRÍTICO)\n"
                "- Cable USB-C: 1 ud en C-01-A (CRÍTICO)\n"
                "- Total SKUs: 1842\n"
                "4. Si preguntan sobre picking, indica que deben iniciar en la app, seguir la ruta y escanear los QR.\n\n"
                f"Mensaje del usuario: {text}"
            )
            response = model.generate_content(contexto)
            return {"text": response.text.strip()}
        else:
            return {"text": "⚠️ *Modo Offline:* La API Key de Gemini no está configurada en el .env."}
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error en Gemini: {err_msg}")
        return {"text": f"❌ Ocurrió un error al consultar el cerebro de IA.\n\nDetalle técnico: `{err_msg}`"}


# ─── TELEGRAM BOT HANDLERS ────────────────────────────────────────────────────

async def command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    reply = get_bot_reply(text)
    keyboard = [[InlineKeyboardButton(b['label'], callback_data="cmd_" + b['cmd'])] for b in reply.get("buttons", [])]
    await update.message.reply_text(
        reply["text"], parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    cmd = query.data.replace("cmd_", "")
    reply = get_bot_reply(cmd)
    keyboard = [[InlineKeyboardButton(b['label'], callback_data="cmd_" + b['cmd'])] for b in reply.get("buttons", [])]
    await query.answer()
    await query.edit_message_text(
        reply["text"], parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

# Inicializar TG App
tg_app = Application.builder().token(TOKEN).build() if TOKEN and TOKEN != "PEGA_TU_API_KEY_AQUI" else None

if tg_app:
    tg_app.add_handler(MessageHandler(filters.TEXT, command_handler))
    tg_app.add_handler(CallbackQueryHandler(button_handler))


# ─── FASTAPI SETUP ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    if tg_app:
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling()
        logger.info("Telegram Bot iniciado")
    yield
    if tg_app:
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()

app = FastAPI(
    title="SmartWMS Bot API",
    description="Bot de Copiloto IA — valida el JWT emitido por el backend (puerto 8001).",
    version="1.0.0",
    lifespan=lifespan,
)

# ─── CORS: permite llamadas desde Angular (puerto 4200) ───────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ─── Validación JWT ───────────────────────────────────────────────────────────
# Usa el mismo tokenUrl del backend para que el flujo OAuth2 en Swagger sea consistente
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8001/api/auth/login", auto_error=False)

def get_current_user_from_token(token: str | None = Depends(oauth2_scheme)) -> dict | None:
    """
    Valida el JWT del backend. Si el token es inválido, lanza 401.
    Retorna el payload decodificado (contiene 'sub' y 'role').
    """
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
    text: str


@app.post(
    "/api/chat",
    summary="Consultar al Copiloto IA de SmartWMS",
    description=(
        "Recibe el mensaje del usuario y retorna la respuesta de Gemini. "
        "Requiere un JWT válido emitido por POST /api/auth/login del backend (puerto 8001). "
        "Roles permitidos: admin, supervisor, operario."
    ),
)
async def api_chat(
    msg: ChatMessage,
    current_user: dict = Depends(get_current_user_from_token),
):
    """
    Endpoint de chat con validación JWT.
    El token debe ser el mismo Bearer token que devuelve /api/auth/login.
    """
    logger.info(f"Chat request de usuario: {current_user.get('sub')} (rol: {current_user.get('role')})")
    reply = get_bot_reply(msg.text)
    return {"reply": reply}


@app.get("/health", tags=["Sistema"])
async def health_check():
    """Health check para el bot."""
    return {"status": "ok", "service": "smartwms-bot", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
