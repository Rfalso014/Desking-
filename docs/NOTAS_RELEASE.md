> **Versión de prueba** (rama `web`). Se instala igual que cualquier otra, pero las instalaciones 1.x no se actualizan solas a ella.

## Novedades de la 2.0.0

- **Ahora es una web** que funciona en tu propio equipo (http://127.0.0.1:7878). `GestorDescargas.exe` es un panel pequeño para **encender, apagar y reiniciar** el gestor, con la opción «Encender con Windows».
- **Descargar ya o en grupo:** «Al grupo» junta enlaces en un grupo con nombre y los descarga todos con **Descargar grupo**, en una carpeta con su nombre.
- **En su propia carpeta o no:** elige si cada video va en su carpeta o suelto en Videos / Música.
- **Más sitios funcionan:** la extensión manda tu sesión del sitio solo para esa descarga (Vimeo, SharePoint, cursos…), los enlaces directos del reproductor cuando la página no se puede analizar, y se reintenta presentándose como Chrome en sitios con anti-bots.
- **Recortar 4 veces más rápido** (30 s de YouTube en ~6 s en vez de ~25 s).
- **Diseño reorganizado** en la página y la extensión, y un **modo oscuro más suave** para la vista.

**Importante si vienes de la 1.x:** después de instalar, en `chrome://extensions` pulsa **Actualizar** (↻) en la tarjeta de la extensión y acepta el permiso para leer los sitios. Luego vincúlala otra vez con el código de la página (Ajustes → Extensión del navegador).

## Instalar (Windows 10/11)

1. Descarga **`GestorDescargas-…-instalador.exe`** (abajo, en *Assets*).
2. Ábrelo con doble clic. No pide administrador ni Python: trae todo lo necesario (FFmpeg incluido).
   - Si aparece **«Windows protegió su PC»**: pulsa **Más información → Ejecutar de todas formas** (el programa no está firmado digitalmente).
3. Al terminar se enciende el gestor y se abre su página. En el menú Inicio quedan **Gestor de Descargas (encender o apagar)** y **Abrir la página del gestor**.

Para conectar la extensión de Chrome/Edge, sigue la guía del menú Inicio → *Gestor de Descargas* → «Guía de instalación».

¿Prefieres no instalar? Descarga **`GestorDescargas-…-portable.zip`**, descomprímelo y abre `GestorDescargas.exe`.

Para actualizar desde la 1.x, ejecuta este instalador encima: tus descargas, historial y ajustes se conservan.
