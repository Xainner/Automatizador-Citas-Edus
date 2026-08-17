# 🏥 Automatizador de Citas EDUS

<p align="center">
  <img src="logo.png" alt="Automatizador de Citas EDUS" width="220">
</p>

<p align="center">
  Automatización inteligente de reserva de citas médicas en el sistema <b>EDUS</b> de la <b>CCSS</b> (Costa Rica) usando <b>Playwright</b> + <b>visión de IA</b> para resolución de CAPTCHAs.
</p>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python"></a>
  <a href="https://playwright.dev"><img src="https://img.shields.io/badge/Playwright-1.62+-green.svg" alt="Playwright"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License"></a>
  <a href="#"><img src="https://img.shields.io/badge/Status-Activo-brightgreen.svg" alt="Status"></a>
  <a href="#"><img src="https://img.shields.io/badge/PRs-Bienvenidos-orange.svg" alt="PRs"></a>
</p>

---

## Para quienes buscan una cita

Para todos aquellos que de verdad buscan una cita y el sistema simplemente no les va — los que madrugan a las 5 de la mañana, los que refrescan la página hasta el cansancio y los que ya no saben a quién pedir ayuda: esta herramienta es para ustedes.

---

## 🙏 Agradecimientos

Este proyecto fue generado a partir de la **guía/skill base** de **[jeudytuanisapps/automatizacion-citas-edus-ccss](https://github.com/jeudytuanisapps/automatizacion-citas-edus-ccss)**. Gracias por el excelente trabajo base que hizo posible este script. 🙌

---

## 📋 Tabla de Contenidos

- [Características](#-características)
- [Arquitectura](#-arquitectura)
- [Requisitos](#-requisitos)
- [Instalación](#-instalación)
- [Configuración](#-configuración)
- [Uso](#-uso)
- [Bot de Telegram](#-bot-de-telegram)
- [Docker Compose](#-docker-compose)
- [Cron Job](#-cron-job)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Créditos](#-créditos)
- [Licencia](#-licencia)

---

## ✨ Características

- 🔐 **Login automático** con resolución de CAPTCHA mediante **visión de IA** (LLM con capacidades visuales)
- 🔍 **Búsqueda inteligente** de cupos disponibles en tiempo real
- 📅 **Reserva automática** del primer cupo disponible (con verificación real de éxito)
- 🤖 **Bot de Telegram**: registra tus datos, busca al momento o programa búsquedas
- ⏰ **Monitoreo programado** desde las **5:59 AM** hora CR (los cupos se liberan a esa hora)
- 🔔 **Notificaciones** al reservar exitosamente una cita
- 🛡️ **Seguridad**: credenciales cifradas (Fernet) y solo en variables de entorno, nunca en código
- 🔄 **Auto-reintento**: si el CAPTCHA falla, descarga uno nuevo automáticamente (dedupe por mtime, sin repetir el mismo)
- 🛑 **Cancelación real**: `/cancelar` mata el proceso completo de búsqueda (script + Chromium) en segundos
- 🚪 **Cierre de sesión EDUS** al iniciar y terminar cada búsqueda — no deja sesiones pegadas en el servidor

---

## 🏗️ Arquitectura

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│  Cron Job    │────▶│ edus_citas   │────▶│  EDUS CCSS    │
│  (5:59-8am)  │     │   .py        │     │  (Playwright) │
└─────────────┘     └──────┬───────┘     └───────────────┘
                           │
                    ┌──────▼───────┐
                    │  CAPTCHA PNG │
                    └──────┬───────┘
                           │
                    ┌──────▼───────────┐
                    │  Visión de IA    │
                    │  (LLM Vision)    │
                    └──────┬───────────┘
                           │
                    ┌──────▼───────────┐
                    │  resolved.txt    │
                    │  (texto leído)   │
                    └──────────────────┘
```

### Flujo de trabajo

1. **Cron job** ejecuta el script a las 5:59 AM hora CR (cuando se liberan los cupos), luego cada 5 min hasta las 8 AM
2. **Playwright** navega al sitio EDUS, cierra cualquier sesión previa y descarga el CAPTCHA
3. **Visión de IA** lee el CAPTCHA y escribe el resultado
4. El script **inicia sesión** con las credenciales
5. **Busca cupos** de la especialidad configurada
6. **Reserva** el primer cupo disponible (con verificación real de éxito)
7. **Notifica** al usuario con los detalles de la cita
8. **Cierra sesión** en EDUS para no dejar sesiones pegadas

---

## 📦 Requisitos

- **Python** 3.11+
- **Playwright** + Chromium
- **Pillow** (PIL) para procesamiento de imágenes
- Agente de IA con **capacidades de visión** (para leer CAPTCHAs)

---

## 🚀 Instalación

```bash
# Clonar el repositorio
git clone https://github.com/<tu-usuario>/Automatizador-Citas-Edus.git
cd Automatizador-Citas-Edus

# Instalar dependencias
pip install -r requirements.txt

# Instalar Chromium para Playwright
playwright install chromium
```

---

## ⚙️ Configuración

### Variables de entorno

Crear un archivo `.env` (basado en `.env.example`):

```env
# Credenciales EDUS (obligatorio)
EDUS_CEDULA=tu_cedula
EDUS_CLAVE=tu_contraseña

# Configuración de cita (opcional)
SERVICIO=1              # 1 = MEDICINA
ESPECIALIDAD=1033       # 1033 = MEDICINA GENERAL
EXCLUIR_FECHAS=         # Fechas a excluir: DD/MM/AAAA,DD/MM/AAAA
```

> ⚠️ **Importante**: Nunca subas el archivo `.env` a Git. Contiene credenciales sensibles.

### Configuración de gitignore

El archivo `.gitignore` ya excluye:
- `.env` (credenciales)
- `__pycache__/` (archivos compilados)
- `/tmp/edus_captcha/` (imágenes temporales)

---

## 💻 Uso

### Modo manual

```bash
# Exportar variables de entorno
export EDUS_CEDULA="tu_cedula"
export EDUS_CLAVE="tu_contraseña"

# Ejecutar el script
python3 edus_citas.py
```

### Con archivo `.env`

```bash
# Cargar variables desde .env
set -a && source .env && set +a

# Ejecutar
python3 edus_citas.py
```

---

## 🤖 Bot de Telegram

El bot permite manejar todo desde Telegram: registras tus datos una vez y luego pides búsquedas al momento o programadas.

### Comandos (aparecen en el menú de Telegram)

| Comando | Descripción |
|---------|-------------|
| `/start` | Bienvenida e instrucciones |
| `/registrar` | Configurar nombre, cédula y clave (se guardan cifradas) |
| `/buscar` | Buscar una cita ahora mismo |
| `/programar` | Programar búsqueda automática (ej: `/programar 15/08/2026`) |
| `/cancelar` | Cancelar todas las búsquedas programadas |
| `/vision` | Configurar modelo de visión IA para el CAPTCHA |
| `/estado` | Ver configuración y programaciones |
| `/ayuda` | Ayuda rápida |

### Configuración del bot

En el `.env`:

```env
# Token del bot (crear con @BotFather en Telegram)
TELEGRAM_BOT_TOKEN=tu_token

# Clave para cifrar credenciales en la BD. Generar con:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SECRET_KEY=tu_clave_fernet

# Modelo de visión IA (OpenAI-compatible) para resolver CAPTCHAs
# Si no se configura, el bot pedirá al usuario que lea el captcha
VISION_BASE_URL=https://api.openai.com/v1
VISION_API_KEY=tu_api_key
VISION_MODEL=gpt-4o-mini

# Hora (CR) de la búsqueda programada — los cupos se liberan a las 5:59 AM
HORA_BUSQUEDA=5
MINUTO_BUSQUEDA=59
```

### Resolución de CAPTCHA

1. Si configuras un modelo de visión IA con `/vision` (o vía `VISION_BASE_URL` + `VISION_API_KEY` + `VISION_MODEL` en el `.env`), el bot envía la imagen del CAPTCHA al modelo y escribe el resultado automáticamente.
2. Si no hay modelo configurado (o falla), el bot **le envía la imagen al usuario por Telegram** y espera que le escriba el texto.

### Ejecutar el bot

```bash
pip install -r requirements.txt
python3 edus_bot.py
```

### Ejecutar el bot como servicio (systemd)

```ini
# /etc/systemd/system/edus-bot.service
[Unit]
Description=Bot de Telegram EDUS
After=network.target

[Service]
WorkingDirectory=/ruta/al/Automatizador-Citas-Edus
ExecStart=/ruta/a/python3 edus_bot.py
Restart=always
User=tu_usuario

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now edus-bot
```

---

## 🐳 Docker Compose

La forma más fácil de correr todo (bot + búsquedas programadas) es con Docker Compose. Incluye Python, Playwright/Chromium y cron en una sola imagen.

### Requisitos

- Docker + Docker Compose instalados (`docker compose version`)

### Configurar

1. Crear el `.env` a partir de la plantilla:

```bash
cp .env.example .env
```

2. Llenar al menos `TELEGRAM_BOT_TOKEN` y `SECRET_KEY` (y opcionalmente `VISION_*` para resolver CAPTCHAs con IA).

### Levantar

```bash
docker compose up -d --build
```

Esto levanta:
- **`bot`** — el bot de Telegram (siempre activo)
- **`cron`** — búsquedas automáticas: primera corrida a las **5:59 AM** y luego cada 5 min hasta las 8 AM (hora CR)

### Comandos útiles

```bash
docker compose ps              # estado de los servicios
docker compose logs -f bot     # logs del bot
docker compose logs -f cron    # logs de búsquedas programadas
docker compose up -d --build   # reconstruir y reiniciar
docker compose down            # detener (sin borrar datos)
docker compose down -v         # detener y borrar volúmenes (BD incluida)
```

### Persistencia

- La BD (`edus_bot.db`) y los CAPTCHAs se guardan en volúmenes Docker (`edus-data`, `edus-logs`) — sobreviven a `docker compose down`.
- Para reiniciar desde cero: `docker compose down -v` (⚠️ borra la BD y tus credenciales registradas).

### Notas Docker

- La hora de las búsquedas programadas se controla con `HORA_BUSQUEDA`/`MINUTO_BUSQUEDA` en el `.env` (default **5:59 AM CR**, cuando se liberan los cupos).
- El servicio `cron` solo es necesario si quieres búsquedas automáticas sin que nadie use el bot; con el bot activo, `/programar` cubre esa función.

---

## ⏰ Cron Job

### Uso con cron del sistema

```bash
# Editar crontab
crontab -e

# Primera corrida a las 5:59 AM (cupos se liberan a esa hora), luego cada 5 min hasta las 8 AM CST
59 5 * * * /ruta/al/edus_citas_schedule.sh
*/5 6-7 * * * /ruta/al/edus_citas_schedule.sh
```

El wrapper `edus_citas_schedule.sh` verifica el horario antes de ejecutar el script. Si tu intérprete de Python no está en el `PATH`, defínelo con:

```bash
PYTHON_BIN=/ruta/a/tu/python edus_citas_schedule.sh
```

> 💡 Con el bot de Telegram no hace falta cron: el bot programa la búsqueda por ti y te avisa por chat. El cron es la alternativa sin bot.

### Integración con Hermes Agent

El proyecto puede ejecutarse desde **Hermes Agent** como cron job inteligente: el agente lee los CAPTCHAs con visión de IA automáticamente y notifica al reservar una cita.

---

## 📁 Estructura del Proyecto

```
Automatizador-Citas-Edus/
├── logo.png                 # Logo del proyecto
├── README.md                # Este archivo
├── edus_citas.py            # Script principal de automatización
├── edus_bot.py              # Bot de Telegram
├── edus_db.py               # Base de datos SQLite (usuarios, programaciones)
├── edus_citas_schedule.sh   # Wrapper para cron job
├── Dockerfile               # Imagen Docker (Python + Chromium + cron)
├── docker-compose.yml       # Orquesta bot + cron
├── docker/
│   └── entrypoint-cron.sh   # Arranque del cron en el contenedor
├── requirements.txt         # Dependencias Python
├── .env.example             # Plantilla de configuración
└── .gitignore               # Archivos a ignorar en Git
```

---

## 🔧 Configuración avanzada

### Cambiar especialidad

| Código | Especialidad |
|--------|-------------|
| `1033` | Medicina General |
| `1034` | Pediatría |
| `1035` | Ginecología |
| `1036` | Cardiología |

> **Nota**: los códigos pueden variar según la región/área de salud. Verifica los valores reales en el sistema EDUS.

### Excluir fechas

```env
EXCLUIR_FECHAS=15/08/2026,16/08/2026
```

---

## ⚠️ Notas importantes

- Los cupos se liberan a las **5:59 AM** hora Costa Rica
- El sistema EDUS usa **JSF + PrimeFaces** con ViewState rotativo
- Las sesiones expiran rápido; el bot cierra la sesión explícitamente al terminar para no dejar sesiones pegadas
- Solo funciona con **cuentas EDUS reales** de la CCSS Costa Rica
- Este proyecto **no está afiliado** con la Caja Costarricense de Seguro Social

---

## 🙏 Créditos

Este proyecto está basado en el excelente trabajo de **[jeudytuanisapps/automatizacion-citas-edus-ccss](https://github.com/jeudytuanisapps/automatizacion-citas-edus-ccss)**.

### Mejoras sobre el proyecto original

- 👁️ **Resolución de CAPTCHA con visión de IA** (LLM con capacidades visuales) en lugar de Tesseract OCR, logrando mayor precisión
- 🔄 **Auto-reintento inteligente** con descarga de nuevo CAPTCHA si el login falla (dedupe por mtime para no repetir el mismo captcha)
- ✅ **Verificación real de reserva**: confirma la respuesta del servidor antes de declarar éxito
- 🛡️ **Credenciales solo por variables de entorno** (nunca hardcodeadas), cifradas con Fernet en la BD
- 🤖 **Bot de Telegram completo** con registro, búsqueda inmediata, programada y visión configurable por usuario
- ⏰ **Sincronizado con la liberación real de cupos**: primera búsqueda a las 5:59 AM CR
- 🛑 **Cancelación inmediata** desde el bot: mata el proceso completo (script + Chromium)
- 🚪 **Cierre de sesión explícito** en EDUS al terminar — sin sesiones pegadas que bloqueen logins futuros
- 📝 **Documentación profesional** en español

---

## 📄 Licencia

Este proyecto está bajo la licencia **MIT**. Ver el archivo [LICENSE](LICENSE) para más detalles.
