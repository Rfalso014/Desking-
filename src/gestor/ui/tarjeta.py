"""Tarjeta que representa una descarga, y cargador de miniaturas."""
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..modelos import EstadoTarea, Tarea
from .formatos import formato_duracion, formato_eta, formato_velocidad

ETIQUETA = {"detectado": "Detectado", "analizando": "Analizando", "pendiente": "En espera",
            "descargando": "Descargando", "procesando": "Procesando", "completado": "Completado",
            "cancelado": "Cancelado", "error": "Error"}
GLIFO_MODO = {"video": "▶", "audio": "♪", "subtitulos": "CC", "portada": "▣"}
# estado -> acciones que se ofrecen: (texto del botón, acción, estilo)
ACCIONES = {
    "detectado": [("Descargar", "iniciar_detectada", "primary"), ("Eliminar", "eliminar", "peligro")],
    "analizando": [("Cancelar", "cancelar", "")], "pendiente": [("Cancelar", "cancelar", "")],
    "descargando": [("Cancelar", "cancelar", "")], "procesando": [("Cancelar", "cancelar", "")],
    "completado": [("Abrir carpeta", "abrir_carpeta", ""), ("Eliminar", "eliminar", "peligro")],
    "cancelado": [("Reintentar", "reintentar", "primary"), ("Eliminar", "eliminar", "peligro")],
    "error": [("Reintentar", "reintentar", "primary"), ("Eliminar", "eliminar", "peligro")],
}
MAX_BYTES_MINIATURA = 3 * 1024 * 1024


