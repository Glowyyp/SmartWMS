import os
import logging
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from database import SessionLocal, User, get_db
from auth import get_password_hash, verify_password, create_access_token

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- GEMINI SETUP ---
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

# --- LÓGICA COMPARTIDA DEL BOT (Cerebro) ---
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


# --- TELEGRAM BOT HANDLERS ---
async def command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    reply = get_bot_reply(text)
    keyboard = [[InlineKeyboardButton(b['label'], callback_data="cmd_"+b['cmd'])] for b in reply.get("buttons", [])]
    await update.message.reply_text(reply["text"], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    cmd = query.data.replace("cmd_", "")
    reply = get_bot_reply(cmd)
    keyboard = [[InlineKeyboardButton(b['label'], callback_data="cmd_"+b['cmd'])] for b in reply.get("buttons", [])]
    await query.answer()
    await query.edit_message_text(reply["text"], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

# Inicializar TG App
tg_app = Application.builder().token(TOKEN).build() if TOKEN and TOKEN != "PEGA_TU_API_KEY_AQUI" else None

if tg_app:
    tg_app.add_handler(MessageHandler(filters.TEXT, command_handler))
    tg_app.add_handler(CallbackQueryHandler(button_handler))

# --- FASTAPI SETUP ---
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

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ENDPOINTS AUTH ---
class UserCreate(BaseModel):
    email: str
    password: str
    role: str = "operario"

class UserLogin(BaseModel):
    email: str
    password: str

@app.post("/api/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="El correo ya está registrado")
    
    hashed_password = get_password_hash(user.password)
    new_user = User(email=user.email, hashed_password=hashed_password, role=user.role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"msg": "Usuario registrado exitosamente"}

@app.post("/api/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    
    access_token = create_access_token(data={"sub": db_user.email, "role": db_user.role})
    return {"access_token": access_token, "token_type": "bearer", "role": db_user.role}

# --- ENDPOINT CHAT ---
class ChatMessage(BaseModel):
    text: str

@app.post("/api/chat")
async def api_chat(msg: ChatMessage):
    reply = get_bot_reply(msg.text)
    return {"reply": reply}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
