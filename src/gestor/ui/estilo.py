"""Tema visual de la aplicación (diseño «riel lateral», el mismo de la extensión) como hoja de estilos Qt (QSS).

Día = verde azulado y amarillo; noche = violeta y coral. Los colores viven en un diccionario
para que cambiar de tema sea cambiar de diccionario (y coinciden con extension/popup.css).
"""
DIA = {
    "riel": "#1f9e94", "riel_texto": "#d8f3f0", "fondo": "#ffffff", "superficie": "#ffffff", "tarjeta": "#f2f8f8",
    "superficie2": "#e6f2f1", "borde": "#e3ecee", "texto": "#1d2445", "tenue": "#6b7390", "titulo": "#1d2445",
    "acento": "#1f9e94", "acento_h": "#188a81", "sobre_acento": "#ffffff", "resalte": "#ffd45c", "sobre_resalte": "#4a3600",
    "promo": "#d4eef8", "ok": "#2c6b34", "error": "#b42323", "aviso": "#7a5600", "seleccion": "#d9f2ef",
    "e_azul": ("#d9f2ef", "#0f6e66"), "e_amarillo": ("#fff3c9", "#7a5600"), "e_verde": ("#e2f5e4", "#2c6b34"),
    "e_rojo": ("#fde4e4", "#a12d2d"), "e_gris": ("#eceff4", "#5b6280"),
}
NOCHE = {
    "riel": "#2b2350", "riel_texto": "#b9b0e6", "fondo": "#17132b", "superficie": "#17132b", "tarjeta": "#221c3d",
    "superficie2": "#2a2349", "borde": "#2e2752", "texto": "#f1eefe", "tenue": "#9a93bf", "titulo": "#f1eefe",
    "acento": "#ff8a6b", "acento_h": "#ff9e84", "sobre_acento": "#3a1206", "resalte": "#ff8a6b", "sobre_resalte": "#3a1206",
    "promo": "#2e2752", "ok": "#8fe0b5", "error": "#ff9fb0", "aviso": "#f5d38a", "seleccion": "#2e2752",
    "e_azul": ("#4a2a24", "#ffb7a3"), "e_amarillo": ("#3a3320", "#f5d38a"), "e_verde": ("#1f3a2e", "#8fe0b5"),
    "e_rojo": ("#4a1f2a", "#ff9fb0"), "e_gris": ("#2a2349", "#b9b0e6"),
}
CLARO, OSCURO = DIA, NOCHE          # nombres anteriores

# Colores de cada estado de descarga (fondo, texto), igual que las etiquetas de la extensión
COLOR_ESTADO = {
    "detectado": "e_amarillo", "analizando": "e_azul", "pendiente": "e_amarillo", "descargando": "e_azul",
    "procesando": "e_amarillo", "completado": "e_verde", "cancelado": "e_gris", "error": "e_rojo",
}


def paleta(oscuro: bool) -> dict:
    return NOCHE if oscuro else DIA


def hoja_de_estilos(c: dict) -> str:
    estados = "\n".join(
        f'QLabel[estado="{e}"] {{ background: {c[k][0]}; color: {c[k][1]}; }}' for e, k in COLOR_ESTADO.items())
    return f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {c['texto']}; }}
QMainWindow {{ background: {c['riel']}; }}
QFrame#panel {{ background: {c['superficie']}; border-radius: 22px; }}
QWidget#pagina, QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget {{ background: {c['superficie']}; }}
QToolTip {{ background: {c['tarjeta']}; color: {c['texto']}; border: 1px solid {c['borde']}; padding: 4px 8px; }}

/* Riel de íconos: la sección activa se «encaja» en el panel */
QFrame#riel {{ background: transparent; border: none; }}
QLabel#logo {{ background: {c['resalte']}; border-radius: 14px; }}
QToolButton[nav="true"] {{ color: {c['riel_texto']}; background: transparent; border: none; font-size: 8.5pt; font-weight: 600;
                           border-top-left-radius: 16px; border-bottom-left-radius: 16px; padding: 8px 0 6px 0; }}
