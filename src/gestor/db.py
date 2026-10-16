"""Persistencia en SQLite: tareas (historial), reglas, preferencias y errores.

Notas:
  - Una sola conexión compartida protegida con un candado (RLock): sencillo y
    suficiente para una app de escritorio.
  - SIEMPRE consultas con parámetros (?): nunca se arma SQL concatenando texto.
  - No se guardan contraseñas, cookies ni tokens (no hay columnas para ello).
"""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import Preferencias
from .modelos import ErrorGestor, EstadoTarea, Tarea

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS tareas (
    id TEXT PRIMARY KEY, url TEXT NOT NULL, origen TEXT, titulo TEXT, sitio TEXT,
    estado TEXT NOT NULL, progreso REAL, velocidad_bps REAL, eta_seg REAL,
    creado TEXT NOT NULL, actualizado TEXT NOT NULL,
    opciones TEXT NOT NULL DEFAULT '{}', destino_manual TEXT, carpeta_final TEXT,
    archivos TEXT NOT NULL DEFAULT '[]', error TEXT, intentos INTEGER NOT NULL DEFAULT 0,
    notas TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS ix_tareas_estado ON tareas(estado);
CREATE TABLE IF NOT EXISTS reglas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, activa INTEGER NOT NULL DEFAULT 1,
    prioridad INTEGER NOT NULL DEFAULT 0, condicion TEXT NOT NULL, accion TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferencias (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS errores (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tarea_id TEXT, fecha TEXT NOT NULL,
    codigo TEXT NOT NULL, mensaje TEXT NOT NULL, detalle TEXT
);
"""

_COLUMNAS_JSON = ("opciones", "archivos", "error", "notas")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BaseDatos:
    def __init__(self, ruta: Path | str = ":memory:"):
        self._con = sqlite3.connect(str(ruta), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.executescript(_ESQUEMA)

    def cerrar(self) -> None:
        with self._lock:
            self._con.close()

    # --- tareas ---------------------------------------------------------------
    @staticmethod
    def _a_tarea(f: sqlite3.Row) -> Tarea:
        d = dict(f)
        for c in _COLUMNAS_JSON:
            d[c] = json.loads(d[c]) if d[c] else None
        d["estado"] = EstadoTarea(d["estado"])
        d["notas"] = d["notas"] or []
        d["archivos"] = d["archivos"] or []
        d["opciones"] = d["opciones"] or {}
        return Tarea(**d)

    def crear_tarea(self, url: str, *, origen: str | None = None, opciones: dict | None = None,
                    destino_manual: str | None = None,
                    estado: EstadoTarea = EstadoTarea.PENDIENTE) -> Tarea:
        t = Tarea(id=uuid.uuid4().hex[:12], url=url, estado=estado, origen=origen,
                  opciones=opciones or {}, destino_manual=destino_manual,
                  creado=_ahora(), actualizado=_ahora())
        self.guardar_tarea(t)
        return t

    def guardar_tarea(self, t: Tarea) -> None:
        t.actualizado = _ahora()
        d = t.a_dict()
        for c in _COLUMNAS_JSON:
            d[c] = json.dumps(d[c], ensure_ascii=False) if d[c] is not None else None
        cols = ", ".join(d)
        marcas = ", ".join("?" for _ in d)
        with self._lock:
            self._con.execute(f"INSERT OR REPLACE INTO tareas ({cols}) VALUES ({marcas})", list(d.values()))
            self._con.commit()

    def obtener_tarea(self, id_: str) -> Tarea | None:
        with self._lock:
            f = self._con.execute("SELECT * FROM tareas WHERE id = ?", (id_,)).fetchone()
        return self._a_tarea(f) if f else None

    def listar_tareas(self, *, estados: list[EstadoTarea] | None = None, texto: str | None = None,
                      limite: int = 500) -> list[Tarea]:
        sql, args = "SELECT * FROM tareas WHERE 1=1", []
        if estados:
            sql += f" AND estado IN ({', '.join('?' for _ in estados)})"
            args += [e.value for e in estados]
        if texto:
            like = "%" + texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql += " AND (titulo LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\' OR sitio LIKE ? ESCAPE '\\')"
            args += [like, like, like]
        sql += " ORDER BY creado DESC, rowid DESC LIMIT ?"
        args.append(max(1, min(limite, 5000)))
        with self._lock:
            return [self._a_tarea(f) for f in self._con.execute(sql, args).fetchall()]

    def eliminar_tarea(self, id_: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM tareas WHERE id = ?", (id_,))
            self._con.commit()

    def limpiar_historial(self, *, solo_finalizadas: bool = True) -> int:
        with self._lock:
            if solo_finalizadas:
                cur = self._con.execute("DELETE FROM tareas WHERE estado IN ('completado','cancelado','error')")
            else:
                cur = self._con.execute("DELETE FROM tareas")
            self._con.commit()
            return cur.rowcount

    # --- errores --------------------------------------------------------------
    def registrar_error(self, tarea_id: str | None, e: ErrorGestor) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO errores (tarea_id, fecha, codigo, mensaje, detalle) VALUES (?,?,?,?,?)",
                (tarea_id, _ahora(), e.codigo.value, e.mensaje, e.detalle_tecnico))
            self._con.commit()

    def listar_errores(self, limite: int = 100) -> list[dict]:
        with self._lock:
            return [dict(f) for f in self._con.execute(
                "SELECT * FROM errores ORDER BY id DESC LIMIT ?", (limite,)).fetchall()]

    # --- reglas ---------------------------------------------------------------
    def guardar_regla(self, regla: dict) -> int:
        """Inserta (sin 'id') o actualiza (con 'id'). Devuelve el id."""
        valores = (regla["nombre"], 1 if regla.get("activa", True) else 0, int(regla.get("prioridad", 0)),
                   json.dumps(regla.get("condicion", {}), ensure_ascii=False),
                   json.dumps(regla.get("accion", {}), ensure_ascii=False))
        with self._lock:
            if regla.get("id"):
                self._con.execute("UPDATE reglas SET nombre=?, activa=?, prioridad=?, condicion=?, accion=? WHERE id=?",
                                  (*valores, regla["id"]))
                id_ = regla["id"]
            else:
                id_ = self._con.execute(
                    "INSERT INTO reglas (nombre, activa, prioridad, condicion, accion) VALUES (?,?,?,?,?)",
                    valores).lastrowid
            self._con.commit()
        return id_

    def listar_reglas(self, *, solo_activas: bool = False) -> list[dict]:
        sql = "SELECT * FROM reglas" + (" WHERE activa = 1" if solo_activas else "") + " ORDER BY prioridad DESC, id"
        with self._lock:
            filas = self._con.execute(sql).fetchall()
        return [{"id": f["id"], "nombre": f["nombre"], "activa": bool(f["activa"]), "prioridad": f["prioridad"],
                 "condicion": json.loads(f["condicion"]), "accion": json.loads(f["accion"])} for f in filas]

    def activar_regla(self, id_: int, activa: bool) -> None:
        with self._lock:
            self._con.execute("UPDATE reglas SET activa=? WHERE id=?", (1 if activa else 0, id_))
            self._con.commit()

    def eliminar_regla(self, id_: int) -> None:
        with self._lock:
            self._con.execute("DELETE FROM reglas WHERE id=?", (id_,))
            self._con.commit()

    # --- preferencias ----------------------------------------------------------
    def cargar_preferencias(self) -> Preferencias:
        p = Preferencias()
        with self._lock:
            filas = self._con.execute("SELECT clave, valor FROM preferencias").fetchall()
        for f in filas:
            if not hasattr(p, f["clave"]):
                continue                    # clave desconocida (versión distinta): se ignora
            v = json.loads(f["valor"])
            actual = getattr(p, f["clave"])
            if isinstance(actual, Path):
                v = Path(v)
            elif isinstance(actual, tuple):
                v = tuple(v)
            setattr(p, f["clave"], v)
        return p

    def guardar_preferencias(self, p: Preferencias) -> None:
        with self._lock:
            for clave in p.__dataclass_fields__:
                v = getattr(p, clave)
                v = str(v) if isinstance(v, Path) else list(v) if isinstance(v, tuple) else v
                self._con.execute("INSERT OR REPLACE INTO preferencias (clave, valor) VALUES (?,?)",
                                  (clave, json.dumps(v)))
            self._con.commit()
