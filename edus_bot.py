#!/usr/bin/env python3
"""
edus_bot.py — Bot de Telegram para el Automatizador de Citas EDUS.

Permite registrar las credenciales EDUS, buscar citas al momento y
programar búsquedas automáticas para un día específico.

Comandos (aparecen en el menú de Telegram):
  /start     — Bienvenida e instrucciones
  /registrar — Configurar nombre, cédula y clave
  /buscar    — Buscar una cita ahora mismo
  /programar — Programar búsqueda para un día (ej: /programar 15/08/2026)
  /cancelar  — Cancelar todas las búsquedas programadas
  /estado    — Ver tu configuración y programaciones
  /ayuda     — Ayuda rápida

Configuración (.env):
  TELEGRAM_BOT_TOKEN — token del bot (BotFather)
  SECRET_KEY         — clave Fernet para cifrar credenciales
  CAPTCHA_TIMEOUT    — segundos para que el usuario resuelva el captcha (default 60)
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from edus_db import EdusDB

load_dotenv()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN no está definido en el archivo .env")
    sys.exit(1)

# Zona horaria de Costa Rica (donde vive EDUS)
TZ_CR = ZoneInfo("America/Costa_Rica")
# Hora del día en que se ejecuta la búsqueda programada (los cupos se liberan a las 5:59am CR)
HORA_BUSQUEDA = int(os.environ.get("HORA_BUSQUEDA", "5"))
MINUTO_BUSQUEDA = int(os.environ.get("MINUTO_BUSQUEDA", "59"))

# ── Modelo de visión IA (OpenAI-compatible) para resolver CAPTCHAs ──
# Si no se configuran, el bot le pide al usuario que resuelva el captcha.
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "").strip()
VISION_API_KEY = os.environ.get("VISION_API_KEY", "").strip()
VISION_MODEL = os.environ.get("VISION_MODEL", "").strip()

# Estados del flujo de registro
NOMBRE, CEDULA, CLAVE = range(3)

# Estado del flujo de programación
PREGUNTAR_FECHA = 10

# Estados del flujo de configuración de visión
VIS_URL, VIS_KEY, VIS_MODEL = 20, 21, 22

CAPTCHA_TIMEOUT = int(os.environ.get("CAPTCHA_TIMEOUT", "60"))

# Captchas pendientes: chat_id -> (evento asyncio, texto resuelto)
_captchas = {}
# subprocesos de búsqueda en curso por chat (para poder cancelarlos)
_procesos = {}
# chats que pidieron cancelar la búsqueda en curso
_cancelados = set()
# último waiting.txt resuelto por chat (deduplicación de captchas)
_ultimo_waiting = {}
# contador de captchas resueltos por chat en la búsqueda actual
_n_captcha = {}

# Búsquedas en curso por chat (evita duplicados)
_buscando = set()

db = EdusDB()

# Script que ejecuta la búsqueda real
SCRIPT = Path(__file__).resolve().parent / "edus_citas.py"
PYTHON = sys.executable

# Directorio de captchas: configurable (usar volumen en Docker), default junto al código
CAPTCHA_DIR_BOT = Path(os.environ.get(
    "CAPTCHA_DIR",
    str(Path(__file__).resolve().parent / "captchas"),
))

COMANDOS = [
    BotCommand("start", "Bienvenida e instrucciones"),
    BotCommand("registrar", "Configurar nombre, cédula y clave"),
    BotCommand("buscar", "Buscar una cita ahora mismo"),
    BotCommand("programar", "Programar búsqueda (ej: /programar 15/08/2026)"),
    BotCommand("cancelar", "Cancelar búsquedas programadas"),
    BotCommand("vision", "Configurar modelo de visión IA para el CAPTCHA"),
    BotCommand("estado", "Ver configuración y programaciones"),
    BotCommand("ayuda", "Ayuda rápida"),
]

# ── Utilidades ────────────────────────────────────────────────

def es_fecha_valida(texto: str) -> bool:
    """Valida DD/MM/AAAA y que no sea una fecha pasada."""
    try:
        fecha = datetime.strptime(texto.strip(), "%d/%m/%Y")
    except ValueError:
        return False
    return fecha.date() >= datetime.now().date()


def formatear_fecha(fecha_texto: str) -> str:
    """Convierte DD/MM/AAAA a 'lunes 15 de agosto de 2026'."""
    try:
        f = datetime.strptime(fecha_texto.strip(), "%d/%m/%Y")
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        return f"{dias[f.weekday()]} {f.day} de {meses[f.month - 1]} de {f.year}"
    except ValueError:
        return fecha_texto


def requiere_registro(func):
    """Decorador: exige que el usuario esté registrado."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.obtener_usuario(update.effective_chat.id)
        if not user:
            await update.effective_chat.send_message(
                "⚠️ Primero necesito tus datos. Usa /registrar para configurar "
                "tu nombre, cédula y clave de EDUS."
            )
            return
        return await func(update, context, user)
    return wrapper


