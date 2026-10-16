"""Tema visual (claro y oscuro) de la aplicación, escrito como hoja de estilos Qt (QSS).

QSS es como CSS: describe colores, bordes y tamaños. Los colores viven en un diccionario
para que cambiar de tema sea cambiar de diccionario.
"""
OSCURO = {
    "fondo": "#12151a", "lateral": "#171b21", "superficie": "#1d222a", "superficie2": "#262c36",
    "borde": "#2f3642", "texto": "#e8ebf1", "tenue": "#9aa4b5", "acento": "#4f8cff", "acento_h": "#6aa0ff",
    "sobre_acento": "#ffffff", "ok": "#3ecf8e", "error": "#ff7070", "aviso": "#f5b94a", "seleccion": "#2a3a5c",
}
CLARO = {
    "fondo": "#f3f5f9", "lateral": "#ffffff", "superficie": "#ffffff", "superficie2": "#eef1f6",
    "borde": "#dde2ea", "texto": "#1b2230", "tenue": "#667085", "acento": "#2563eb", "acento_h": "#1d4fd0",
    "sobre_acento": "#ffffff", "ok": "#15803d", "error": "#dc2626", "aviso": "#b45309", "seleccion": "#dbe7ff",
}

# Colores de cada estado de descarga (se usan en las etiquetas)
COLOR_ESTADO = {
    "detectado": "tenue", "analizando": "aviso", "pendiente": "tenue", "descargando": "acento",
    "procesando": "aviso", "completado": "ok", "cancelado": "tenue", "error": "error",
}


def paleta(oscuro: bool) -> dict:
    return OSCURO if oscuro else CLARO


def hoja_de_estilos(c: dict) -> str:
    def tinte(hex_: str, a: float = 0.16) -> str:      # mismo color pero casi transparente, para el fondo de las etiquetas
        r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
        return f"rgba({r},{g},{b},{a})"
    estados = "\n".join(
        f'QLabel[estado="{e}"] {{ color: {c[k]}; background: {tinte(c[k])}; }}' for e, k in COLOR_ESTADO.items())
    return f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {c['texto']}; }}
QMainWindow, QWidget#pagina, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c['fondo']}; }}
QToolTip {{ background: {c['superficie2']}; color: {c['texto']}; border: 1px solid {c['borde']}; padding: 4px 8px; }}

/* Barra lateral */
QFrame#lateral {{ background: {c['lateral']}; border-right: 1px solid {c['borde']}; }}
QLabel#marca {{ font-size: 14pt; font-weight: 700; }}
QLabel#submarca {{ color: {c['tenue']}; font-size: 9pt; }}
QPushButton[nav="true"] {{ text-align: left; padding: 10px 14px; border: none; border-radius: 10px; color: {c['tenue']};
                           font-weight: 600; background: transparent; }}
QPushButton[nav="true"]:hover {{ background: {c['superficie2']}; color: {c['texto']}; }}
QPushButton[nav="true"]:checked {{ background: {c['seleccion']}; color: {c['acento']}; }}
QLabel#pie {{ color: {c['tenue']}; font-size: 9pt; }}

/* Títulos */
QLabel#titulo {{ font-size: 20pt; font-weight: 700; }}
QLabel#subtitulo {{ color: {c['tenue']}; }}
QLabel[seccion="true"] {{ font-size: 11pt; font-weight: 700; }}
QLabel[tenue="true"] {{ color: {c['tenue']}; }}

/* Tarjetas */
QFrame#tarjeta, QFrame#caja {{ background: {c['superficie']}; border: 1px solid {c['borde']}; border-radius: 14px; }}
QFrame#tarjeta:hover {{ border-color: {c['acento']}; }}
QLabel#miniatura {{ background: {c['superficie2']}; border-radius: 10px; color: {c['tenue']}; font-size: 20pt; }}
QLabel#tituloTarjeta {{ font-weight: 700; font-size: 11pt; }}
QLabel#detalle {{ color: {c['tenue']}; font-size: 9pt; }}
QLabel#errorTexto {{ color: {c['error']}; font-size: 9pt; }}
QLabel[chip="true"] {{ border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 8.5pt; }}
{estados}
QLabel#codigo {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 34pt; font-weight: 700; letter-spacing: 4px;
                 color: {c['acento']}; background: {c['superficie2']}; border-radius: 14px; padding: 12px 24px; }}
QLabel#paso {{ background: {c['acento']}; color: {c['sobre_acento']}; border-radius: 13px; font-weight: 700; min-width: 26px; max-width: 26px;
               min-height: 26px; max-height: 26px; qproperty-alignment: AlignCenter; }}

/* Progreso */
QProgressBar {{ background: {c['superficie2']}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['acento']}; border-radius: 4px; }}

/* Botones */
QPushButton {{ background: {c['superficie2']}; border: 1px solid {c['borde']}; border-radius: 9px; padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ border-color: {c['acento']}; }}
QPushButton:pressed {{ background: {c['seleccion']}; }}
QPushButton:disabled {{ color: {c['tenue']}; }}
QPushButton[primary="true"] {{ background: {c['acento']}; border-color: {c['acento']}; color: {c['sobre_acento']}; }}
QPushButton[primary="true"]:hover {{ background: {c['acento_h']}; }}
QPushButton[peligro="true"] {{ color: {c['error']}; }}
QPushButton[filtro="true"] {{ border-radius: 14px; padding: 5px 14px; background: transparent; color: {c['tenue']}; }}
QPushButton[filtro="true"]:checked {{ background: {c['seleccion']}; color: {c['acento']}; border-color: {c['acento']}; }}
QPushButton[enlace="true"] {{ border: none; background: transparent; color: {c['acento']}; padding: 2px 4px; }}
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {c['acento']}; }}

/* Campos */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ background: {c['superficie']}; border: 1px solid {c['borde']}; border-radius: 9px; padding: 7px 10px;
                                                  selection-background-color: {c['acento']}; selection-color: {c['sobre_acento']}; }}
QLineEdit#entradaUrl {{ font-size: 11pt; padding: 11px 14px; }}
QComboBox QAbstractItemView {{ background: {c['superficie']}; border: 1px solid {c['borde']}; selection-background-color: {c['seleccion']}; selection-color: {c['texto']}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {c['borde']}; background: {c['superficie']}; }}
QCheckBox::indicator:checked {{ background: {c['acento']}; border-color: {c['acento']}; }}
QGroupBox {{ border: 1px solid {c['borde']}; border-radius: 14px; margin-top: 14px; padding: 16px 14px 10px 14px; background: {c['superficie']}; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {c['tenue']}; }}

/* Tablas */
QTableWidget {{ background: {c['superficie']}; border: 1px solid {c['borde']}; border-radius: 12px; gridline-color: transparent; selection-background-color: {c['seleccion']};
                selection-color: {c['texto']}; alternate-background-color: {c['superficie']}; }}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {c['borde']}; }}
QHeaderView::section {{ background: {c['superficie2']}; color: {c['tenue']}; border: none; border-bottom: 1px solid {c['borde']}; padding: 8px; font-weight: 700; text-align: left; }}
QTableCornerButton::section {{ background: {c['superficie2']}; border: none; }}

/* Barras de desplazamiento */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['borde']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['tenue']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QStatusBar {{ background: {c['lateral']}; color: {c['tenue']}; border-top: 1px solid {c['borde']}; }}
QMessageBox, QDialog {{ background: {c['fondo']}; }}
"""
