"""Ventana principal: Descargas, Historial, Reglas y Configuración."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import reglas
from ..cola import GestorCola
from ..config import localizar_ffmpeg
from ..modelos import ESTADOS_ACTIVOS, ErrorGestor, EstadoTarea, Tarea
from ..nativo import instalador
from ..organizador import ORGANIZACIONES, POLITICAS
from .dialogos import (AnalisisDialog, ReglaDialog, ALTURAS, FORMATOS_AUDIO, MODOS, SIN_CAMBIO, texto_error)

ETIQUETA = {"detectado": "Detectado", "analizando": "Analizando", "pendiente": "Pendiente",
            "descargando": "Descargando", "procesando": "Procesando", "completado": "Completado",
            "cancelado": "Cancelado", "error": "Error"}
COLOR = {"completado": "#188038", "error": "#b3261e", "cancelado": "#80868b"}


class Puente(QObject):
    """Lleva avisos desde los hilos de trabajo al hilo de la interfaz (Qt lo exige)."""
    cambio = Signal(dict)
    analisis = Signal(object, object)   # (resultado | None, error | None)


def _tabla(columnas: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    return t


def _celda(texto: str, color: str | None = None) -> QTableWidgetItem:
    i = QTableWidgetItem(texto or "")
    if color:
        i.setForeground(QColor(color))
    return i


class VentanaPrincipal(QMainWindow):
    def __init__(self, cola: GestorCola):
        super().__init__()
        self.cola, self.db = cola, cola.db
        self.setWindowTitle("Gestor de Descargas")
        self.resize(1000, 640)
        self.puente = Puente()
        self.puente.cambio.connect(self._programar_refresco)
        self.puente.analisis.connect(self._mostrar_analisis)
        cola.suscribir(self.puente.cambio.emit)

        tabs = QTabWidget()
        tabs.addTab(self._pestana_descargas(), "Descargas")
        tabs.addTab(self._pestana_historial(), "Historial")
        tabs.addTab(self._pestana_reglas(), "Reglas")
        tabs.addTab(self._pestana_config(), "Configuración")
        self.setCentralWidget(tabs)
        self.statusBar().showMessage("Listo")

        self._temporizador = QTimer(self, singleShot=True, interval=250)   # agrupa avisos seguidos
        self._temporizador.timeout.connect(self.refrescar)
        self.refrescar()
        self._cargar_reglas()

    # --- Descargas -----------------------------------------------------------------
    def _pestana_descargas(self) -> QWidget:
        w, lay = QWidget(), QVBoxLayout()
        w.setLayout(lay)
        fila = QHBoxLayout()
        self.url = QLineEdit(); self.url.setPlaceholderText("Pega aquí el enlace de un video, audio, imagen o página…")
        self.url.returnPressed.connect(self._anadir)
        self.modo = QComboBox()
        for t, d in MODOS[1:]:
            self.modo.addItem(t, d)
        self.altura = QComboBox()
        for t, d in ALTURAS:
            self.altura.addItem(t if d else "Calidad: la de la regla", d)
        b_analizar, b_anadir = QPushButton("Analizar"), QPushButton("Añadir a la cola")
        b_analizar.clicked.connect(self._analizar); b_anadir.clicked.connect(self._anadir)
        for x in (self.url, self.modo, self.altura, b_analizar, b_anadir):
            fila.addWidget(x)
        fila.setStretch(0, 1)
        lay.addLayout(fila)

        self.tabla = _tabla(["Contenido", "Sitio", "Estado", "Progreso", "Destino"])
        self.tabla.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.tabla.itemSelectionChanged.connect(self._mostrar_detalle)
        lay.addWidget(self.tabla, 1)
        self.detalle = QPlainTextEdit(); self.detalle.setReadOnly(True); self.detalle.setMaximumHeight(110)
        self.detalle.setPlaceholderText("Selecciona una descarga para ver sus detalles y errores.")
        lay.addWidget(self.detalle)

        botones = QHBoxLayout()
        for texto, f in [("Cancelar", lambda: self._accion("cancelar")), ("Reintentar", lambda: self._accion("reintentar")),
                         ("Eliminar", lambda: self._accion("eliminar")), ("Abrir carpeta", self._abrir_carpeta)]:
            b = QPushButton(texto); b.clicked.connect(f); botones.addWidget(b)
        botones.addStretch()
        lay.addLayout(botones)
        return w

    def _opciones_formulario(self) -> dict:
        o = {"modo": self.modo.currentData()}
        if self.altura.currentData() == "mejor":
            o["altura_max"] = None
        elif self.altura.currentData():
            o["altura_max"] = int(self.altura.currentData())
        return o

    def _anadir(self) -> None:
        try:
            self.cola.encolar(self.url.text(), opciones=self._opciones_formulario())
            self.url.clear()
            self.statusBar().showMessage("Añadida a la cola", 3000)
        except ErrorGestor as e:
            QMessageBox.warning(self, "No se pudo añadir", texto_error(e))

    def _analizar(self) -> None:
        url = self.url.text()
        self.statusBar().showMessage("Analizando…")

        def trabajo():
            try:
                self.puente.analisis.emit(self.cola.analizar(url), None)
            except ErrorGestor as e:
                self.puente.analisis.emit(None, e)
        threading.Thread(target=trabajo, daemon=True).start()

    def _mostrar_analisis(self, resultado, error) -> None:
        self.statusBar().clearMessage()
        if error:
            QMessageBox.warning(self, "No se pudo analizar", texto_error(error))
        else:
            AnalisisDialog(self, resultado["info"], resultado["diagnostico"]).exec()

    def _tarea_seleccionada(self, tabla: QTableWidget) -> Tarea | None:
        filas = tabla.selectionModel().selectedRows()
        return self.db.obtener_tarea(tabla.item(filas[0].row(), 0).data(Qt.UserRole)) if filas else None

    def _accion(self, nombre: str, tabla: QTableWidget | None = None) -> None:
        t = self._tarea_seleccionada(tabla or self.tabla)
        if not t:
            return
        try:
            getattr(self.cola, nombre)(t.id)
        except ErrorGestor as e:
            QMessageBox.information(self, "No se puede", texto_error(e))
        self.refrescar()

    def _abrir_carpeta(self) -> None:
        t = self._tarea_seleccionada(self.tabla)
        if t and t.carpeta_final and Path(t.carpeta_final).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(t.carpeta_final))

    def _mostrar_detalle(self) -> None:
        t = self._tarea_seleccionada(self.tabla)
        if not t:
            self.detalle.clear(); return
        lineas = [f"URL: {t.url}", f"Estado: {ETIQUETA[t.estado.value]}"]
        lineas += t.notas
        if t.error:
            lineas += ["", t.error["mensaje"], f"Causa: {t.error.get('causa') or 'no se pudo determinar'}",
                       f"Qué hacer: {t.error.get('solucion') or '-'}", f"Detalles técnicos: {t.error.get('detalle') or '-'}"]
        self.detalle.setPlainText("\n".join(lineas))

    def _programar_refresco(self, _d: dict) -> None:
        if not self._temporizador.isActive():
            self._temporizador.start()

    def _llenar(self, tabla: QTableWidget, tareas: list[Tarea], progreso: bool) -> None:
        sel = self._tarea_seleccionada(tabla)
        tabla.setRowCount(len(tareas))
        for fila, t in enumerate(tareas):
            c0 = _celda(t.titulo or t.url); c0.setData(Qt.UserRole, t.id)
            tabla.setItem(fila, 0, c0)
            tabla.setItem(fila, 1, _celda(t.sitio or ""))
            tabla.setItem(fila, 2, _celda(ETIQUETA[t.estado.value], COLOR.get(t.estado.value)))
            if progreso:
                barra = QProgressBar(); barra.setRange(0, 100)
                barra.setValue(int(t.progreso or (100 if t.estado == EstadoTarea.COMPLETADO else 0)))
                tabla.setCellWidget(fila, 3, barra)
                tabla.setItem(fila, 4, _celda(t.carpeta_final or ""))
            else:
                tabla.setItem(fila, 3, _celda(t.creado[:16].replace("T", " ")))
            if sel and sel.id == t.id:
                tabla.selectRow(fila)

    def refrescar(self) -> None:
        self._llenar(self.tabla, self.cola.listar(limite=200), True)
        activas = sum(1 for t in self.cola.listar(estados=list(ESTADOS_ACTIVOS)))
        self.statusBar().showMessage(f"{activas} descarga(s) activa(s)")
        if hasattr(self, "tabla_hist"):
            self._refrescar_historial()

    # --- Historial ---------------------------------------------------------------------
    def _pestana_historial(self) -> QWidget:
        w, lay = QWidget(), QVBoxLayout()
        w.setLayout(lay)
        fila = QHBoxLayout()
        self.buscar = QLineEdit(); self.buscar.setPlaceholderText("Buscar por título, sitio o URL…")
        self.filtro = QComboBox(); self.filtro.addItem("Todos los estados", None)
        for e in EstadoTarea:
            self.filtro.addItem(ETIQUETA[e.value], e)
        self.buscar.textChanged.connect(self._refrescar_historial); self.filtro.currentIndexChanged.connect(self._refrescar_historial)
        fila.addWidget(self.buscar, 1); fila.addWidget(self.filtro)
        lay.addLayout(fila)
        self.tabla_hist = _tabla(["Contenido", "Sitio", "Estado", "Fecha"])
        lay.addWidget(self.tabla_hist, 1)
        botones = QHBoxLayout()
        for texto, f in [("Reintentar", lambda: self._accion("reintentar", self.tabla_hist)),
                         ("Eliminar registro", lambda: self._accion("eliminar", self.tabla_hist)),
                         ("Limpiar historial terminado", self._limpiar_historial)]:
            b = QPushButton(texto); b.clicked.connect(f); botones.addWidget(b)
        botones.addStretch()
        lay.addLayout(botones)
        return w

    def _refrescar_historial(self, *_) -> None:
        e = self.filtro.currentData()
        self._llenar(self.tabla_hist, self.db.listar_tareas(estados=[e] if e else None,
                                                            texto=self.buscar.text() or None, limite=500), False)

    def _limpiar_historial(self) -> None:
        if QMessageBox.question(self, "Limpiar historial", "¿Borrar del historial las descargas completadas, canceladas y con error?\n(No se borran los archivos descargados.)") == QMessageBox.Yes:
            self.db.limpiar_historial(); self.refrescar()

    # --- Reglas ---------------------------------------------------------------------------
    def _pestana_reglas(self) -> QWidget:
        w, lay = QWidget(), QVBoxLayout()
        w.setLayout(lay)
        lay.addWidget(QLabel("Las reglas cambian cómo se descarga un sitio concreto. Una elección hecha para una descarga "
                             "puntual siempre gana a las reglas, y las reglas ganan a la configuración general."))
        self.tabla_reglas = _tabla(["Nombre", "Prioridad", "Activa", "Condición", "Acción"])
        lay.addWidget(self.tabla_reglas, 1)
        botones = QHBoxLayout()
        for texto, f in [("Nueva", self._regla_nueva), ("Editar", self._regla_editar),
                         ("Activar/Desactivar", self._regla_alternar), ("Eliminar", self._regla_eliminar)]:
            b = QPushButton(texto); b.clicked.connect(f); botones.addWidget(b)
        botones.addStretch()
        lay.addLayout(botones)
        lay.addWidget(QLabel("¿Qué regla se aplicaría a este enlace?"))
        prueba = QHBoxLayout()
        self.url_prueba = QLineEdit(); self.url_prueba.setPlaceholderText("https://…")
        b = QPushButton("Probar"); b.clicked.connect(self._probar_regla)
        prueba.addWidget(self.url_prueba, 1); prueba.addWidget(b)
        lay.addLayout(prueba)
        self.resultado_prueba = QPlainTextEdit(); self.resultado_prueba.setReadOnly(True); self.resultado_prueba.setMaximumHeight(150)
        lay.addWidget(self.resultado_prueba)
        return w

    def _cargar_reglas(self) -> None:
        rs = self.db.listar_reglas()
        self.tabla_reglas.setRowCount(len(rs))
        for i, r in enumerate(rs):
            c0 = _celda(r["nombre"]); c0.setData(Qt.UserRole, r["id"])
            self.tabla_reglas.setItem(i, 0, c0)
            self.tabla_reglas.setItem(i, 1, _celda(str(r["prioridad"])))
            self.tabla_reglas.setItem(i, 2, _celda("Sí" if r["activa"] else "No"))
            self.tabla_reglas.setItem(i, 3, _celda(", ".join(f"{k}={v}" for k, v in r["condicion"].items())))
            self.tabla_reglas.setItem(i, 4, _celda(", ".join(f"{k}={v}" for k, v in r["accion"].items())))

    def _regla_seleccionada(self) -> dict | None:
        filas = self.tabla_reglas.selectionModel().selectedRows()
        if not filas:
            return None
        id_ = self.tabla_reglas.item(filas[0].row(), 0).data(Qt.UserRole)
        return next((r for r in self.db.listar_reglas() if r["id"] == id_), None)

    def _regla_nueva(self) -> None:
        d = ReglaDialog(self)
        if d.exec() and d.resultado:
            self.db.guardar_regla(d.resultado); self._cargar_reglas()

    def _regla_editar(self) -> None:
        r = self._regla_seleccionada()
        if r:
            d = ReglaDialog(self, r)
            if d.exec() and d.resultado:
                self.db.guardar_regla(d.resultado); self._cargar_reglas()

    def _regla_alternar(self) -> None:
        r = self._regla_seleccionada()
        if r:
            self.db.activar_regla(r["id"], not r["activa"]); self._cargar_reglas()

    def _regla_eliminar(self) -> None:
        r = self._regla_seleccionada()
        if r and QMessageBox.question(self, "Eliminar regla", f"¿Eliminar la regla «{r['nombre']}»?") == QMessageBox.Yes:
            self.db.eliminar_regla(r["id"]); self._cargar_reglas()

    def _probar_regla(self) -> None:
        try:
            res = reglas.resolver(self.url_prueba.text().strip(), None, self.db.listar_reglas(solo_activas=True),
                                  self.db.cargar_preferencias())
        except ErrorGestor as e:
            self.resultado_prueba.setPlainText(texto_error(e)); return
        enc = ["Reglas que coinciden: " + (", ".join(res.reglas_aplicadas) or "ninguna"), ""]
        self.resultado_prueba.setPlainText("\n".join(enc + res.texto()))

    # --- Configuración ----------------------------------------------------------------------
    def _pestana_config(self) -> QWidget:
        p = self.db.cargar_preferencias()
        w, f = QWidget(), QFormLayout()
        w.setLayout(f)
        self.c_raiz = QLineEdit(str(p.carpeta_raiz))
        b = QPushButton("Elegir…"); b.clicked.connect(self._elegir_raiz)
        fila = QHBoxLayout(); fila.addWidget(self.c_raiz, 1); fila.addWidget(b)
        f.addRow("Carpeta de descargas", fila)
        self.c_org = QComboBox()
        for k, t in [("tipo_y_contenido", "Por tipo y por contenido (Videos/Nombre/…)"), ("tipo", "Solo por tipo"),
                     ("contenido", "Solo por contenido"), ("manual", "Manual (la elijo yo cada vez)")]:
            self.c_org.addItem(t, k)
        self.c_org.setCurrentIndex(self.c_org.findData(p.organizacion))
        self.c_dup = QComboBox()
        for k, t in [("renombrar", "Renombrar (añadir número)"), ("omitir", "Omitir (conservar el existente)"),
                     ("reemplazar", "Reemplazar")]:
            self.c_dup.addItem(t, k)
        self.c_dup.setCurrentIndex(self.c_dup.findData(p.duplicados))
        self.c_cont = QComboBox(); [self.c_cont.addItem(t, d) for t, d in [("MP4", "mp4"), ("MKV", "mkv"), ("El mejor disponible", "mejor")]]
        self.c_cont.setCurrentIndex(self.c_cont.findData(p.contenedor_video))
        self.c_aud = QComboBox(); [self.c_aud.addItem(t, d) for t, d in FORMATOS_AUDIO[1:]]
        self.c_aud.setCurrentIndex(self.c_aud.findData(p.formato_audio))
        self.c_alt = QComboBox(); [self.c_alt.addItem(t, d) for t, d in [("Mejor", ""), ("1080p", "1080"), ("720p", "720"), ("480p", "480")]]
        self.c_alt.setCurrentIndex(self.c_alt.findData(str(p.altura_max) if p.altura_max else ""))
        self.c_idiomas = QLineEdit(",".join(p.idiomas_subtitulos))
        self.c_subs = QCheckBox("Descargar subtítulos por defecto"); self.c_subs.setChecked(p.descargar_subtitulos)
        self.c_portada = QCheckBox("Descargar portada por defecto"); self.c_portada.setChecked(p.descargar_portada)
        self.c_simult = QSpinBox(); self.c_simult.setRange(1, 8); self.c_simult.setValue(p.descargas_simultaneas)
        self.c_reanudar = QCheckBox("Reanudar descargas pendientes al abrir"); self.c_reanudar.setChecked(p.reanudar_al_iniciar)
        for t, x in [("Organización", self.c_org), ("Si el archivo ya existe", self.c_dup), ("Contenedor de video", self.c_cont),
                     ("Formato de audio", self.c_aud), ("Calidad máxima", self.c_alt), ("Idiomas de subtítulos", self.c_idiomas),
                     ("", self.c_subs), ("", self.c_portada), ("Descargas simultáneas (al reiniciar)", self.c_simult), ("", self.c_reanudar)]:
            f.addRow(t, x)
        guardar = QPushButton("Guardar configuración"); guardar.clicked.connect(self._guardar_config)
        f.addRow("", guardar)
        self.estado_sistema = QLabel(); self.estado_sistema.setWordWrap(True)
        f.addRow("Estado", self.estado_sistema)
        bh = QHBoxLayout()
        for texto, fn in [("Instalar conexión con el navegador", self._instalar_host), ("Quitar conexión", self._quitar_host)]:
            x = QPushButton(texto); x.clicked.connect(fn); bh.addWidget(x)
        bh.addStretch()
        f.addRow("Navegador", bh)
        self._actualizar_estado_sistema()
        return w

    def _elegir_raiz(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Carpeta de descargas", self.c_raiz.text())
        if d:
            self.c_raiz.setText(d)

    def _guardar_config(self) -> None:
        p = self.db.cargar_preferencias()
        try:
            p.carpeta_raiz = Path(self.c_raiz.text()).expanduser()
            p.carpeta_raiz.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Carpeta no válida", f"No se pudo usar esa carpeta.\n{e}"); return
        idiomas = tuple(s.strip() for s in self.c_idiomas.text().split(",") if s.strip())
        try:   # reutiliza las mismas validaciones que las reglas
            reglas.validar_regla({"nombre": "x", "condicion": {"dominio": "x"}, "accion": {"subtitulos": list(idiomas)}})
        except ErrorGestor as e:
            QMessageBox.warning(self, "Idiomas no válidos", texto_error(e)); return
        p.organizacion, p.duplicados = self.c_org.currentData(), self.c_dup.currentData()
        p.contenedor_video, p.formato_audio = self.c_cont.currentData(), self.c_aud.currentData()
        p.altura_max = int(self.c_alt.currentData()) if self.c_alt.currentData() else None
        p.idiomas_subtitulos, p.descargar_subtitulos = idiomas, self.c_subs.isChecked()
        p.descargar_portada, p.descargas_simultaneas = self.c_portada.isChecked(), self.c_simult.value()
        p.reanudar_al_iniciar = self.c_reanudar.isChecked()
        assert p.organizacion in ORGANIZACIONES and p.duplicados in POLITICAS
        self.db.guardar_preferencias(p)
        self.statusBar().showMessage("Configuración guardada", 3000)

    def _actualizar_estado_sistema(self) -> None:
        ff = localizar_ffmpeg()
        host = instalador.estado()
        ok = any(host.values())
        self.estado_sistema.setText(f"FFmpeg: {ff if ff else 'NO encontrado (necesario para unir y convertir)'}\n"
                                    f"Conexión con el navegador: {'instalada' if ok else 'NO instalada'}")

    def _instalar_host(self) -> None:
        try:
            r = instalador.instalar()
            QMessageBox.information(self, "Listo", f"Conexión instalada.\nID de la extensión autorizada:\n{r['extension_id']}\n\n"
                                    "Carga la carpeta «extension» en chrome://extensions (Modo desarrollador).")
        except Exception as e:
            QMessageBox.warning(self, "No se pudo instalar", str(e))
        self._actualizar_estado_sistema()

    def _quitar_host(self) -> None:
        instalador.desinstalar(); self._actualizar_estado_sistema()
