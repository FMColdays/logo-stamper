# Logo Stamper

Herramienta de escritorio para aplicar marcas de agua (logos) a lotes de imágenes y subirlas directamente a Facebook.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Características

- **Marca de agua por lote** — procesa decenas o cientos de imágenes de una vez
- **Posición inteligente** — detecta automáticamente la esquina con menos contenido, o elige la posición manualmente en la cuadrícula 3×3
- **Posición personalizada por imagen** — arrastra el logo en la vista previa para colocarlo exactamente donde quieres
- **Vista previa en tiempo real** — zoom, paneo y arrastre del logo antes de procesar
- **Subida a Facebook** — sube las imágenes directamente a un álbum de tu página de Facebook desde la app
- **Logos recientes** — acceso rápido a los últimos 5 logos usados
- **Exportación flexible** — mantiene el formato original (JPEG, PNG…) o fuerza JPEG con calidad 95
- **Sufijo configurable** — nombra los archivos de salida como quieras (ej. `_logo`, `_marca`)
- **Instalador Windows** — genera un `.exe` listo para compartir con Inno Setup

---

## Requisitos

- Python 3.10 o superior
- Windows 10/11 (para el instalador; la app en sí corre en cualquier SO con Python)

### Dependencias Python

```
pip install -r requirements.txt
```

| Paquete | Uso |
|---|---|
| `customtkinter` | Interfaz gráfica moderna |
| `Pillow` | Procesamiento de imágenes |
| `opencv-python` | Detección de posición inteligente |
| `numpy` | Operaciones de array para CV |
| `requests` | Llamadas a la API de Facebook |

---

## Instalación y ejecución

### Opción A — Ejecutar desde el código fuente

```bash
git clone https://github.com/FMColdays/logo-stamper.git
cd logo-stamper
pip install -r requirements.txt
python main.py
```

### Opción B — Instalador Windows

1. Instala [Inno Setup 6](https://jrsoftware.org/isdl.php) (gratis)
2. Ejecuta el script de construcción:

```bash
python _build_installer.py
```

Se generará `LogoStamper_Instalador.exe` en la carpeta `_dist_installer/`.

---

## Uso

### Aplicar logo a imágenes

1. **Imágenes** — selecciona archivos sueltos, una carpeta completa, o arrastra y suelta
2. **Logo** — elige el archivo PNG (recomendado con fondo transparente)
3. **Tamaño y opacidad** — ajusta con los sliders
4. **Posición** — elige una celda de la cuadrícula o deja el modo Auto
5. **Carpeta de salida** — escribe un nombre o selecciona una carpeta existente
6. **Procesar** — haz clic en "✦ Procesar imágenes"

> **Tip:** Puedes arrastrar el logo en la vista previa para una posición personalizada imagen por imagen.

### Subir a Facebook

La app incluye un módulo para subir las imágenes procesadas directamente a una página de Facebook.

1. Haz clic en **"📤 Subir a Facebook"**
2. Inicia sesión con tu cuenta de Facebook (se abre el navegador)
3. Selecciona tu **Página de Facebook** en el dropdown
4. Elige el **álbum de destino** (existente) o crea uno nuevo
5. Selecciona la **carpeta** con las imágenes procesadas
6. Haz clic en **"Subir imágenes a Facebook"**

> La sesión se guarda localmente para no tener que iniciar sesión cada vez.

---

## Configuración de Facebook

La integración con Facebook usa la **Graph API v19** con autenticación OAuth 2.0.

### Requisitos para la subida a Facebook

- Una **App de Facebook** de tipo Business en [developers.facebook.com](https://developers.facebook.com)
- Permisos necesarios: `pages_manage_posts`, `pages_show_list`, `pages_read_engagement`
- El App ID está configurado en `facebook_uploader.py`

```python
FB_APP_ID = "tu_app_id_aqui"
```

> Para que la creación de álbumes funcione, la app de Facebook necesita tener
> **Acceso Avanzado** a `pages_manage_posts`, lo que requiere revisión por parte de Meta.
> Mientras tanto, puedes subir fotos a álbumes existentes sin restricciones.

---

## Estructura del proyecto

```
logo-stamper/
├── main.py                 # Aplicación principal (UI + lógica)
├── logo_placer.py          # Motor de marca de agua (CV + Pillow)
├── facebook_uploader.py    # Integración con Facebook Graph API
├── _build_installer.py     # Script para generar instalador Windows
├── requirements.txt        # Dependencias Python
├── app_icon.png            # Ícono de la aplicación
└── README.md
```

---

## Archivos ignorados por Git

Los siguientes archivos se generan automáticamente o contienen datos locales y **no se suben al repositorio**:

| Archivo / Carpeta | Motivo |
|---|---|
| `config.json` | Configuración local del usuario (rutas, preferencias) |
| `fb_session.json` | Token de sesión de Facebook |
| `_dist_app/` | App compilada por PyInstaller |
| `_dist_installer/` | Instalador `.exe` generado |
| `_build_tmp/` | Archivos temporales de compilación |
| `app_icon.ico` | Generado automáticamente desde `app_icon.png` |

---

## Autor

**FMColdays** · [github.com/FMColdays](https://github.com/FMColdays)
