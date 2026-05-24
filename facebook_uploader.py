"""
Integración con Facebook Graph API.
  · OAuth 2.0 implicit flow (sin client secret — seguro para apps de escritorio)
  · Creación de álbumes en perfil personal o Página
  · Subida de fotos por carpeta con callback de progreso

CONFIGURACIÓN:
  Rellena FB_APP_ID con el App ID de tu Facebook App.
  Puedes conseguirlo en: https://developers.facebook.com
    → tu app → Configuración → Básica → App ID
"""
from __future__ import annotations
import json, os, threading, time, urllib.parse, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable

try:
    import requests as _req
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ── Helper de errores ─────────────────────────────────────────────────────────
def _fb_error_msg(err) -> str:
    """Extrae un mensaje legible del campo 'error' de la Graph API."""
    if not isinstance(err, dict):
        return str(err) or "Error desconocido"
    msg  = err.get("message")       # puede ser null
    user = err.get("error_user_msg")
    code = err.get("code", "?")
    typ  = err.get("type", "Error")
    if msg:
        return msg
    if user:
        return user
    return f"[{typ} #{code}]  {err}"


# ── Configuración ──────────────────────────────────────────────────────────────
FB_APP_ID     = "1656902272182775"
CALLBACK_PORT = 8765
REDIRECT_URI  = f"http://localhost:{CALLBACK_PORT}/callback"
SCOPE         = "public_profile,pages_show_list,pages_manage_posts,pages_read_engagement"
SESSION_FILE  = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fb_session.json")

