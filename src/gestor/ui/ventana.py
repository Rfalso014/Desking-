"""Ventana principal: barra lateral + páginas (Descargas, Historial, Reglas, Extensión, Configuración)."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import reglas
from ..cola import GestorCola
from ..config import RAIZ_PROYECTO, localizar_deno, localizar_ffmpeg
from ..modelos import ESTADOS_ACTIVOS, ErrorGestor, EstadoTarea, Tarea
from ..nativo import instalador
from ..organizador import ORGANIZACIONES, POLITICAS
from ..validacion import validar_url
from ..vinculacion import Vinculacion
from .dialogos import FORMATOS_AUDIO, AnalisisDialog, DialogoElementos, ReglaDialog, SelectorDestino, SelectorElementos, texto_error
from .estilo import hoja_de_estilos, paleta
from .formatos import formato_cuenta_atras, formato_velocidad
from .tarjeta import ETIQUETA, Miniaturas, TarjetaTarea

FILTROS = [("todas", "Todas"), ("activas", "Activas"), ("completadas", "Completadas"), ("errores", "Con error")]
PAGINAS = [("descargas", "⬇  Descargas"), ("historial", "◷  Historial"), ("reglas", "☰  Reglas"),
           ("extension", "⛓  Extensión"), ("config", "⚙  Configuración")]
MODOS_FORMULARIO = [("Video", "video"), ("Solo audio", "audio"), ("Solo subtítulos", "subtitulos"), ("Solo portada", "portada")]
CALIDADES = [("Según mi configuración", ""), ("La mejor", "mejor"), ("1080p", "1080"), ("720p", "720"), ("480p", "480")]
VELOCIDADES = [("Normal (conexión lenta o inestable)", "normal"), ("Rápida (recomendada)", "rapida"),
               ("Máxima (usa más conexiones a la vez)", "maxima")]
TEMAS = [("Automático (como Windows)", "auto"), ("Claro", "claro"), ("Oscuro", "oscuro")]


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
    t.setShowGrid(False)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    return t


def _celda(texto: str, color: str | None = None) -> QTableWidgetItem:
    i = QTableWidgetItem(texto or "")
    if color:
        i.setForeground(QColor(color))
    return i


def _boton(texto: str, *, primario=False, peligro=False, filtro=False, enlace=False, tip: str = "") -> QPushButton:
    b = QPushButton(texto)
    for nombre, activo in (("primary", primario), ("peligro", peligro), ("filtro", filtro), ("enlace", enlace)):
        if activo:
            b.setProperty(nombre, True)
    if filtro:
        b.setCheckable(True)
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def _titulo(texto: str, sub: str = "") -> QVBoxLayout:
    lay = QVBoxLayout(); lay.setSpacing(2)
    t = QLabel(texto); t.setObjectName("titulo")
    lay.addWidget(t)
    if sub:
        s = QLabel(sub); s.setObjectName("subtitulo"); s.setWordWrap(True)
        lay.addWidget(s)
    return lay


def _pagina() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget(); w.setObjectName("pagina")
    lay = QVBoxLayout(w); lay.setContentsMargins(28, 24, 28, 18); lay.setSpacing(14)
    return w, lay


def _caja() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame(); f.setObjectName("caja")
    lay = QVBoxLayout(f); lay.setContentsMargins(18, 16, 18, 16); lay.setSpacing(10)
    return f, lay


class VentanaPrincipal(QMainWindow):
    def __init__(self, cola: GestorCola, vinculacion: Vinculacion | None = None):
        super().__init__()
        self.cola, self.db = cola, cola.db
        self.vinc = vinculacion or Vinculacion(cola.db)
        self.setWindowTitle("Gestor de Descargas")
        self.resize(1120, 720); self.setMinimumSize(940, 620)
        self.puente = Puente()
        self.puente.cambio.connect(self._programar_refresco)
        self.puente.analisis.connect(self._mostrar_analisis)
        cola.suscribir(self.puente.cambio.emit)
        self.miniaturas = Miniaturas(self)
        self.miniaturas.lista.connect(lambda _u: self._programar_refresco({}))
        self.tarjetas: dict[str, TarjetaTarea] = {}
        self.filtro_actual = "todas"
        self._ultima_sugerencia = ""

        central = QWidget(); self.setCentralWidget(central)
        raiz = QHBoxLayout(central); raiz.setContentsMargins(0, 0, 0, 0); raiz.setSpacing(0)
        raiz.addWidget(self._barra_lateral())
        self.paginas = QStackedWidget(); raiz.addWidget(self.paginas, 1)
        self._indice = {}
        for clave, constructor in (("descargas", self._pagina_descargas), ("historial", self._pagina_historial),
                                   ("reglas", self._pagina_reglas), ("extension", self._pagina_extension),
                                   ("config", self._pagina_config)):
            self._indice[clave] = self.paginas.addWidget(constructor())
        self.ir_a("descargas")
        self.aplicar_tema()

        self._temporizador = QTimer(self, singleShot=True, interval=250)   # agrupa avisos seguidos
        self._temporizador.timeout.connect(self.refrescar)
        self._reloj = QTimer(self, interval=1000); self._reloj.timeout.connect(self._cada_segundo); self._reloj.start()
        QGuiApplication.clipboard().dataChanged.connect(self._revisar_portapapeles)
        self.refrescar(); self._cargar_reglas(); self._pintar_vinculos(); self._pintar_codigo(); self._actualizar_estado_sistema()

    # --- tema ---------------------------------------------------------------------------
    def aplicar_tema(self) -> None:
        tema = self.db.cargar_preferencias().tema
        if tema == "auto":
            oscuro = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        else:
            oscuro = tema == "oscuro"
        self.setStyleSheet(hoja_de_estilos(paleta(oscuro)))

    # --- barra lateral --------------------------------------------------------------------
    def _barra_lateral(self) -> QWidget:
        f = QFrame(); f.setObjectName("lateral"); f.setFixedWidth(230)
        lay = QVBoxLayout(f); lay.setContentsMargins(14, 20, 14, 14); lay.setSpacing(4)
        marca = QLabel("⬇ Gestor de\nDescargas"); marca.setObjectName("marca")
        sub = QLabel("Video, audio, subtítulos\ne imágenes"); sub.setObjectName("submarca")
        lay.addWidget(marca); lay.addWidget(sub); lay.addSpacing(18)
        self._nav = {}
        grupo = QButtonGroup(self); grupo.setExclusive(True)
        for clave, texto in PAGINAS:
            b = QPushButton(texto); b.setProperty("nav", True); b.setCheckable(True); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=clave: self.ir_a(c))
            grupo.addButton(b); lay.addWidget(b); self._nav[clave] = b
        lay.addStretch()
        self.pie = QLabel(); self.pie.setObjectName("pie"); self.pie.setWordWrap(True)
        lay.addWidget(self.pie)
        return f

    def ir_a(self, clave: str) -> None:
        self.paginas.setCurrentIndex(self._indice[clave])
        self._nav[clave].setChecked(True)
        if clave == "extension":
            self._pintar_codigo(); self._pintar_vinculos()

    # ========================= DESCARGAS ===========================================================
    def _pagina_descargas(self) -> QWidget:
        w, lay = _pagina()
        cab = QHBoxLayout(); cab.addLayout(_titulo("Descargas", "Pega un enlace o envíalo desde la extensión del navegador."), 1)
        self.resumen = QLabel(); self.resumen.setProperty("tenue", True)
        cab.addWidget(self.resumen, 0, Qt.AlignBottom); lay.addLayout(cab)

        caja, c = _caja()
        fila = QHBoxLayout(); fila.setSpacing(8)
        self.url = QLineEdit(); self.url.setObjectName("entradaUrl")
        self.url.setPlaceholderText("Pega aquí el enlace de un video, audio, imagen o página…"); self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self._anadir)
        b_pegar = _boton("Pegar", tip="Pega el enlace que tengas copiado"); b_pegar.clicked.connect(self._pegar)
        b_analizar = _boton("Analizar", tip="Muestra calidades, subtítulos y si el contenido es compatible, sin descargar")
        b_analizar.clicked.connect(self._analizar)
        b_anadir = _boton("Descargar", primario=True, tip="Añade el enlace a la cola; la descarga la hace esta aplicación")
        b_anadir.clicked.connect(self._anadir)
        for x in (self.url, b_pegar, b_analizar, b_anadir):
            fila.addWidget(x)
        fila.setStretch(0, 1); c.addLayout(fila)
        titulo_sel = QLabel("¿Qué quieres descargar?"); titulo_sel.setProperty("seccion", True); c.addWidget(titulo_sel)
        self.selector = SelectorElementos(self.db.cargar_preferencias())
        c.addWidget(self.selector)
        self.destino = SelectorDestino(self.db.cargar_preferencias())
        c.addWidget(self.destino)
        self.sugerencia = QFrame(); self.sugerencia.setObjectName("caja"); self.sugerencia.hide()
        sl = QHBoxLayout(self.sugerencia); sl.setContentsMargins(12, 8, 12, 8)
        self.texto_sugerencia = QLabel(); sl.addWidget(self.texto_sugerencia, 1)
        b1 = _boton("Descargar este enlace", primario=True); b1.clicked.connect(self._aceptar_sugerencia)
        b2 = _boton("Ahora no", enlace=True); b2.clicked.connect(self.sugerencia.hide)
        sl.addWidget(b1); sl.addWidget(b2); c.addWidget(self.sugerencia)
        lay.addWidget(caja)

        filtros = QHBoxLayout(); filtros.setSpacing(6)
        self._grupo_filtros = QButtonGroup(self); self._botones_filtro = {}
        for clave, texto in FILTROS:
            b = _boton(texto, filtro=True); b.clicked.connect(lambda _=False, k=clave: self._filtrar(k))
            self._grupo_filtros.addButton(b); filtros.addWidget(b); self._botones_filtro[clave] = b
        self._botones_filtro["todas"].setChecked(True); filtros.addStretch()
        limpiar = _boton("Quitar las terminadas de la lista", enlace=True, tip="No borra los archivos descargados")
        limpiar.clicked.connect(self._limpiar_terminadas); filtros.addWidget(limpiar); lay.addLayout(filtros)

        self.lista = QWidget(); self.lista.setObjectName("pagina")
        self.lista_lay = QVBoxLayout(self.lista); self.lista_lay.setContentsMargins(0, 0, 6, 0); self.lista_lay.setSpacing(10)
        self.vacio = QLabel("Aún no hay descargas.\nPega un enlace arriba, o usa el botón «Descargar» que aparece sobre los videos "
                            "cuando tienes la extensión instalada.")
        self.vacio.setAlignment(Qt.AlignCenter); self.vacio.setProperty("tenue", True)
        self.lista_lay.addWidget(self.vacio); self.lista_lay.addStretch()
        area = QScrollArea(); area.setWidgetResizable(True); area.setFrameShape(QFrame.NoFrame); area.setWidget(self.lista)
        lay.addWidget(area, 1)
        return w

    def _pegar(self) -> None:
        self.url.setText(QGuiApplication.clipboard().text().strip())

    def _anadir(self) -> None:
        try:
            for opciones in self.destino.aplicar(self.selector.opciones()):        # video + audio marcados = dos descargas
                self.cola.encolar(self.url.text(), opciones=opciones)
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

    # Si copias un enlace mientras la app está abierta, la app te ofrece descargarlo.
    def _revisar_portapapeles(self) -> None:
        texto = QGuiApplication.clipboard().text().strip()
        if texto == self._ultima_sugerencia or len(texto) > 2000:
            return
        try:
            validar_url(texto)
        except ErrorGestor:
            return
        self._ultima_sugerencia = texto
        self.texto_sugerencia.setText(f"Enlace copiado: {texto[:90]}{'…' if len(texto) > 90 else ''}")
        self.sugerencia.show()

    def _aceptar_sugerencia(self) -> None:
        self.url.setText(self._ultima_sugerencia); self.sugerencia.hide(); self._anadir()

    def _filtrar(self, clave: str) -> None:
        self.filtro_actual = clave
        self.refrescar()

    def _limpiar_terminadas(self) -> None:
        self.cola.limpiar_terminadas(); self.refrescar()

    def _accion_tarjeta(self, accion: str, id_: str) -> None:
        try:
            if accion == "iniciar_detectada":
                self._autorizar_detectada(id_)
            elif accion == "abrir_carpeta":
                t = self.db.obtener_tarea(id_)
                if t and t.carpeta_final and Path(t.carpeta_final).exists():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(t.carpeta_final))
            else:
                getattr(self.cola, accion)(id_)
        except ErrorGestor as e:
            QMessageBox.information(self, "No se puede", texto_error(e))
        self.refrescar()

    def _autorizar_detectada(self, id_: str) -> None:
        """El usuario autoriza una descarga detectada: antes elige qué quiere de ella."""
        t = self.db.obtener_tarea(id_)
        if t is None:
            return
        d = DialogoElementos(self, t.titulo or t.url, self.db.cargar_preferencias(), t.opciones)
        if d.exec() and d.resultado:
            self.cola.iniciar_detectada(id_, d.resultado[0])
            for extra in d.resultado[1:]:                    # p. ej. el audio aparte
                self.cola.encolar(t.url, origen=t.origen, opciones=extra)

    def _programar_refresco(self, _d: dict) -> None:
        if not self._temporizador.isActive():
            self._temporizador.start()

    def _pasa_filtro(self, t: Tarea) -> bool:
        f = self.filtro_actual
        return (f == "todas" or (f == "activas" and (t.estado in ESTADOS_ACTIVOS or t.estado in (EstadoTarea.PENDIENTE, EstadoTarea.DETECTADO)))
                or (f == "completadas" and t.estado == EstadoTarea.COMPLETADO) or (f == "errores" and t.estado == EstadoTarea.ERROR))

    def refrescar(self) -> None:
        todas = self.cola.listar(limite=300)
        visibles = [t for t in todas if self._pasa_filtro(t)]
        visibles.sort(key=lambda t: 0 if t.estado in (EstadoTarea.DESCARGANDO, EstadoTarea.PROCESANDO, EstadoTarea.ANALIZANDO) else 1)  # activas arriba
        ids = [t.id for t in visibles]
        for id_ in [i for i in self.tarjetas if i not in ids]:          # quitar las que ya no están
            self.tarjetas.pop(id_).deleteLater()
        orden_actual = [self.lista_lay.itemAt(i).widget() for i in range(self.lista_lay.count()) if self.lista_lay.itemAt(i).widget()]
        for t in visibles:
            tarjeta = self.tarjetas.get(t.id)
            if tarjeta is None:
                tarjeta = self.tarjetas[t.id] = TarjetaTarea(t.id)
                tarjeta.accion.connect(self._accion_tarjeta)
            tarjeta.actualizar(t, self.miniaturas.obtener(t.miniatura))
        nuevo = [self.tarjetas[i] for i in ids]
        if [w for w in orden_actual if w is not self.vacio] != nuevo:
            for w in orden_actual:
                self.lista_lay.removeWidget(w)
            for i, tarjeta in enumerate(nuevo):
                self.lista_lay.insertWidget(i, tarjeta)
        self.vacio.setVisible(not nuevo)
        if not nuevo:
            self.lista_lay.insertWidget(0, self.vacio)
        activas = [t for t in todas if t.estado == EstadoTarea.DESCARGANDO]
        pendientes = sum(1 for t in todas if t.estado in (EstadoTarea.PENDIENTE, EstadoTarea.ANALIZANDO, EstadoTarea.PROCESANDO))
        vel = formato_velocidad(sum(t.velocidad_bps or 0 for t in activas))
        self.resumen.setText("  ·  ".join(x for x in (f"{len(activas)} descargando" if activas else "Nada descargando",
                                                      f"{pendientes} en espera" if pendientes else "", vel) if x))
        self.statusBar().showMessage(f"{len(todas)} descarga(s) en la lista")
        if hasattr(self, "tabla_hist"):
            self._refrescar_historial()

    # ========================= HISTORIAL ===========================================================
    def _pagina_historial(self) -> QWidget:
        w, lay = _pagina()
        lay.addLayout(_titulo("Historial", "Todo lo que has descargado o intentado descargar. Buscar no borra nada."))
        fila = QHBoxLayout()
        self.buscar = QLineEdit(); self.buscar.setPlaceholderText("Buscar por título, sitio o enlace…"); self.buscar.setClearButtonEnabled(True)
        self.filtro = QComboBox(); self.filtro.addItem("Todos los estados", None)
        for e in EstadoTarea:
            self.filtro.addItem(ETIQUETA[e.value], e)
        self.buscar.textChanged.connect(self._refrescar_historial); self.filtro.currentIndexChanged.connect(self._refrescar_historial)
        fila.addWidget(self.buscar, 1); fila.addWidget(self.filtro); lay.addLayout(fila)
        self.tabla_hist = _tabla(["Contenido", "Sitio", "Estado", "Fecha"])
        lay.addWidget(self.tabla_hist, 1)
        botones = QHBoxLayout()
        for texto, f, p in [("Reintentar", lambda: self._accion_hist("reintentar"), False),
                            ("Eliminar registro", lambda: self._accion_hist("eliminar"), True),
                            ("Limpiar historial terminado", self._limpiar_historial, True)]:
            b = _boton(texto, peligro=p); b.clicked.connect(f); botones.addWidget(b)
        botones.addStretch(); lay.addLayout(botones)
        return w

    def _tarea_hist(self) -> Tarea | None:
        filas = self.tabla_hist.selectionModel().selectedRows()
        return self.db.obtener_tarea(self.tabla_hist.item(filas[0].row(), 0).data(Qt.UserRole)) if filas else None

    def _accion_hist(self, accion: str) -> None:
        t = self._tarea_hist()
        if t:
            self._accion_tarjeta(accion, t.id)

    def _refrescar_historial(self, *_) -> None:
        e = self.filtro.currentData()
        tareas = self.db.listar_tareas(estados=[e] if e else None, texto=self.buscar.text() or None, limite=500)
        self.tabla_hist.setRowCount(len(tareas))
        colores = {"completado": "#16a34a", "error": "#dc2626"}
        for fila, t in enumerate(tareas):
            c0 = _celda(t.titulo or t.url); c0.setData(Qt.UserRole, t.id)
            self.tabla_hist.setItem(fila, 0, c0); self.tabla_hist.setItem(fila, 1, _celda(t.sitio or ""))
            self.tabla_hist.setItem(fila, 2, _celda(ETIQUETA[t.estado.value], colores.get(t.estado.value)))
            self.tabla_hist.setItem(fila, 3, _celda(t.creado[:16].replace("T", " ")))

    def _limpiar_historial(self) -> None:
        if QMessageBox.question(self, "Limpiar historial", "¿Borrar del historial las descargas completadas, canceladas y con error?\n"
                                "(No se borran los archivos descargados.)") == QMessageBox.Yes:
            self.db.limpiar_historial(); self.refrescar()

    # ========================= REGLAS ==============================================================
    def _pagina_reglas(self) -> QWidget:
        w, lay = _pagina()
        lay.addLayout(_titulo("Reglas", "Cambian cómo se descarga un sitio concreto. Una elección hecha para una descarga puntual "
                                        "gana a las reglas, y las reglas ganan a la configuración general."))
        self.tabla_reglas = _tabla(["Nombre", "Prioridad", "Activa", "Condición", "Acción"])
        lay.addWidget(self.tabla_reglas, 1)
        botones = QHBoxLayout()
        for texto, f, p in [("Nueva regla", self._regla_nueva, True), ("Editar", self._regla_editar, False),
                            ("Activar / desactivar", self._regla_alternar, False), ("Eliminar", self._regla_eliminar, False)]:
            b = _boton(texto, primario=p); b.clicked.connect(f); botones.addWidget(b)
        botones.addStretch(); lay.addLayout(botones)
        caja, c = _caja()
        t = QLabel("¿Qué regla se aplicaría a este enlace?"); t.setProperty("seccion", True); c.addWidget(t)
        prueba = QHBoxLayout()
        self.url_prueba = QLineEdit(); self.url_prueba.setPlaceholderText("https://…")
        b = _boton("Probar"); b.clicked.connect(self._probar_regla)
        prueba.addWidget(self.url_prueba, 1); prueba.addWidget(b); c.addLayout(prueba)
        self.resultado_prueba = QPlainTextEdit(); self.resultado_prueba.setReadOnly(True); self.resultado_prueba.setMaximumHeight(130)
        c.addWidget(self.resultado_prueba); lay.addWidget(caja)
        return w

    def _cargar_reglas(self) -> None:
        rs = self.db.listar_reglas()
        self.tabla_reglas.setRowCount(len(rs))
        for i, r in enumerate(rs):
            c0 = _celda(r["nombre"]); c0.setData(Qt.UserRole, r["id"])
            self.tabla_reglas.setItem(i, 0, c0); self.tabla_reglas.setItem(i, 1, _celda(str(r["prioridad"])))
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

    # ========================= EXTENSIÓN (vinculación) ==============================================
    def _pagina_extension(self) -> QWidget:
        w, lay = _pagina()
        lay.addLayout(_titulo("Extensión del navegador", "La extensión solo detecta videos y te deja ordenar «Descargar» o «Eliminar». "
                                                         "Quien descarga siempre es esta aplicación."))
        caja, c = _caja()
        for n, texto, boton, f in [
            ("1", "Instala la conexión con Chrome y Edge (una sola vez).", "Instalar conexión", self._instalar_host),
            ("2", "En el navegador abre chrome://extensions, activa «Modo de desarrollador» y pulsa «Cargar descomprimida».",
             "Abrir carpeta de la extensión", self._abrir_carpeta_extension)]:
            fila = QHBoxLayout(); p = QLabel(n); p.setObjectName("paso"); fila.addWidget(p)
            l = QLabel(texto); l.setWordWrap(True); fila.addWidget(l, 1)
            b = _boton(boton); b.clicked.connect(f); fila.addWidget(b); c.addLayout(fila)
        fila = QHBoxLayout(); p = QLabel("3"); p.setObjectName("paso"); fila.addWidget(p)
        l = QLabel("Escribe este código en la extensión para vincularla con la aplicación:"); l.setWordWrap(True); fila.addWidget(l, 1)
        c.addLayout(fila)
        centro = QVBoxLayout(); centro.setAlignment(Qt.AlignHCenter)
        self.etiqueta_codigo = QLabel("----"); self.etiqueta_codigo.setObjectName("codigo"); self.etiqueta_codigo.setAlignment(Qt.AlignCenter)
        self.etiqueta_codigo.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.vence = QLabel(); self.vence.setProperty("tenue", True); self.vence.setAlignment(Qt.AlignCenter)
        centro.addWidget(self.etiqueta_codigo, 0, Qt.AlignHCenter); centro.addWidget(self.vence)
        botones = QHBoxLayout(); botones.addStretch()
        b = _boton("Copiar código"); b.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.etiqueta_codigo.text()))
        n = _boton("Generar uno nuevo", tip="El anterior deja de servir"); n.clicked.connect(lambda: (self.vinc.renovar(), self._pintar_codigo()))
        botones.addWidget(b); botones.addWidget(n); botones.addStretch(); centro.addLayout(botones)
        c.addLayout(centro)
        nota = QLabel("El código dura 10 minutos y sirve una sola vez. Tras 5 intentos fallidos se bloquea un minuto."); nota.setProperty("tenue", True)
        nota.setWordWrap(True); c.addWidget(nota)
        lay.addWidget(caja)

        t = QLabel("Extensiones vinculadas"); t.setProperty("seccion", True); lay.addWidget(t)
        self.tabla_vinculos = _tabla(["Nombre", "Vinculada el", "Último uso"])
        lay.addWidget(self.tabla_vinculos, 1)
        fila = QHBoxLayout()
        r = _boton("Revocar la seleccionada", peligro=True, tip="Esa extensión dejará de poder usar la aplicación"); r.clicked.connect(self._revocar_vinculo)
        fila.addWidget(r); fila.addStretch(); lay.addLayout(fila)
        return w

    def _pintar_codigo(self) -> None:
        codigo, resto = self.vinc.codigo_actual()
        self.etiqueta_codigo.setText(codigo)
        self.vence.setText(f"Vence en {formato_cuenta_atras(resto)}")

    def _pintar_vinculos(self) -> None:
        vs = self.vinc.listar()
        self.tabla_vinculos.setRowCount(len(vs))
        for i, v in enumerate(vs):
            c0 = _celda(v["nombre"]); c0.setData(Qt.UserRole, v["id"])
            self.tabla_vinculos.setItem(i, 0, c0)
            self.tabla_vinculos.setItem(i, 1, _celda(v["creado"][:16].replace("T", " ")))
            self.tabla_vinculos.setItem(i, 2, _celda((v["ultimo_uso"] or "nunca")[:16].replace("T", " ")))

    def _revocar_vinculo(self) -> None:
        filas = self.tabla_vinculos.selectionModel().selectedRows()
        if filas and QMessageBox.question(self, "Revocar", "¿Revocar esta extensión? Tendrás que vincularla de nuevo con un código.") == QMessageBox.Yes:
            self.vinc.revocar(self.tabla_vinculos.item(filas[0].row(), 0).data(Qt.UserRole)); self._pintar_vinculos(); self._actualizar_estado_sistema()

    def _abrir_carpeta_extension(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(RAIZ_PROYECTO / "extension")))

    def _cada_segundo(self) -> None:
        if self.paginas.currentIndex() == self._indice["extension"]:
            self._pintar_codigo()

    # ========================= CONFIGURACIÓN ========================================================
    def _pagina_config(self) -> QWidget:
        p = self.db.cargar_preferencias()
        w, lay = _pagina()
        lay.addLayout(_titulo("Configuración"))
        contenido = QWidget(); contenido.setObjectName("pagina"); cl = QVBoxLayout(contenido); cl.setSpacing(12); cl.setContentsMargins(0, 0, 8, 0)

        g1 = QGroupBox("Carpeta y archivos"); f1 = QFormLayout(g1)
        self.c_raiz = QLineEdit(str(p.carpeta_raiz)); b = _boton("Elegir…"); b.clicked.connect(self._elegir_raiz)
        fila = QHBoxLayout(); fila.addWidget(self.c_raiz, 1); fila.addWidget(b); f1.addRow("Carpeta de descargas", fila)
        self.c_org = QComboBox()
        for k, t in [("tipo_y_contenido", "Por tipo y por contenido (Videos/Nombre/…)"), ("tipo", "Solo por tipo"),
                     ("contenido", "Solo por contenido"), ("manual", "Manual (la elijo yo cada vez)")]:
            self.c_org.addItem(t, k)
        self.c_org.setCurrentIndex(self.c_org.findData(p.organizacion)); f1.addRow("Organización", self.c_org)
        self.c_dup = QComboBox()
        for k, t in [("renombrar", "Renombrar (añadir número)"), ("omitir", "Omitir (conservar el existente)"), ("reemplazar", "Reemplazar")]:
            self.c_dup.addItem(t, k)
        self.c_dup.setCurrentIndex(self.c_dup.findData(p.duplicados)); f1.addRow("Si el archivo ya existe", self.c_dup)
        cl.addWidget(g1)

        g2 = QGroupBox("Calidad y formatos"); f2 = QFormLayout(g2)
        self.c_cont = QComboBox(); [self.c_cont.addItem(t, d) for t, d in [("MP4", "mp4"), ("MKV", "mkv"), ("El mejor disponible", "mejor")]]
        self.c_cont.setCurrentIndex(self.c_cont.findData(p.contenedor_video)); f2.addRow("Contenedor de video", self.c_cont)
        self.c_aud = QComboBox(); [self.c_aud.addItem(t, d) for t, d in FORMATOS_AUDIO[1:]]
        self.c_aud.setCurrentIndex(self.c_aud.findData(p.formato_audio)); f2.addRow("Formato de audio", self.c_aud)
        self.c_alt = QComboBox(); [self.c_alt.addItem(t, d) for t, d in [("La mejor", ""), ("1080p", "1080"), ("720p", "720"), ("480p", "480")]]
        self.c_alt.setCurrentIndex(self.c_alt.findData(str(p.altura_max) if p.altura_max else "")); f2.addRow("Calidad máxima", self.c_alt)
        self.c_idiomas = QLineEdit(",".join(p.idiomas_subtitulos)); f2.addRow("Idiomas de subtítulos", self.c_idiomas)
        self.c_subs = QCheckBox("Descargar subtítulos por defecto"); self.c_subs.setChecked(p.descargar_subtitulos); f2.addRow("", self.c_subs)
        self.c_portada = QCheckBox("Descargar la portada por defecto"); self.c_portada.setChecked(p.descargar_portada); f2.addRow("", self.c_portada)
        cl.addWidget(g2)

        g3 = QGroupBox("Velocidad"); f3 = QFormLayout(g3)
        self.c_vel = QComboBox(); [self.c_vel.addItem(t, d) for t, d in VELOCIDADES]
        self.c_vel.setCurrentIndex(self.c_vel.findData(p.velocidad)); f3.addRow("Perfil", self.c_vel)
        self.c_simult = QSpinBox(); self.c_simult.setRange(1, 8); self.c_simult.setValue(p.descargas_simultaneas)
        f3.addRow("Descargas a la vez (al reiniciar)", self.c_simult)
        self.c_reanudar = QCheckBox("Reanudar las descargas pendientes al abrir"); self.c_reanudar.setChecked(p.reanudar_al_iniciar); f3.addRow("", self.c_reanudar)
        cl.addWidget(g3)

        g4 = QGroupBox("Apariencia y sistema"); f4 = QFormLayout(g4)
        self.c_tema = QComboBox(); [self.c_tema.addItem(t, d) for t, d in TEMAS]
        self.c_tema.setCurrentIndex(self.c_tema.findData(p.tema)); f4.addRow("Tema", self.c_tema)
        self.estado_sistema = QLabel(); self.estado_sistema.setWordWrap(True); f4.addRow("Estado", self.estado_sistema)
        bh = QHBoxLayout()
        for texto, fn in [("Instalar conexión con el navegador", self._instalar_host), ("Quitar conexión", self._quitar_host)]:
            x = _boton(texto); x.clicked.connect(fn); bh.addWidget(x)
        bh.addStretch(); f4.addRow("Navegador", bh)
        cl.addWidget(g4); cl.addStretch()
        area = QScrollArea(); area.setWidgetResizable(True); area.setFrameShape(QFrame.NoFrame); area.setWidget(contenido)
        lay.addWidget(area, 1)
        guardar = _boton("Guardar configuración", primario=True); guardar.clicked.connect(self._guardar_config)
        pie = QHBoxLayout(); pie.addStretch(); pie.addWidget(guardar); lay.addLayout(pie)
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
        p.reanudar_al_iniciar, p.velocidad, p.tema = self.c_reanudar.isChecked(), self.c_vel.currentData(), self.c_tema.currentData()
        assert p.organizacion in ORGANIZACIONES and p.duplicados in POLITICAS
        self.db.guardar_preferencias(p)
        self.aplicar_tema()
        self.statusBar().showMessage("Configuración guardada", 3000)

    def _actualizar_estado_sistema(self) -> None:
        ff, deno, host = localizar_ffmpeg(), localizar_deno(), instalador.estado()
        conexion = any(host.values())
        n = len(self.vinc.listar())
        self.estado_sistema.setText(
            f"FFmpeg: {'listo' if ff else 'NO encontrado (necesario para unir y convertir)'}\n"
            f"Deno (mejora YouTube): {'listo' if deno else 'no instalado (opcional)'}\n"
            f"Conexión con el navegador: {'instalada' if conexion else 'NO instalada'}\n"
            f"Extensiones vinculadas: {n}")
        self.pie.setText(f"{'●' if ff else '○'} FFmpeg\n{'●' if deno else '○'} Deno (YouTube)\n"
                         f"{'●' if conexion else '○'} Conexión con el navegador\n{'●' if n else '○'} Extensión vinculada" +
                         (f" ({n})" if n else ""))

    def _instalar_host(self) -> None:
        try:
            r = instalador.instalar()
            QMessageBox.information(self, "Conexión instalada", f"Listo. ID de la extensión autorizada:\n{r['extension_id']}\n\n"
                                    "Ahora carga la carpeta «extension» en chrome://extensions.")
        except Exception as e:
            QMessageBox.warning(self, "No se pudo instalar", str(e))
        self._actualizar_estado_sistema()

    def _quitar_host(self) -> None:
        instalador.desinstalar(); self._actualizar_estado_sistema()