QToolButton[nav="true"]:hover {{ color: #ffffff; }}
QToolButton[nav="true"]:checked {{ background: {c['superficie']}; color: {c['acento']}; }}
QToolButton#tema {{ background: transparent; border: none; border-radius: 14px; padding: 6px; }}
QToolButton#tema:hover {{ background: rgba(255,255,255,0.14); }}

/* Títulos */
QLabel#titulo {{ font-size: 21pt; font-weight: 700; color: {c['titulo']}; }}
QLabel#subtitulo {{ color: {c['tenue']}; }}
QLabel[seccion="true"] {{ font-size: 11pt; font-weight: 700; }}
QLabel[tenue="true"] {{ color: {c['tenue']}; }}

/* Resumen de la cola (Descargando · En espera · Velocidad) */
QFrame#dato {{ background: {c['tarjeta']}; border-radius: 14px; }}
QFrame#dato[resaltado="true"] {{ background: {c['resalte']}; }}
QLabel#datoNum {{ font-size: 15pt; font-weight: 700; background: transparent; }}
QLabel#datoTxt {{ color: {c['tenue']}; font-size: 9pt; background: transparent; }}
QFrame#dato[resaltado="true"] QLabel {{ color: {c['sobre_resalte']}; }}

/* Tarjetas */
QFrame#tarjeta {{ background: {c['tarjeta']}; border: 1px solid transparent; border-radius: 18px; }}
QFrame#tarjeta:hover {{ border-color: {c['borde']}; }}
QFrame#caja {{ background: {c['tarjeta']}; border: none; border-radius: 20px; }}
QFrame#promo {{ background: {c['promo']}; border-radius: 20px; }}
QLabel#miniatura {{ background: {c['superficie2']}; border-radius: 12px; color: {c['tenue']}; font-size: 18pt; }}
QLabel#tituloTarjeta {{ font-weight: 700; font-size: 10.5pt; }}
QLabel#detalle {{ color: {c['tenue']}; font-size: 9pt; }}
QLabel#errorTexto {{ color: {c['error']}; font-size: 9pt; }}
QLabel[chip="true"] {{ border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 8.5pt; }}
{estados}
QLabel#codigo {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 34pt; font-weight: 700; letter-spacing: 4px;
                 color: {c['acento']}; background: {c['superficie']}; border-radius: 16px; padding: 12px 24px; }}
QLabel#paso {{ background: {c['acento']}; color: {c['sobre_acento']}; border-radius: 13px; font-weight: 700; min-width: 26px; max-width: 26px;
               min-height: 26px; max-height: 26px; qproperty-alignment: AlignCenter; }}

/* Progreso */
QProgressBar {{ background: {c['superficie2']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['acento']}; border-radius: 3px; }}

/* Botones (píldoras) */
QPushButton {{ background: {c['superficie2']}; border: 1px solid transparent; border-radius: 16px; padding: 7px 18px; font-weight: 600; }}
QPushButton:hover {{ border-color: {c['acento']}; }}
QPushButton:pressed {{ background: {c['seleccion']}; }}
QPushButton:disabled {{ color: {c['tenue']}; }}
QPushButton[primary="true"] {{ background: {c['acento']}; border-color: {c['acento']}; color: {c['sobre_acento']}; }}
QPushButton[primary="true"]:hover {{ background: {c['acento_h']}; }}
QPushButton[resalte="true"] {{ background: {c['resalte']}; border-color: {c['resalte']}; color: {c['sobre_resalte']}; }}
QPushButton[peligro="true"] {{ background: transparent; color: {c['error']}; border-color: {c['error']}; }}
QPushButton[filtro="true"] {{ border-radius: 14px; padding: 5px 15px; background: {c['tarjeta']}; border-color: transparent; color: {c['tenue']}; font-weight: 500; }}
QPushButton[filtro="true"]:checked {{ background: {c['acento']}; color: {c['sobre_acento']}; border-color: {c['acento']}; }}
QPushButton[enlace="true"] {{ border: none; background: transparent; color: {c['acento']}; padding: 2px 4px; }}
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {c['acento']}; }}

/* Campos */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ background: {c['superficie']}; border: 1px solid {c['borde']}; border-radius: 12px; padding: 7px 11px;
                                                  selection-background-color: {c['acento']}; selection-color: {c['sobre_acento']}; }}
QLineEdit#entradaUrl {{ font-size: 11pt; padding: 11px 16px; border-radius: 16px; background: {c['superficie']}; border-color: {c['borde']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{ background: {c['superficie']}; border: 1px solid {c['borde']}; selection-background-color: {c['seleccion']}; selection-color: {c['texto']}; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px; border: 1px solid {c['borde']}; background: {c['superficie']}; }}
QCheckBox::indicator:checked {{ background: {c['acento']}; border-color: {c['acento']}; }}
QGroupBox {{ border: none; border-radius: 20px; margin-top: 16px; padding: 18px 16px 12px 16px; background: {c['tarjeta']}; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 16px; padding: 0 4px; color: {c['texto']}; }}

/* Tablas */
QTableWidget {{ background: {c['tarjeta']}; border: none; border-radius: 16px; gridline-color: transparent; selection-background-color: {c['seleccion']};
                selection-color: {c['texto']}; alternate-background-color: {c['tarjeta']}; }}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {c['borde']}; }}
QHeaderView::section {{ background: {c['superficie2']}; color: {c['tenue']}; border: none; border-bottom: 1px solid {c['borde']}; padding: 8px; font-weight: 700; text-align: left; }}
QTableCornerButton::section {{ background: {c['superficie2']}; border: none; }}

/* Barras de desplazamiento */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['borde']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['tenue']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QStatusBar {{ background: {c['riel']}; color: {c['riel_texto']}; border: none; }}
QMessageBox, QDialog {{ background: {c['superficie']}; }}
"""
