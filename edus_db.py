"""
edus_db.py — Capa de base de datos SQLite para el bot de Telegram.

Guarda usuarios (con credenciales EDUS cifradas con Fernet) y
búsquedas programadas. Sin dependencias externas más allá de cryptography.
"""
import os
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet

# Ruta de la BD: configurable (usar volumen en Docker), default junto al código
DB_PATH = Path(os.environ.get(
    "EDUS_DB_PATH",
    str(Path(__file__).resolve().parent / "edus_bot.db"),
))


def _get_cipher() -> Fernet:
    """Cifrador Fernet basado en SECRET_KEY del entorno."""
    key = os.environ.get("SECRET_KEY", "").encode()
    if not key:
        raise RuntimeError(
            "SECRET_KEY no definida. Genera una con: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key)


class EdusDB:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._crear_tablas()

    def _crear_tablas(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                telegram_id   INTEGER PRIMARY KEY,
                nombre        TEXT NOT NULL,
                cedula        TEXT NOT NULL,
                clave_cifrada TEXT NOT NULL,
                servicio      TEXT DEFAULT '1',
                especialidad  TEXT DEFAULT '1033',
                creado_en     TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS programaciones (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id  INTEGER NOT NULL,
                fecha        TEXT NOT NULL,           -- DD/MM/AAAA
                estado       TEXT DEFAULT 'pendiente', -- pendiente | ejecutada | cancelada
                creado_en    TEXT DEFAULT (datetime('now'))
            );
            """
        )
        # Migración: columnas de visión IA (BD existentes no las tienen)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(usuarios)")}
        if "vision_base_url" not in cols:
            self.conn.execute("ALTER TABLE usuarios ADD COLUMN vision_base_url TEXT DEFAULT ''")
        if "vision_api_key_cifrada" not in cols:
            self.conn.execute("ALTER TABLE usuarios ADD COLUMN vision_api_key_cifrada TEXT DEFAULT ''")
        if "vision_model" not in cols:
            self.conn.execute("ALTER TABLE usuarios ADD COLUMN vision_model TEXT DEFAULT ''")
        self.conn.commit()

    # ── Usuarios ──────────────────────────────────────────────
    def registrar_usuario(self, telegram_id: int, nombre: str, cedula: str, clave: str,
                          servicio: str = "1", especialidad: str = "1033"):
        clave_cifrada = _get_cipher().encrypt(clave.encode()).decode()
        self.conn.execute(
            """
            INSERT INTO usuarios (telegram_id, nombre, cedula, clave_cifrada, servicio, especialidad)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                nombre = excluded.nombre,
                cedula = excluded.cedula,
                clave_cifrada = excluded.clave_cifrada,
                servicio = excluded.servicio,
                especialidad = excluded.especialidad
            """,
            (telegram_id, nombre, cedula, clave_cifrada, servicio, especialidad),
        )
        self.conn.commit()

    def obtener_usuario(self, telegram_id: int) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM usuarios WHERE telegram_id = ?", (telegram_id,))
        return cur.fetchone()

    def descifrar_clave(self, clave_cifrada: str) -> str:
        return _get_cipher().decrypt(clave_cifrada.encode()).decode()

    # ── Visión IA por usuario ─────────────────────────────────
    def guardar_vision(self, telegram_id: int, base_url: str, api_key: str, model: str):
        api_key_cifrada = _get_cipher().encrypt(api_key.encode()).decode()
        self.conn.execute(
            "UPDATE usuarios SET vision_base_url = ?, vision_api_key_cifrada = ?, "
            "vision_model = ? WHERE telegram_id = ?",
            (base_url, api_key_cifrada, model, telegram_id),
        )
        self.conn.commit()

    def obtener_vision(self, telegram_id: int) -> dict:
        """Devuelve la config de visión del usuario o {} si no tiene."""
        row = self.conn.execute(
            "SELECT vision_base_url, vision_api_key_cifrada, vision_model "
            "FROM usuarios WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not row or not row["vision_base_url"] or not row["vision_model"]:
            return {}
        try:
            api_key = _get_cipher().decrypt(row["vision_api_key_cifrada"].encode()).decode()
        except Exception:
            return {}
        return {
            "base_url": row["vision_base_url"],
            "api_key": api_key,
            "model": row["vision_model"],
        }

    def limpiar_vision(self, telegram_id: int):
        self.conn.execute(
            "UPDATE usuarios SET vision_base_url = '', vision_api_key_cifrada = '', "
            "vision_model = '' WHERE telegram_id = ?",
            (telegram_id,),
        )
        self.conn.commit()

    # ── Programaciones ────────────────────────────────────────
    def programar_busqueda(self, telegram_id: int, fecha: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO programaciones (telegram_id, fecha) VALUES (?, ?)",
            (telegram_id, fecha),
        )
        self.conn.commit()
        return cur.lastrowid

    def programaciones_pendientes(self, telegram_id: int | None = None) -> list[sqlite3.Row]:
        if telegram_id is None:
            cur = self.conn.execute(
                "SELECT * FROM programaciones WHERE estado = 'pendiente' ORDER BY fecha")
        else:
            cur = self.conn.execute(
                "SELECT * FROM programaciones WHERE estado = 'pendiente' AND telegram_id = ? "
                "ORDER BY fecha",
                (telegram_id,),
            )
        return cur.fetchall()

    def marcar_programacion(self, prog_id: int, estado: str):
        self.conn.execute(
            "UPDATE programaciones SET estado = ? WHERE id = ?", (estado, prog_id))
        self.conn.commit()

    def cancelar_pendientes(self, telegram_id: int) -> int:
        cur = self.conn.execute(
            "UPDATE programaciones SET estado = 'cancelada' "
            "WHERE telegram_id = ? AND estado = 'pendiente'",
            (telegram_id,),
        )
        self.conn.commit()
        return cur.rowcount

    def cerrar(self):
        self.conn.close()
