"""Diálogos: crear/editar una regla y mostrar el análisis de un enlace."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QSpinBox, QVBoxLayout)

from .. import reglas
from ..modelos import ErrorGestor

SIN_CAMBIO = ""
MODOS = [("(sin cambio)", SIN_CAMBIO), ("Video", "video"), ("Solo audio", "audio"),
         ("Solo subtítulos", "subtitulos"), ("Solo portada", "portada")]
FORMATOS_AUDIO = [("(sin cambio)", SIN_CAMBIO), ("Pista original", "original"), ("MP3", "mp3"), ("M4A", "m4a"),
                  ("FLAC", "flac"), ("OGG", "ogg"), ("OPUS", "opus"), ("WAV", "wav")]
ALTURAS = [("(sin cambio)", SIN_CAMBIO), ("Mejor", "mejor"), ("1080p", "1080"), ("720p", "720"), ("480p", "480")]
TRI = [("(sin cambio)", SIN_CAMBIO), ("Sí", "si"), ("No", "no")]


def regla_desde_valores(v: dict) -> dict:
    """Convierte los valores del formulario en una regla validada (función pura, se prueba sin ventanas)."""
    cond = {k: v[k].strip() for k in ("dominio", "url_contiene", "sitio") if v.get(k, "").strip()}
    acc: dict = {}
    if v.get("modo"): acc["modo"] = v["modo"]
    if v.get("formato_audio"): acc["formato_audio"] = v["formato_audio"]
    if v.get("altura"): acc["altura_max"] = None if v["altura"] == "mejor" else int(v["altura"])
    if v.get("subtitulos", "").strip():
        acc["subtitulos"] = [s.strip() for s in v["subtitulos"].split(",") if s.strip()]
    if v.get("portada"): acc["portada"] = v["portada"] == "si"
    if v.get("excluir"): acc["excluir"] = True
    if v.get("subcarpeta", "").strip(): acc["subcarpeta"] = v["subcarpeta"].strip()
    regla = {"nombre": v.get("nombre", "").strip(), "prioridad": int(v.get("prioridad", 0)),
             "activa": v.get("activa", True), "condicion": cond, "accion": acc}
    if v.get("id"): regla["id"] = v["id"]
    reglas.validar_regla(regla)
    return regla


def _combo(opciones, actual=SIN_CAMBIO):
    c = QComboBox()
    for texto, dato in opciones:
        c.addItem(texto, dato)
    i = c.findData(actual)
    c.setCurrentIndex(max(i, 0))
    return c


class ReglaDialog(QDialog):
    def __init__(self, parent=None, regla: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Regla" if regla else "Nueva regla")
        self.resultado: dict | None = None
        self._id = regla.get("id") if regla else None
        r, c, a = regla or {}, (regla or {}).get("condicion", {}), (regla or {}).get("accion", {})
        f = QFormLayout()
        self.nombre = QLineEdit(r.get("nombre", ""))
        self.prioridad = QSpinBox(); self.prioridad.setRange(-100, 100); self.prioridad.setValue(r.get("prioridad", 0))
        self.prioridad.setToolTip("Si dos reglas cambian lo mismo, gana la de mayor prioridad.")
        self.dominio = QLineEdit(c.get("dominio", "")); self.dominio.setPlaceholderText("youtube.com (incluye subdominios)")
        self.url_contiene = QLineEdit(c.get("url_contiene", "")); self.url_contiene.setPlaceholderText("/curso/")
        self.sitio = QLineEdit(c.get("sitio", "")); self.sitio.setPlaceholderText("Youtube")
        self.modo = _combo(MODOS, a.get("modo", SIN_CAMBIO))
        self.formato_audio = _combo(FORMATOS_AUDIO, a.get("formato_audio", SIN_CAMBIO))
        alt = SIN_CAMBIO if "altura_max" not in a else ("mejor" if a["altura_max"] is None else str(a["altura_max"]))
        self.altura = _combo(ALTURAS, alt)
        self.subtitulos = QLineEdit(",".join(a.get("subtitulos", []))); self.subtitulos.setPlaceholderText("es,en")
        self.portada = _combo(TRI, SIN_CAMBIO if "portada" not in a else ("si" if a["portada"] else "no"))
        self.subcarpeta = QLineEdit(a.get("subcarpeta") or "")
        self.excluir = QCheckBox("No descargar nada de lo que coincida"); self.excluir.setChecked(bool(a.get("excluir")))
        self.activa = QCheckBox("Regla activa"); self.activa.setChecked(r.get("activa", True))
        for etiqueta, w in [("Nombre", self.nombre), ("Prioridad", self.prioridad),
                            ("Si el dominio es", self.dominio), ("Y la URL contiene", self.url_contiene),
                            ("Y el sitio es", self.sitio), ("Entonces: qué descargar", self.modo),
                            ("Formato de audio", self.formato_audio), ("Calidad máxima", self.altura),
                            ("Idiomas de subtítulos", self.subtitulos), ("Portada", self.portada),
                            ("Guardar en subcarpeta", self.subcarpeta), ("", self.excluir), ("", self.activa)]:
            f.addRow(etiqueta, w)
        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.accepted.connect(self._guardar); botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(f); lay.addWidget(botones)

    def _guardar(self) -> None:
        try:
            self.resultado = regla_desde_valores({
                "id": self._id, "nombre": self.nombre.text(), "prioridad": self.prioridad.value(),
                "dominio": self.dominio.text(), "url_contiene": self.url_contiene.text(), "sitio": self.sitio.text(),
                "modo": self.modo.currentData(), "formato_audio": self.formato_audio.currentData(),
                "altura": self.altura.currentData(), "subtitulos": self.subtitulos.text(),
                "portada": self.portada.currentData(), "excluir": self.excluir.isChecked(),
                "subcarpeta": self.subcarpeta.text(), "activa": self.activa.isChecked()})
        except (ErrorGestor, ValueError) as e:
            QMessageBox.warning(self, "Regla no válida", getattr(e, "mensaje", str(e)))
            return
        self.accept()


def texto_error(e: ErrorGestor) -> str:
    partes = [e.mensaje]
    if e.causa: partes.append(f"Causa: {e.causa}")
    if e.solucion: partes.append(f"Qué hacer: {e.solucion}")
    return "\n".join(partes)


class AnalisisDialog(QDialog):
    """Muestra qué ofrece un enlace y la compatibilidad (DRM)."""

    def __init__(self, parent, info, diag):
        super().__init__(parent)
        self.setWindowTitle("Análisis del enlace")
        self.resize(520, 380)
        alturas = sorted({f.altura for f in info.formatos if f.altura}, reverse=True)
        subs = [k + (" (auto)" if auto else "") for k, auto in info.subtitulos.items()]
        txt = [f"Título: {info.titulo}", f"Sitio: {info.sitio}", f"Autor: {info.autor or '-'}",
               f"Duración: {int(info.duracion_seg)} s" if info.duracion_seg else "Duración: -",
               f"Calidades: {', '.join(f'{a}p' for a in alturas) or 'no informadas'}",
               f"Formatos disponibles: {len(info.formatos)}", f"Subtítulos: {', '.join(subs) or 'ninguno'}", "",
               f"Compatibilidad: {diag.nivel.value.replace('_', ' ')} ({diag.confianza.value})", diag.motivo]
        txt += [f"Alternativa: {a}" for a in diag.alternativas]
        caja = QPlainTextEdit("\n".join(txt)); caja.setReadOnly(True)
        botones = QDialogButtonBox(QDialogButtonBox.Close); botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addWidget(QLabel("Esto es lo que ofrece el enlace:")); lay.addWidget(caja)
        lay.addWidget(botones)
