# Automatizador de Citas EDUS — imagen del bot + script + cron
# Un solo contenedor base con Python, Playwright/Chromium y cron.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=America/Costa_Rica \
    PYTHONDONTWRITEBYTECODE=1

# cron para el servicio de búsqueda programada + tzdata para hora CR
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias Python + Chromium de Playwright (con deps del sistema)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /root/.cache/pip

# Código de la app
COPY . .

# Directorios de datos persistentes (montados como volumen en compose)
RUN mkdir -p /app/data /app/logs \
    && chmod +x /app/docker/entrypoint-cron.sh /app/edus_citas_schedule.sh

# Servicio por defecto: el bot de Telegram
CMD ["python", "edus_bot.py"]
