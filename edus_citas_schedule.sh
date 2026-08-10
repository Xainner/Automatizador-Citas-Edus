#!/bin/bash
# EDUS Citas - Wrapper para cron job
# Ejecutar entre 5am-8am CST cada 5 minutos (los cupos salen ~5am)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Intérprete Python: sobrescribible con PYTHON_BIN; por defecto, python3 del PATH
PYTHON_BIN="${PYTHON_BIN:-python3}"
SCRIPT="$SCRIPT_DIR/edus_citas.py"
LOG="$SCRIPT_DIR/edus_errors.log"

# Solo ejecutar entre 5am-8am CST
HOUR=$(TZ='America/Costa_Rica' date +%H)
if [ "$HOUR" -ge 5 ] && [ "$HOUR" -lt 8 ]; then
    # Cargar variables de entorno si existe .env
    if [ -f "$SCRIPT_DIR/.env" ]; then
        set -a
        source "$SCRIPT_DIR/.env"
        set +a
    fi

    # Ejecutar script
    $PYTHON_BIN "$SCRIPT" 2>> "$LOG"
else
    echo "Fuera de horario (5am-8am CST). Hora actual: $(TZ='America/Costa_Rica' date '+%H:%M')" >> "$LOG"
fi
