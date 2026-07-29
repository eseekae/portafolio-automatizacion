"""
DEMO DE PORTAFOLIO — Bot de Telegram para atención automática (FAQ)
====================================================================

Caso de uso real: un negocio chico (ej. una tienda, un emprendimiento,
una academia) recibe las mismas preguntas todo el día por Telegram/WhatsApp
("¿cuál es el horario?", "¿hacen envíos?", "¿cuánto cuesta X?"). Este bot
responde automáticamente usando un diccionario de FAQ configurable y,
si no encuentra coincidencia, deriva el mensaje a un humano.

Arquitectura:
- python-telegram-bot (librería oficial más usada, async, bien mantenida)
- FAQ_DB: diccionario simple (palabra clave -> respuesta). Para un cliente
  real esto podría vivir en un Google Sheet o base de datos, pero para
  un negocio chico un diccionario en el código ya resuelve el problema.
- Matching por palabras clave (simple y transparente). Se puede escalar
  a embeddings/IA si el cliente necesita entender lenguaje más libre.

Cómo correrlo:
1. pip install python-telegram-bot --break-system-packages
2. Crear un bot con @BotFather en Telegram y obtener el TOKEN
3. export TELEGRAM_TOKEN="tu_token_aqui"
4. python demo1_bot_faq_telegram.py
"""

import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuración del negocio (esto se personaliza por cliente) ---
NEGOCIO_NOMBRE = "Tienda Ejemplo"

FAQ_DB = {
    "horario": "Atendemos de lunes a viernes de 9:00 a 19:00, y sábados de 10:00 a 14:00.",
    "envio": "Hacemos envíos a todo Chile por Chilexpress. El costo se calcula según comuna.",
    "envios": "Hacemos envíos a todo Chile por Chilexpress. El costo se calcula según comuna.",
    "precio": "Los precios varían según el producto. Cuéntanos qué te interesa y te cotizamos al tiro.",
    "pago": "Aceptamos transferencia, Webpay y Mercado Pago.",
    "direccion": "Estamos ubicados en Av. Ejemplo 123, Santiago. Retiro en tienda con cita previa.",
    "contacto": "Puedes escribirnos por este mismo chat o al correo contacto@tiendaejemplo.cl",
}

MENSAJE_BIENVENIDA = (
    f"¡Hola! Soy el asistente virtual de {NEGOCIO_NOMBRE}. 🤖\n\n"
    "Puedo responder preguntas sobre: horario, envíos, precios, formas de pago, "
    "dirección y contacto.\n\n"
    "Escribe tu consulta y te ayudo, o escribe /humano si prefieres hablar con una persona."
)

MENSAJE_SIN_MATCH = (
    "No tengo una respuesta automática para eso todavía 🤔\n"
    "Un miembro del equipo va a revisar tu mensaje y te responderá pronto. "
    "Si es urgente, escribe /humano."
)


def buscar_respuesta(texto_usuario: str) -> str | None:
    """Busca coincidencias de palabras clave en el mensaje del usuario."""
    texto = texto_usuario.lower()
    for palabra_clave, respuesta in FAQ_DB.items():
        if palabra_clave in texto:
            return respuesta
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MENSAJE_BIENVENIDA)


async def humano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Perfecto, te conectamos con una persona del equipo. "
        "Mientras tanto, cuéntanos brevemente en qué te podemos ayudar."
    )
    # Aquí, en un caso real, se notificaría al dueño del negocio
    # (ej. reenviando el mensaje a un chat de administración).


async def responder_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    respuesta = buscar_respuesta(texto_usuario)

    if respuesta:
        await update.message.reply_text(respuesta)
        logger.info("Consulta resuelta automáticamente: %s", texto_usuario)
    else:
        await update.message.reply_text(MENSAJE_SIN_MATCH)
        logger.info("Consulta SIN match, requiere seguimiento humano: %s", texto_usuario)


def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError(
            "Falta la variable de entorno TELEGRAM_TOKEN. "
            "Créala con @BotFather en Telegram y expórtala antes de correr el script."
        )

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("humano", humano))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder_mensaje))

    logger.info("Bot corriendo. Ctrl+C para detener.")
    app.run_polling()


if __name__ == "__main__":
    main()