# ── Comandos básicos ──────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = db.obtener_usuario(chat.id)
    mensaje = (
        "¡Hola! 👋 Soy el asistente de citas de EDUS.\n\n"
        "Te ayudo a buscar y reservar citas médicas en la CCSS, "
        "y a programar búsquedas automáticas.\n\n"
    )
    if user:
        mensaje += (
            f"Ya estás registrado como *{user['nombre']}* (cédula "
            f"`{user['cedula']}`).\n\n"
            "¿Qué hacemos hoy?\n"
            "• /buscar — buscar una cita ahora\n"
            "• /programar — programar para un día\n"
            "• /estado — ver tu configuración"
        )
    else:
        mensaje += "Para empezar, registra tus datos con /registrar. 📝"
    await chat.send_message(mensaje, parse_mode=ParseMode.MARKDOWN)


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "🤖 *Asistente EDUS* — ayuda\n\n"
        "• /registrar — configuro tu nombre, cédula y clave (se guardan cifradas)\n"
        "• /buscar — busco cupos disponibles en este momento\n"
        "• /programar — programo una búsqueda para un día (ej: /programar 15/08/2026)\n"
        "• /vision — configuro un modelo de IA para leer los códigos de seguridad\n"
        "• /cancelar — cancelo todas las búsquedas programadas\n"
        "• /estado — te muestro tus datos y programaciones\n\n"
        "Cuando busque una cita y el sistema pida un código de seguridad, "
        "lo resolveré automáticamente si configuraste /vision; si no, "
        "te enviaré la imagen y tú me escribes el texto. 🙏",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Registro (ConversationHandler) ────────────────────────────

async def reg_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "📝 Perfecto, configuremos tus datos.\n\n"
        "¿Cómo te llamas?"
    )
    return NOMBRE


