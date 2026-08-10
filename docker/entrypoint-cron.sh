#!/bin/bash
# entrypoint-cron.sh — arranca el cron del contenedor para búsquedas programadas
# Ejecuta edus_citas_schedule.sh cada 5 min entre 5-7am (hora del contenedor = CR).
set -e

# Configurar crontab (el TZ del contenedor es America/Costa_Rica)
cat > /etc/cron.d/edus-citas <<'EOF'
*/5 5-7 * * * root /app/edus_citas_schedule.sh >> /app/logs/cron.log 2>&1
EOF
chmod 0644 /etc/cron.d/edus-citas
touch /app/logs/cron.log

echo "[cron] Búsquedas programadas cada 5 min entre 5-7am (Costa Rica)"
exec cron -f
