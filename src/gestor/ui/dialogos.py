"""Diálogos: crear/editar una regla y mostrar el análisis de un enlace."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import reglas
from ..config import Preferencias
from ..elementos import opciones_desde_elementos, parsear_idiomas
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
        txt = ([f"Es una lista de reproducción con {len(info.entradas)} videos.",
                "Al descargarla, cada video se agrega a la cola y se guarda en una carpeta con el nombre de la lista.", ""]
               if info.es_lista else [])
        txt += [f"Título: {info.titulo}", f"Sitio: {info.sitio}", f"Autor: {info.autor or '-'}",
               f"Duración: {int(info.duracion_seg)} s" if info.duracion_seg else "Duración: -",
               f"Calidades: {', '.join(f'{a}p' for a in alturas) or 'no informadas'}",
               f"Formatos disponibles: {len(info.formatos)}", f"Subtítulos: {', '.join(subs) or 'ninguno'}", "",
               f"Compatibilidad: {diag.nivel.value.replace('_', ' ')} ({diag.confianza.value})", diag.motivo]
        txt += [f"Alternativa: {a}" for a in diag.alternativas]
        if info.es_lista:
            txt += ["", "Videos de la lista:", *(f"  {i}. {t}" for i, (_u, t) in enumerate(info.entradas[:50], 1))]
            if len(info.entradas) > 50:
                txt.append(f"  … y {len(info.entradas) - 50} más")
        caja = QPlainTextEdit("\n".join(txt)); caja.setReadOnly(True)
        botones = QDialogButtonBox(QDialogButtonBox.Close); botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addWidget(QLabel("Esto es lo que ofrece el enlace:")); lay.addWidget(caja)
        lay.addWidget(botones)


CALIDADES_SELECTOR = [("Según mi configuración", ""), ("La mejor", "mejor"), ("1080p", "1080"), ("720p", "720"), ("480p", "480")]
AUDIOS_SELECTOR = [("MP3", "mp3"), ("M4A", "m4a"), ("FLAC", "flac"), ("OGG", "ogg"), ("OPUS", "opus"), ("WAV", "wav"), ("Pista original", "original")]


class SelectorDestino(QWidget):
    """«Dónde guardar»: nombre de una carpeta (dentro quedan Videos, Musica, Subtitulos…) y el lugar donde crearla."""

    def __init__(self, prefs: Preferencias | None = None, parent=None):
        super().__init__(parent)
        self._defecto = (prefs or Preferencias()).carpeta_raiz
        self.carpeta = QLineEdit(); self.carpeta.setMaximumWidth(220); self.carpeta.setClearButtonEnabled(True)
        self.carpeta.setPlaceholderText("Nombre de carpeta (opcional)")
        self.carpeta.setToolTip("Si escribes un nombre, se crea esa carpeta y dentro se separan Videos, Musica, Subtitulos y Portadas.")
        self.lugar = QLineEdit(); self.lugar.setReadOnly(True)
        self.lugar.setPlaceholderText(f"Predeterminado: {self._defecto}")
        self.lugar.setToolTip("Dónde se crea la carpeta. Vacío = la carpeta de descargas de la Configuración.")
        elegir = QPushButton("Elegir lugar…"); elegir.setCursor(Qt.PointingHandCursor); elegir.clicked.connect(self._elegir)
        quitar = QPushButton("Predeterminado"); quitar.setCursor(Qt.PointingHandCursor); quitar.clicked.connect(lambda: self.lugar.clear())
        fila = QHBoxLayout(); fila.setContentsMargins(0, 0, 0, 0); fila.setSpacing(8)
        l = QLabel("Guardar en"); l.setProperty("tenue", True)
        for w in (l, self.carpeta, self.lugar, elegir, quitar):
            fila.addWidget(w)
        fila.setStretch(2, 1)
        self.setLayout(fila)

    def _elegir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "¿Dónde guardar?", self.lugar.text() or str(self._defecto))
        if d:
            self.lugar.setText(d)

    def aplicar(self, lista: list[dict]) -> list[dict]:
        """Añade la carpeta y el lugar elegidos a cada descarga (si no eligió nada, no cambia nada)."""
        nombre, lugar = self.carpeta.text().strip(), self.lugar.text().strip()
        extra = {**({"subcarpeta": nombre} if nombre else {}), **({"destino": lugar} if lugar else {})}
        return [{**o, **extra} for o in lista]


class SelectorElementos(QWidget):
    """Casillas «qué quiero descargar»: video, audio, subtítulos (con idiomas) y portada, más calidad y formato de audio."""

    def __init__(self, prefs: Preferencias | None = None, inicial: dict | None = None, parent=None):
        super().__init__(parent)
        p = prefs or Preferencias()
        o = inicial or {}
        modo = o.get("modo")
        self.video = QCheckBox("Video"); self.audio = QCheckBox("Audio")
        self.subs = QCheckBox("Subtítulos"); self.portada = QCheckBox("Portada")
        if modo:           # se reconstruye lo que ya se había elegido (p. ej. una tarea detectada desde la extensión)
            self.video.setChecked(modo == "video"); self.audio.setChecked(modo == "audio")
            self.subs.setChecked(bool(o.get("subtitulos")) or modo == "subtitulos")
            self.portada.setChecked(bool(o.get("portada", p.descargar_portada)) or modo == "portada")
            idiomas = o.get("subtitulos") or list(p.idiomas_subtitulos)
        else:
            self.video.setChecked(True); self.subs.setChecked(p.descargar_subtitulos); self.portada.setChecked(p.descargar_portada)
            idiomas = list(p.idiomas_subtitulos)
        self.idiomas = QLineEdit(",".join(idiomas)); self.idiomas.setPlaceholderText("es,en"); self.idiomas.setMaximumWidth(120)
        self.idiomas.setToolTip("Códigos de idioma separados por comas")
        self.calidad = QComboBox(); [self.calidad.addItem(t, d) for t, d in CALIDADES_SELECTOR]
        alt = o.get("altura_max", "__no__")
        self.calidad.setCurrentIndex(max(0, self.calidad.findData("" if alt == "__no__" else "mejor" if alt is None else str(alt))))
        self.formato_audio = QComboBox(); [self.formato_audio.addItem(t, d) for t, d in AUDIOS_SELECTOR]
        self.formato_audio.setCurrentIndex(max(0, self.formato_audio.findData(o.get("formato_audio", p.formato_audio))))

        fila1 = QHBoxLayout(); fila1.setSpacing(16)
        for c in (self.video, self.audio, self.subs, self.portada):
            fila1.addWidget(c)
        fila1.addStretch()
        fila2 = QHBoxLayout(); fila2.setSpacing(8)
        self._et = {}
        for clave, texto, w in (("calidad", "Calidad", self.calidad), ("audio", "Formato de audio", self.formato_audio), ("idiomas", "Idiomas", self.idiomas)):
            l = QLabel(texto); l.setProperty("tenue", True); self._et[clave] = l; fila2.addWidget(l); fila2.addWidget(w)
        fila2.addStretch()
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8); lay.addLayout(fila1); lay.addLayout(fila2)
        for c in (self.video, self.audio, self.subs):
            c.toggled.connect(self._actualizar)
        self._actualizar()

    def _actualizar(self) -> None:
        """Solo se habilita lo que tiene sentido para lo marcado."""
        self.calidad.setEnabled(self.video.isChecked())
        self.formato_audio.setEnabled(self.audio.isChecked())
        self.idiomas.setEnabled(self.subs.isChecked())

    def opciones(self) -> list[dict]:
        """Lista de opciones (una por descarga). Lanza ErrorGestor si no hay nada marcado o un idioma es raro."""
        return opciones_desde_elementos(
            video=self.video.isChecked(), audio=self.audio.isChecked(), subtitulos=self.subs.isChecked(),
            idiomas=parsear_idiomas(self.idiomas.text()), portada=self.portada.isChecked(),
            altura=self.calidad.currentData() or None, formato_audio=self.formato_audio.currentData() if self.audio.isChecked() else None)


class DialogoElementos(QDialog):
    """Pregunta «¿qué quieres descargar?» antes de autorizar una descarga detectada."""

    def __init__(self, parent, titulo: str, prefs: Preferencias, inicial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("¿Qué quieres descargar?")
        self.resultado: list[dict] | None = None
        self.selector = SelectorElementos(prefs, inicial)
        self.destino = SelectorDestino(prefs)
        t = QLabel(titulo); t.setWordWrap(True); t.setProperty("seccion", True)
        botones = QDialogButtonBox(); ok = botones.addButton("Descargar", QDialogButtonBox.AcceptRole); ok.setProperty("primary", True)
        botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
        botones.accepted.connect(self._aceptar); botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.setSpacing(12); lay.addWidget(t); lay.addWidget(self.selector); lay.addWidget(self.destino); lay.addWidget(botones)
        self.setMinimumWidth(760)

    def _aceptar(self) -> None:
        try:
            self.resultado = self.destino.aplicar(self.selector.opciones())
        except ErrorGestor as e:
            QMessageBox.warning(self, "Revisa lo que marcaste", texto_error(e)); return
        self.accept()