async def reg_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nombre"] = update.message.text.strip()
    await update.message.reply_text(
        f"Mucho gusto, *{context.user_data['nombre']}* ✨\n\n"
        "Ahora, ¿cuál es tu número de cédula? (9 dígitos)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return CEDULA


async def reg_cedula(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cedula = update.message.text.strip()
    if not (cedula.isdigit() and len(cedula) == 9):
        await update.message.reply_text(
            "❌ La cédula debe tener 9 dígitos numéricos. Intenta de nuevo:"
        )
        return CEDULA
    context.user_data["cedula"] = cedula
    await update.message.reply_text(
        "✅ Cédula registrada.\n\n"
        "Ahora, ¿cuál es tu clave de EDUS? (se guarda cifrada, nadie la verá)"
    )
    return CLAVE


async def reg_clave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clave = update.message.text.strip()
    if len(clave) < 4:
        await update.message.reply_text(
            "❌ Esa clave parece muy corta. Intenta de nuevo:"
        )
        return CLAVE

    db.registrar_usuario(
        telegram_id=update.effective_chat.id,
        nombre=context.user_data["nombre"],
        cedula=context.user_data["cedula"],
        clave=clave,
    )

    # Seguridad: borrar el mensaje con la contraseña del chat
    try:
        await update.message.delete()
    except Exception:
        pass

    await update.effective_chat.send_message(
        "🎉 ¡Listo! Ya quedé registrado.\n\n"
        "Ahora puedes:\n"
        "• /buscar — buscar una cita ahora\n"
        "• /programar — programar para un día"
    )
    return ConversationHandler.END


async def reg_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback de conversación: cancela programaciones reales y cierra la conversación."""
    chat_id = update.effective_chat.id
    n = db.cancelar_pendientes(chat_id)
    if context.job_queue:
        for job in context.job_queue.jobs():
            data = job.data or {}
            if data.get("chat_id") == chat_id:
                try:
                    job.schedule_removal()
                except Exception:
                    pass
    if n:
        await update.message.reply_text(f"🚫 Cancelé {n} búsqueda(s) programada(s).")
    else:
        await update.message.reply_text("🚫 Operación cancelada.")
    return ConversationHandler.END


# ── Búsqueda ahora ────────────────────────────────────────────

@requiere_registro
async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    chat_id = update.effective_chat.id

    if chat_id in _buscando:
        await update.effective_chat.send_message(
            "⏳ Ya hay una búsqueda en curso. Espera a que termine, por favor."
        )
        return

    fecha_objetivo = ""
    if context.args:
        fecha_arg = " ".join(context.args).strip()
        if not es_fecha_valida(fecha_arg):
            await update.effective_chat.send_message(
                "❌ Formato de fecha incorrecto. Usa DD/MM/AAAA, por ejemplo: "
                "`/buscar 15/08/2026` o simplemente `/buscar`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        fecha_objetivo = fecha_arg

    await update.effective_chat.send_message(
        "🔍 *Buscando cita…* Dame unos minutos. Te iré contando cómo va.\n"
        "Si el sistema pide un código de seguridad, te enviaré la imagen. "
        "Es normal, es solo un paso más. ✨",
        parse_mode=ParseMode.MARKDOWN,
    )

    _buscando.add(chat_id)
    try:
        await ejecutar_busqueda(update.effective_chat, user, fecha_objetivo)
    finally:
        _buscando.discard(chat_id)


async def ejecutar_busqueda(chat, user, fecha_objetivo: str = ""):
    """Ejecuta el script EDUS como subproceso y traduce el progreso."""
    clave = db.descifrar_clave(user["clave_cifrada"])

    env = os.environ.copy()
    env.update({
        "EDUS_CEDULA": user["cedula"],
        "EDUS_CLAVE": clave,
        "SERVICIO": user["servicio"],
        "ESPECIALIDAD": user["especialidad"],
        "CAPTCHA_DIR": str(CAPTCHA_DIR_BOT),
        "PYTHONUNBUFFERED": "1",
    })
    if fecha_objetivo:
        env["FECHA_OBJETIVO"] = fecha_objetivo

    if fecha_objetivo:
        await chat.send_message(f"📅 Buscando citas para el *{formatear_fecha(fecha_objetivo)}*.")
    else:
        await chat.send_message("📅 Buscando cualquier cita disponible.")

    try:
        proc = await asyncio.create_subprocess_exec(
            PYTHON, str(SCRIPT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except Exception as e:
        await chat.send_message(f"❌ No pude iniciar la búsqueda: {e}")
        return

    # Registrar el proceso para poder cancelarlo con /cancelar
    _procesos[chat.id] = proc

    captcha_dir = CAPTCHA_DIR_BOT
    captcha_dir.mkdir(exist_ok=True)

    resultado = "sin_resultado"
    try:
        while True:
            linea = await proc.stdout.readline()
            if not linea:
                break
            texto = linea.decode(errors="replace").strip()
            print(f"[edus] {texto}")  # log local

            if "LOGIN EXITOSO" in texto:
                await chat.send_message("✅ Entré al sistema de EDUS con tus datos.")
            elif "cupo(s) disponible" in texto:
                await chat.send_message("🎯 ¡Hay cupos disponibles! Voy a intentar reservar uno.")
            elif "Cita reservada" in texto or "¡¡Cita reservada!!" in texto:
                resultado = "reservada"
            elif "No hay cupos" in texto or "no hay cupos" in texto:
                resultado = "sin_cupos"
            elif "no está disponible" in texto or "asignada a otro" in texto:
                await chat.send_message("😔 Ese cupo ya no estaba disponible, pruebo otro…")
            elif "Login" in texto and ("falló" in texto or "incorrecta" in texto or "Error" in texto):
                resultado = "login_fallido"

            # ¿El script pidió un captcha? (solo si es uno NUEVO, no el ya resuelto)
            waiting = captcha_dir / "waiting.txt"
            if waiting.exists():
                contenido = waiting.read_text().strip()
                if contenido != _ultimo_waiting.get(chat.id):
                    _ultimo_waiting[chat.id] = contenido
                    _n_captcha[chat.id] = _n_captcha.get(chat.id, 0) + 1
                    vision = db.obtener_vision(chat.id)
                    await resolver_captcha(chat, captcha_dir, waiting, vision)
                    # Borrar para no reprocesar el mismo captcha en la próxima vuelta
                    try:
                        waiting.unlink()
                    except Exception:
                        pass
    finally:
        _procesos.pop(chat.id, None)
        _ultimo_waiting.pop(chat.id, None)
        _n_captcha.pop(chat.id, None)
        try:
            await proc.wait()
        except Exception:
            pass

    # Si el usuario canceló, reportarlo y terminar
    if chat.id in _cancelados:
        _cancelados.discard(chat.id)
        await chat.send_message("🛑 Búsqueda cancelada. Cuando quieras, vuelve a intentar con /buscar.")
        return

    # Traducir el resultado final
    if resultado == "reservada":
        await chat.send_message(
            "🎉 *¡Cita reservada con éxito!*\n"
            "Revisa el comprobante en EDUS. Si quieres, busca otra con /buscar.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif resultado == "sin_cupos":
        await chat.send_message(
            "😔 *No hay cupos disponibles* en este momento.\n"
            "Suelen liberarse temprano en la mañana. Puedes programar una "
            "búsqueda con /programar.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif resultado == "login_fallido":
        await chat.send_message(
            "❌ *No pude entrar* con tus datos. Revisa tu cédula y clave con "
            "/registrar, y vuelve a intentar.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await chat.send_message(
            "⚠️ La búsqueda terminó sin un resultado claro. Intenta de nuevo "
            "con /buscar en unos minutos."
        )


async def resolver_captcha(chat, captcha_dir: Path, waiting: Path, vision: dict | None = None):
    """Resuelve el captcha: primero con IA de visión, luego con el usuario."""
    ruta_captcha = waiting.read_text().strip()
    img_path = Path(ruta_captcha)
    if not img_path.exists():
        # buscar alternativas en el directorio
        candidatos = list(captcha_dir.glob("*.png"))
        if not candidatos:
            return
        img_path = candidatos[-1]

    # 1) Intentar con modelo de visión IA (config del usuario, o env vars)
    texto_ia = await resolver_captcha_con_ia(img_path, vision)
    if texto_ia:
        (captcha_dir / "resolved.txt").write_text(texto_ia)
        intento = _n_captcha.get(chat.id, 1)
        if intento > 1:
            await chat.send_message(
                f"🤖 Código de seguridad resuelto automáticamente (intento {intento}). ¡Continúo! ✨"
            )
        else:
            await chat.send_message(
                "🤖 Código de seguridad resuelto automáticamente. ¡Continúo! ✨"
            )
        return

    # 2) Fallback: pedirle al usuario
    chat_id = chat.id
    evento = asyncio.Event()
    _captchas[chat_id] = {"evento": evento, "texto": ""}

    try:
        with open(img_path, "rb") as f:
            await chat.send_photo(
                f,
                caption=(
                    "🧩 El sistema pide un *código de seguridad*.\n"
                    "Escríbeme el texto que ves en la imagen (sin espacios)."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
    except Exception:
        return

    try:
        await asyncio.wait_for(evento.wait(), timeout=CAPTCHA_TIMEOUT)
    except asyncio.TimeoutError:
        await chat.send_message("⏰ Se agotó el tiempo para el código. Reintentando…")
        (captcha_dir / "resolved.txt").write_text("")
        return

    texto = _captchas[chat_id]["texto"]

    # El usuario canceló mientras esperaba el código
    if texto == "__CANCELAR__":
        await chat.send_message("🛑 Cancelado. Detengo la búsqueda.")
        return

    (captcha_dir / "resolved.txt").write_text(texto)
    await chat.send_message("✅ ¡Gracias! Continúo con la búsqueda…")


async def resolver_captcha_con_ia(img_path: Path, vision: dict | None = None) -> str:
    """Intenta leer el captcha con un modelo de visión OpenAI-compatible.

    Usa la config de visión del usuario (dict con base_url/api_key/model)
    si existe; si no, las variables de entorno VISION_*. Devuelve el texto
    leído, o string vacío si no hay modelo o la lectura falla (fallback usuario).
    """
    if vision:
        base_url = vision.get("base_url", "")
        api_key = vision.get("api_key", "")
        model = vision.get("model", "")
    else:
        base_url, api_key, model = VISION_BASE_URL, VISION_API_KEY, VISION_MODEL

    if not (base_url and api_key and model):
        return ""

    import base64
    import json

    try:
        import httpx
    except ImportError:
        print("[bot] ⚠️ httpx no está instalado; no se puede usar visión IA")
        return ""

    b64 = base64.b64encode(img_path.read_bytes()).decode()
    data_url = f"data:image/png;base64,{b64}"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Este es un CAPTCHA con caracteres alfanuméricos. "
                            "Responde SOLO con el texto exacto del captcha, "
                            "sin explicaciones ni espacios."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": 10,
        "temperature": 0,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            texto = data["choices"][0]["message"]["content"].strip()
        # Limpiar: quedarse solo con caracteres alfanuméricos
        texto = "".join(ch for ch in texto if ch.isalnum())
        print(f"[bot] 🤖 CAPTCHA leído por IA: {texto}")
        return texto
    except Exception as e:
        print(f"[bot] ⚠️ Visión IA falló: {e}")
        return ""


async def manejar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Si hay un captcha pendiente para este chat, lo resuelve."""
    chat_id = update.effective_chat.id
    pendiente = _captchas.get(chat_id)
    if pendiente and not pendiente["evento"].is_set():
        texto = update.message.text.strip()
        if texto and not texto.startswith("/"):
            pendiente["texto"] = texto
            pendiente["evento"].set()
            return
    await update.message.reply_text(
        "No entendí. Usa /ayuda para ver qué puedo hacer."
    )


# ── Programar búsqueda ────────────────────────────────────────

@requiere_registro
async def cmd_programar(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    if context.args:
        fecha = " ".join(context.args).strip()
        return await confirmar_programacion(update, context, user, fecha)
    await update.effective_chat.send_message(
        "📅 ¿Para qué día quieres que busque? Escríbeme la fecha en formato "
        "DD/MM/AAAA, por ejemplo: 15/08/2026"
    )
    return PREGUNTAR_FECHA


async def programar_fecha_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fecha = update.message.text.strip()
    user = db.obtener_usuario(update.effective_chat.id)
    if not user:
        await update.message.reply_text("⚠️ Primero regístrate con /registrar.")
        return ConversationHandler.END
    return await confirmar_programacion(update, context, user, fecha)


async def confirmar_programacion(update, context, user, fecha: str):
    if not es_fecha_valida(fecha):
        await update.effective_chat.send_message(
            "❌ Esa fecha no es válida. Usa formato DD/MM/AAAA y una fecha "
            "de hoy en adelante. Ejemplo: /programar 15/08/2026"
        )
        return PREGUNTAR_FECHA

    # Guardar en BD
    prog_id = db.programar_busqueda(update.effective_chat.id, fecha)

    # Programar el job de Telegram: 5:00 AM (hora CR) del día indicado
    try:
        fecha_dt = datetime.strptime(fecha, "%d/%m/%Y")
        cuando = datetime.combine(
            fecha_dt.date(),
            dt_time(HORA_BUSQUEDA, MINUTO_BUSQUEDA),
            tzinfo=TZ_CR,
        )
        context.job_queue.run_once(
            job_busqueda_programada,
            when=cuando,
            data={"prog_id": prog_id, "fecha": fecha, "chat_id": update.effective_chat.id},
            name=f"edus_prog_{prog_id}",
        )
    except Exception as e:
        print(f"[bot] No se pudo programar job: {e}")
        db.marcar_programacion(prog_id, "cancelada")
        await update.effective_chat.send_message(
            "❌ Ocurrió un error al programar la búsqueda automática "
            "(job_queue no disponible). La programación fue cancelada. "
            "Reporta este error al administrador.",
        )
        return ConversationHandler.END

    await update.effective_chat.send_message(
        f"📅 *Búsqueda programada* para el *{formatear_fecha(fecha)}*.\n\n"
        "Cuando llegue el momento, buscaré automáticamente y te avisaré "
        "por aquí. Puedes cancelarla con /cancelar.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def job_busqueda_programada(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    chat_id = data["chat_id"]
    fecha = data["fecha"]

    if chat_id in _buscando:
        return

    user = db.obtener_usuario(chat_id)
    if not user:
        return

    db.marcar_programacion(data["prog_id"], "ejecutada")

    _buscando.add(chat_id)
    try:
        chat = await context.bot.get_chat(chat_id)
        await chat.send_message(
            f"⏰ ¡Llegó la hora! Busco citas para el *{formatear_fecha(fecha)}*. 🤞",
            parse_mode=ParseMode.MARKDOWN,
        )
        await ejecutar_busqueda(chat, user, fecha)
    finally:
        _buscando.discard(chat_id)


# ── Configuración de visión IA ───────────────────────────────

@requiere_registro
async def vis_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    chat_id = update.effective_chat.id
    actual = db.obtener_vision(chat_id)
    if actual:
        await update.effective_chat.send_message(
            f"🤖 Tienes visión IA configurada:\n"
            f"• URL: `{actual['base_url']}`\n"
            f"• Modelo: `{actual['model']}`\n\n"
            "Si quieres cambiarla, dime la nueva *URL base* del servicio "
            "(ej: `https://api.openai.com/v1`). O escribe /cancelar para dejarla igual.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.effective_chat.send_message(
            "🤖 Configura un modelo de visión IA para leer los códigos de seguridad "
            "automáticamente (compatible con OpenAI).\n\n"
            "Dime la *URL base* del servicio, por ejemplo: `https://api.openai.com/v1`",
            parse_mode=ParseMode.MARKDOWN,
        )
    return VIS_URL


async def vis_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip().rstrip("/")
    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text(
            "❌ Esa URL no parece válida. Debe empezar con http:// o https://. "
            "Intenta de nuevo (o /cancelar):"
        )
        return VIS_URL
    context.user_data["vis_url"] = url
    await update.message.reply_text(
        "✅ URL guardada.\n\nAhora dime tu *API key* (se guarda cifrada). "
        "Si no quieres usar clave, escribe: no",
        parse_mode=ParseMode.MARKDOWN,
    )
    return VIS_KEY


async def vis_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = update.message.text.strip()
    context.user_data["vis_key"] = key if key.lower() != "no" else ""

    # Seguridad: borrar el mensaje con la API key del chat
    try:
        await update.message.delete()
    except Exception:
        pass

    await update.effective_chat.send_message(
        "✅ Listo.\n\nAhora dime el *nombre del modelo*, por ejemplo: `gpt-4o-mini`",
        parse_mode=ParseMode.MARKDOWN,
    )
    return VIS_MODEL


async def vis_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    model = update.message.text.strip()
    if not model:
        await update.message.reply_text("❌ El nombre del modelo no puede estar vacío. Intenta de nuevo:")
        return VIS_MODEL

    db.guardar_vision(
        telegram_id=update.effective_chat.id,
        base_url=context.user_data["vis_url"],
        api_key=context.user_data["vis_key"],
        model=model,
    )
    await update.message.reply_text(
        f"🎉 ¡Visión IA configurada!\n"
        f"• URL: `{context.user_data['vis_url']}`\n"
        f"• Modelo: `{model}`\n\n"
        "Los códigos de seguridad se resolverán automáticamente en tus búsquedas. "
        "Puedes cambiar esto cuando quieras con /vision.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ── Cancelar y estado ─────────────────────────────────────────

async def cmd_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    mensajes = []

    # Cancelar búsqueda programadas
    n = db.cancelar_pendientes(chat_id)
    if n:
        mensajes.append(f"🚫 Cancelé {n} búsqueda(s) programada(s).")

    # Cancelar jobs en memoria (solo los de este chat)
    if context.job_queue:
        for job in context.job_queue.jobs():
            data = job.data or {}
            if data.get("chat_id") == chat_id:
                try:
                    job.schedule_removal()
                except Exception:
                    pass

    # Interrumpir una búsqueda en curso (esperando captcha o no)
    pendiente = _captchas.get(chat_id)
    if pendiente and not pendiente["evento"].is_set():
        pendiente["texto"] = "__CANCELAR__"
        pendiente["evento"].set()

    proc = _procesos.get(chat_id)
    if proc is not None and proc.returncode is None:
        _cancelados.add(chat_id)
        try:
            proc.terminate()
        except Exception:
            pass
        mensajes.append("🛑 Deteniendo la búsqueda en curso…")

    if mensajes:
        await update.effective_chat.send_message("\n".join(mensajes))
    else:
        await update.effective_chat.send_message(
            "No había búsquedas programadas ni en curso. 😌"
        )


@requiere_registro
async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    progs = db.programaciones_pendientes(update.effective_chat.id)
    vision = db.obtener_vision(update.effective_chat.id)
    texto = (
        f"👤 *Tu configuración*\n"
        f"Nombre: {user['nombre']}\n"
        f"Cédula: `{user['cedula']}`\n"
        f"Especialidad: Medicina General\n"
    )
    if vision:
        texto += f"🤖 Visión IA: `{vision['model']}`\n"
    else:
        texto += "🤖 Visión IA: no configurada (usa /vision)\n"
    texto += "\n"
    if progs:
        texto += "📅 *Búsquedas programadas:*\n"
        for p in progs:
            texto += f"  • {formatear_fecha(p['fecha'])}\n"
    else:
        texto += "📅 No tienes búsquedas programadas."
    await update.effective_chat.send_message(texto, parse_mode=ParseMode.MARKDOWN)


# ── Re-agendamiento al arranque ──────────────────────────────

async def reagendar_pendientes(app: Application):
    """Re-agenda en el job_queue las búsquedas pendientes guardadas en BD.

    El job_queue de PTB vive en memoria: si el bot se reinicia, los jobs
    desaparecen aunque la BD siga teniendo programaciones 'pendiente'.
    Esta función las vuelve a programar al arrancar.
    """
    ahora = datetime.now(TZ_CR)
    for p in db.programaciones_pendientes():
        try:
            fecha_dt = datetime.strptime(p["fecha"], "%d/%m/%Y")
            cuando = datetime.combine(
                fecha_dt.date(),
                dt_time(HORA_BUSQUEDA, MINUTO_BUSQUEDA),
                tzinfo=TZ_CR,
            )
            if cuando < ahora:
                # Fecha pasada sin ejecutar: cancelar en vez de dejar huérfana
                db.marcar_programacion(p["id"], "cancelada")
                print(f"[bot] Programación #{p['id']} ({p['fecha']}) vencida sin ejecutar → cancelada")
                continue
            app.job_queue.run_once(
                job_busqueda_programada,
                when=cuando,
                data={"prog_id": p["id"], "fecha": p["fecha"], "chat_id": p["telegram_id"]},
                name=f"edus_prog_{p['id']}",
            )
            print(f"[bot] Re-agendada búsqueda #{p['id']} para {p['fecha']} a las {cuando:%H:%M} CR")
        except Exception as e:
            print(f"[bot] No se pudo re-agendar #{p['id']}: {e}")


# ── Main ──────────────────────────────────────────────────────

def main():
    import logging
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    app = Application.builder().token(TOKEN).build()

    # Comandos del menú + re-agendar búsquedas pendientes tras un reinicio
    async def post_init(app: Application):
        await app.bot.set_my_commands(COMANDOS)
        await reagendar_pendientes(app)

    app.post_init = post_init

    # Registro (conversación)
    conv_registro = ConversationHandler(
        entry_points=[CommandHandler("registrar", reg_inicio)],
        states={
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_nombre)],
            CEDULA: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_cedula)],
            CLAVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_clave)],
        },
        fallbacks=[CommandHandler("cancelar", reg_cancelar)],
    )

    # Programación (conversación para pedir fecha)
    conv_programar = ConversationHandler(
        entry_points=[CommandHandler("programar", cmd_programar)],
        states={
            PREGUNTAR_FECHA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, programar_fecha_texto)
            ],
        },
        fallbacks=[CommandHandler("cancelar", reg_cancelar)],
    )

    # Visión IA (conversación para configurar URL, API key y modelo)
    conv_vision = ConversationHandler(
        entry_points=[CommandHandler("vision", vis_inicio)],
        states={
            VIS_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, vis_url)],
            VIS_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, vis_key)],
            VIS_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, vis_model)],
        },
        fallbacks=[CommandHandler("cancelar", reg_cancelar)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ayuda", cmd_ayuda))
    app.add_handler(conv_registro)
    app.add_handler(conv_programar)
    app.add_handler(conv_vision)
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))
    app.add_handler(CommandHandler("estado", cmd_estado))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))

    print("🤖 Bot EDUS iniciado. Esperando mensajes…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
