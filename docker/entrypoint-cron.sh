#!/bin/bash
# entrypoint-cron.sh — arranca el cron del contenedor para búsquedas programadas
# Ejecuta edus_citas_schedule.sh: primera corrida a las 5:59am y luego cada 5 min
# hasta las 8am (hora del contenedor = CR). Los cupos se liberan a las 5:59am.
set -e

# Configurar crontab (el TZ del contenedor es America/Costa_Rica)
cat > /etc/cron.d/edus-citas <<'EOF'
59 5 * * * root /app/edus_citas_schedule.sh >> /app/logs/cron.log 2>&1
*/5 6-7 * * * root /app/edus_citas_schedule.sh >> /app/logs/cron.log 2>&1
EOF
chmod 0644 /etc/cron.d/edus-citas
touch /app/logs/cron.log

echo "[cron] Búsquedas programadas: 5:59am y cada 5 min hasta las 8am (Costa Rica)"
exec cron -f