# ── Página de éxito que recibe el token del URL fragment ─────────────────────
_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Logo Stamper</title>
<style>
  body{font-family:Arial,sans-serif;text-align:center;
       padding:60px 20px;background:#18191a;color:#e4e6eb}
  h2{font-size:26px;margin-bottom:12px}
  p{color:#b0b3b8;font-size:15px}
</style></head>
<body>
<h2 id="h" style="color:#1877f2">&#10003; &#161;Conectado a Facebook!</h2>
<p id="p">Puedes cerrar esta pesta&#241;a y volver a Logo Stamper.</p>
<script>
  var h  = window.location.hash.substring(1);
  var q  = window.location.search.substring(1);
  var p  = new URLSearchParams(h || q);
  var tk = p.get("access_token");
  var er = p.get("error_description");
  if (tk) {
    fetch("/token?t=" + encodeURIComponent(tk));
  } else if (er) {
    document.getElementById("h").textContent = "&#10007; Error de autorizaci&#243;n";
    document.getElementById("h").style.color = "#ff4444";
    document.getElementById("p").textContent = decodeURIComponent(er.replace(/\\+/g," "));
  }
</script>
</body></html>""".encode("utf-8")


# ── Servidor OAuth local ───────────────────────────────────────────────────────
class _OAuthServer(HTTPServer):
    access_token: str | None = None


class _OAuthHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # silenciar logs en consola

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs     = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/callback":
            # Servir la página HTML que lee el fragment y llama /token
            self.send_response(200)
            self.send_header("Content-Type",   "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_HTML)))
            self.end_headers()
            self.wfile.write(_HTML)

        elif parsed.path == "/token":
            token = qs.get("t", [None])[0]
            if token:
                self.server.access_token = token
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"OK")

        else:
            self.send_response(404)
            self.end_headers()


# ── Autenticación ──────────────────────────────────────────────────────────────
class FacebookAuth:
    """Gestiona el token de acceso de Facebook."""

    def __init__(self, app_id: str = ""):
        self.app_id     = app_id or FB_APP_ID
        self._token: str | None = None
        self._expiry: float     = 0.0
        self._name: str         = ""
        self._uid:  str         = ""
        self._load()

    # ── Persistencia ─────────────────────────────────────────────────────────
    def _load(self):
        try:
            d = json.loads(open(SESSION_FILE, encoding="utf-8").read())
            if d.get("expiry", 0) > time.time():
                self._token  = d["token"]
                self._expiry = d["expiry"]
                self._name   = d.get("name", "")
                self._uid    = d.get("uid",  "")
        except Exception:
            pass

    def _save(self, token: str, name: str = "", uid: str = "",
              expires_in: int = 5_184_000):          # 60 días por defecto
        self._token  = token
        self._expiry = time.time() + expires_in
        self._name   = name
        self._uid    = uid
        try:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump({"token": token, "expiry": self._expiry,
                           "name": name, "uid": uid}, f)
        except Exception:
            pass

    # ── Estado ───────────────────────────────────────────────────────────────
    def is_logged_in(self) -> bool:
        return bool(self._token) and time.time() < self._expiry

    def get_token(self) -> str | None:
        return self._token if self.is_logged_in() else None

    def get_user_name(self) -> str:
        return self._name

    def logout(self):
        self._token  = None
        self._expiry = 0.0
        self._name   = ""
        self._uid    = ""
        try:
            os.remove(SESSION_FILE)
        except Exception:
            pass

    # ── Flujo OAuth ───────────────────────────────────────────────────────────
    def login(
        self,
        on_success: Callable[[str, str], None],   # (token, nombre_usuario)
        on_error:   Callable[[str], None],
    ):
        """
        Abre el navegador con el diálogo de Facebook.
        Espera hasta 5 min a que el usuario autorice.
        Llama on_success o on_error en un hilo secundario.
        """
        if not self.app_id:
            on_error(
                "App ID de Facebook no configurado.\n"
                "Abre facebook_uploader.py y rellena FB_APP_ID.")
            return

        auth_url = (
            "https://www.facebook.com/dialog/oauth"
            f"?client_id={self.app_id}"
            f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
            f"&scope={SCOPE}"
            "&response_type=token"
            "&display=popup"
        )

        def _wait():
            # Iniciar servidor local
            try:
                srv = _OAuthServer(("localhost", CALLBACK_PORT), _OAuthHandler)
            except OSError:
                on_error(
                    f"El puerto {CALLBACK_PORT} está en uso.\n"
                    "Cierra otras instancias de la app e inténtalo de nuevo.")
                return

            webbrowser.open(auth_url)

            deadline = time.time() + 300          # 5 minutos
            while time.time() < deadline:
                srv.handle_request()
                if srv.access_token:
                    break

            srv.server_close()

            if not srv.access_token:
                on_error("Tiempo agotado. Cierra el navegador e inténtalo de nuevo.")
                return

            token = srv.access_token

            # Obtener nombre del usuario con el token recibido
            name = uid = ""
            if _REQUESTS_OK:
                try:
                    r = _req.get(
                        "https://graph.facebook.com/me",
                        params={"fields": "id,name", "access_token": token},
                        timeout=15)
                    d = r.json()
                    name = d.get("name", "")
                    uid  = d.get("id",   "")
                except Exception:
                    pass

            self._save(token, name, uid)
            on_success(token, name)

        threading.Thread(target=_wait, daemon=True).start()


# ── Subidor ────────────────────────────────────────────────────────────────────
class FacebookUploader:
    """Interactúa con la Graph API de Facebook."""

    BASE = "https://graph.facebook.com/v19.0"

    def __init__(self, auth: FacebookAuth):
        self.auth = auth

    def _require(self):
        if not _REQUESTS_OK:
            raise RuntimeError(
                "Falta la librería 'requests'.\n"
                "Ejecuta:  pip install requests")
        if not self.auth.get_token():
            raise RuntimeError("Sesión de Facebook expirada. Inicia sesión de nuevo.")

    def _get(self, path: str, token: str | None = None, **kw) -> dict:
        self._require()
        r = _req.get(
            f"{self.BASE}/{path}",
            params={"access_token": token or self.auth.get_token(), **kw},
            timeout=30)
        try:
            d = r.json()
        except ValueError:
            r.raise_for_status()
            return {}
        if "error" in d:
            raise RuntimeError(_fb_error_msg(d["error"]))
        r.raise_for_status()
        return d

    def _post(self, path: str, data: dict | None = None,
              files=None, token: str | None = None) -> dict:
        self._require()
        d = {"access_token": token or self.auth.get_token(), **(data or {})}
        r = _req.post(f"{self.BASE}/{path}", data=d, files=files, timeout=120)
        try:
            rd = r.json()
        except ValueError:
            r.raise_for_status()
            return {}
        if "error" in rd:
            raise RuntimeError(_fb_error_msg(rd["error"]))
        r.raise_for_status()
        return rd

    # ── Páginas / usuario ─────────────────────────────────────────────────────
    def get_me(self) -> dict:
        return self._get("me", fields="id,name")

    def get_pages(self) -> list[dict]:
        """Lista de páginas que administra el usuario (incluye page token)."""
        d = self._get("me/accounts", fields="id,name,access_token")
        return d.get("data", [])

    # ── Álbumes ───────────────────────────────────────────────────────────────
    def get_albums(self, target_id: str = "me",
                   token: str | None = None) -> list[dict]:
        d = self._get(f"{target_id}/albums", token=token,
                      fields="id,name,count", limit=50)
        return d.get("data", [])

    def create_album(self, target_id: str, name: str,
                     description: str = "",
                     token: str | None = None) -> str:
        """Crea un álbum y devuelve su ID."""
        result = self._post(
            f"{target_id}/albums",
            data={"name": name, "description": description},
            token=token)
        album_id = result.get("id")
        if not album_id:
            raise RuntimeError(
                f"No se pudo crear el álbum — respuesta inesperada: {result}")
        return str(album_id)

    # ── Fotos ─────────────────────────────────────────────────────────────────
    def upload_photo(self, album_id: str, image_path: str,
                     caption: str = "",
                     token: str | None = None) -> str:
        """Sube una foto y devuelve su ID."""
        with open(image_path, "rb") as f:
            result = self._post(
                f"{album_id}/photos",
                data={"caption": caption},
                files={"source": (os.path.basename(image_path), f, "image/jpeg")},
                token=token)
        return result.get("id", "")

    def upload_folder(
        self,
        album_id:    str,
        folder_path: str,
        caption:     str = "",
        progress_cb: Callable[[int, int, str], None] | None = None,
        stop_evt:    threading.Event | None = None,
        token:       str | None = None,
    ) -> tuple[int, int]:
        """
        Sube todas las imágenes JPEG/PNG de una carpeta.

        Si album_id es un page_id, las fotos se suben directamente a la página.
        progress_cb(n_ya_subidas, total, nombre_archivo_actual)
        Devuelve (subidas_exitosas, total_encontradas).
        """
        exts  = {".jpg", ".jpeg", ".png", ".webp"}
        files = sorted(
            f for f in os.listdir(folder_path)
            if os.path.splitext(f.lower())[1] in exts)

        total    = len(files)
        uploaded = 0

        for i, fname in enumerate(files):
            if stop_evt and stop_evt.is_set():
                break
            if progress_cb:
                progress_cb(i, total, fname)
            try:
                self.upload_photo(album_id,
                                  os.path.join(folder_path, fname),
                                  caption=caption,
                                  token=token)
                uploaded += 1
            except Exception as exc:
                # Notificar el error pero continuar con el resto
                if progress_cb:
                    progress_cb(i, total, f"✗ {fname}: {exc}")

        if progress_cb:
            progress_cb(total, total, "")

        return uploaded, total

    # ── Post multi-foto (alternativa a álbum vía API) ─────────────────────────
    def upload_photo_unpublished(self, page_id: str, image_path: str,
                                  token: str | None = None) -> str:
        """Sube una foto sin publicar y devuelve su ID para adjuntarla a un post."""
        with open(image_path, "rb") as f:
            result = self._post(
                f"{page_id}/photos",
                data={"published": "false"},
                files={"source": (os.path.basename(image_path), f, "image/jpeg")},
                token=token)
        return result.get("id", "")

    def create_album_post(self, page_id: str, photo_ids: list[str],
                           caption: str = "",
                           token: str | None = None) -> str:
        """Crea un post con múltiples fotos (hasta 30) en la página."""
        import json as _json
        attached = _json.dumps([{"media_fbid": pid} for pid in photo_ids])
        result = self._post(
            f"{page_id}/feed",
            data={"message": caption, "attached_media": attached},
            token=token)
        return result.get("id", "")

    def upload_folder_as_post(
        self,
        page_id:     str,
        folder_path: str,
        caption:     str = "",
        progress_cb: Callable[[int, int, str], None] | None = None,
        stop_evt:    threading.Event | None = None,
        token:       str | None = None,
        batch_size:  int = 10,
    ) -> tuple[int, int]:
        """
        Sube todas las imágenes de una carpeta como post(s) multi-foto en la página.
        Si hay más de batch_size fotos crea varios posts numerados.
        Devuelve (subidas_exitosas, total_encontradas).
        """
        exts  = {".jpg", ".jpeg", ".png", ".webp"}
        files = sorted(
            f for f in os.listdir(folder_path)
            if os.path.splitext(f.lower())[1] in exts)

        total     = len(files)
        photo_ids: list[str] = []

        # ── Paso 1: subir cada foto sin publicar ──────────────────────────────
        for i, fname in enumerate(files):
            if stop_evt and stop_evt.is_set():
                break
            if progress_cb:
                progress_cb(i, total, fname)
            try:
                pid = self.upload_photo_unpublished(
                    page_id, os.path.join(folder_path, fname), token=token)
                if pid:
                    photo_ids.append(pid)
            except Exception as exc:
                if progress_cb:
                    progress_cb(i, total, f"✗ {fname}: {exc}")

        if not photo_ids:
            if progress_cb:
                progress_cb(total, total, "")
            return 0, total

        # ── Paso 2: publicar en lotes ─────────────────────────────────────────
        batches   = [photo_ids[i:i + batch_size]
                     for i in range(0, len(photo_ids), batch_size)]
        n_batches = len(batches)

        for bi, batch in enumerate(batches):
            if stop_evt and stop_evt.is_set():
                break
            lote_txt = (f"  ({bi + 1}/{n_batches})" if n_batches > 1 else "")
            if progress_cb:
                progress_cb(total, total,
                            f"Publicando lote {bi + 1}/{n_batches}…")
            try:
                self.create_album_post(
                    page_id, batch, caption + lote_txt, token=token)
            except Exception as exc:
                if progress_cb:
                    progress_cb(total, total,
                                f"✗ Error al publicar lote {bi + 1}: {exc}")

        if progress_cb:
            progress_cb(total, total, "")

        return len(photo_ids), total