class Miniaturas(QObject):
    """Descarga y guarda en memoria las miniaturas (solo http/https y de tamaño razonable)."""
    lista = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._red = QNetworkAccessManager(self)
        self._cache: dict[str, QPixmap] = {}
        self._en_curso: set[str] = set()

    def obtener(self, url: str | None) -> QPixmap | None:
        if not url or not url.lower().startswith(("http://", "https://")):
            return None
        if url in self._cache:
            return self._cache[url]
        if url not in self._en_curso and len(self._en_curso) < 12:
            self._en_curso.add(url)
            req = QNetworkRequest(QUrl(url))
            req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
            req.setTransferTimeout(10000)
            r = self._red.get(req)
            r.finished.connect(lambda r=r, u=url: self._terminado(r, u))
        return None

    def _terminado(self, r: QNetworkReply, url: str) -> None:
        self._en_curso.discard(url)
        datos = r.readAll().data() if r.error() == QNetworkReply.NoError else b""
        r.deleteLater()
        pix = QPixmap()
        if datos and len(datos) <= MAX_BYTES_MINIATURA and pix.loadFromData(datos):
            self._cache[url] = pix.scaled(224, 128, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self.lista.emit(url)


def _propiedad(w: QWidget, nombre: str, valor) -> None:
    w.setProperty(nombre, valor)
    w.style().unpolish(w)
    w.style().polish(w)


class TarjetaTarea(QFrame):
    accion = Signal(str, str)      # (acción, id de tarea)

    def __init__(self, tarea_id: str):
        super().__init__()
        self.tarea_id = tarea_id
        self.setObjectName("tarjeta")
        self._botones: list[QPushButton] = []
        self._detalle_visible = False

        self.miniatura = QLabel("▶")
        self.miniatura.setObjectName("miniatura")
        self.miniatura.setFixedSize(112, 64)
        self.miniatura.setAlignment(Qt.AlignCenter)
        self.titulo = QLabel(); self.titulo.setObjectName("tituloTarjeta"); self.titulo.setWordWrap(True)
        self.titulo.setTextFormat(Qt.PlainText)
        self.chip = QLabel(); self.chip.setProperty("chip", True)
        self.meta = QLabel(); self.meta.setObjectName("detalle"); self.meta.setTextFormat(Qt.PlainText)
        self.barra = QProgressBar(); self.barra.setRange(0, 1000); self.barra.setTextVisible(False)
        self.progreso = QLabel(); self.progreso.setObjectName("detalle")
        self.error = QLabel(); self.error.setObjectName("errorTexto"); self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        self.error.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.mas = QPushButton("Ver detalles técnicos"); self.mas.setProperty("enlace", True)
        self.mas.clicked.connect(self._alternar_detalle)
        self.tecnico = QLabel(); self.tecnico.setObjectName("detalle"); self.tecnico.setWordWrap(True)
        self.tecnico.setTextFormat(Qt.PlainText); self.tecnico.setTextInteractionFlags(Qt.TextSelectableByMouse)

        fila_titulo = QHBoxLayout(); fila_titulo.addWidget(self.titulo, 1); fila_titulo.addWidget(self.chip, 0, Qt.AlignTop)
        centro = QVBoxLayout(); centro.setSpacing(4)
        centro.addLayout(fila_titulo)
        for w in (self.meta, self.barra, self.progreso, self.error):
            centro.addWidget(w)
        centro.addWidget(self.mas, 0, Qt.AlignLeft)      # el enlace no debe estirarse a todo el ancho
        centro.addWidget(self.tecnico)
        self.columna_botones = QVBoxLayout(); self.columna_botones.setSpacing(6); self.columna_botones.addStretch()

        lay = QHBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(14)
        lay.addWidget(self.miniatura, 0, Qt.AlignTop); lay.addLayout(centro, 1); lay.addLayout(self.columna_botones)

    def _alternar_detalle(self) -> None:
        self._detalle_visible = not self._detalle_visible
        self.tecnico.setVisible(self._detalle_visible)
        self.mas.setText("Ocultar detalles técnicos" if self._detalle_visible else "Ver detalles técnicos")

    def _poner_botones(self, estado: str) -> None:
        for b in self._botones:
            self.columna_botones.removeWidget(b); b.deleteLater()
        self._botones.clear()
        for i, (texto, accion, estilo) in enumerate(ACCIONES[estado]):
            b = QPushButton(texto)
            if estilo:
                b.setProperty(estilo, True)
            b.clicked.connect(lambda _=False, a=accion: self.accion.emit(a, self.tarea_id))
            self.columna_botones.insertWidget(i, b)
            self._botones.append(b)
        self._estado_botones = estado

    def actualizar(self, t: Tarea, pixmap: QPixmap | None = None) -> None:
        e = t.estado.value
        if getattr(self, "_estado_botones", None) != e:
            self._poner_botones(e)
        self.titulo.setText(t.titulo or t.url)
        self.chip.setText(ETIQUETA[e]); _propiedad(self.chip, "estado", e)
        partes = [t.sitio or "", formato_duracion(t.duracion)]
        self.meta.setText("  ·  ".join(p for p in partes if p) or t.url)
        if pixmap is not None:
            self.miniatura.setPixmap(pixmap.scaled(112, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        elif not self.miniatura.pixmap() or self.miniatura.pixmap().isNull():
            self.miniatura.setText(GLIFO_MODO.get((t.opciones or {}).get("modo", "video"), "▶"))

        activa = t.estado in (EstadoTarea.DESCARGANDO, EstadoTarea.PROCESANDO, EstadoTarea.ANALIZANDO)
        self.barra.setVisible(activa or t.estado == EstadoTarea.COMPLETADO)
        self.barra.setValue(1000 if t.estado == EstadoTarea.COMPLETADO else int((t.progreso or 0) * 10))
        if t.estado == EstadoTarea.DESCARGANDO:
            texto = [f"{t.progreso:.0f} %" if t.progreso is not None else "Iniciando…", formato_velocidad(t.velocidad_bps)]
            if t.eta_seg is not None:
                texto.append(f"quedan {formato_eta(t.eta_seg)}")
            self.progreso.setText("  ·  ".join(x for x in texto if x))
        else:
            self.progreso.setText({
                "analizando": "Leyendo los datos del enlace…", "pendiente": "En espera de su turno",
                "procesando": "Uniendo y convirtiendo archivos…", "completado": t.carpeta_final or "",
                "cancelado": " ".join(t.notas) or "Cancelada",
                "detectado": "Esperando tu autorización: pulsa «Descargar»." + ("  " + " ".join(t.notas) if t.notas else ""),
                "error": ""}[e])
        self.progreso.setVisible(bool(self.progreso.text()))

        err = t.error
        self.error.setVisible(bool(err)); self.mas.setVisible(bool(err)); self.tecnico.setVisible(bool(err) and self._detalle_visible)
        if err:
            lineas = [err["mensaje"], f"Causa: {err.get('causa') or 'no se pudo determinar'}"]
            if err.get("solucion"):
                lineas.append(f"Qué hacer: {err['solucion']}")
            self.error.setText("\n".join(lineas))
            self.tecnico.setText(err.get("detalle") or "Sin detalles técnicos.")
