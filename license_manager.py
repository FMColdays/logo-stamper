"""
Sistema de licencias para Logo Stamper.
Valida claves de activación contra Firebase Firestore (REST API).

CONFIGURACIÓN:
  1. Crea un proyecto en https://console.firebase.google.com
  2. Activa Firestore Database (modo producción)
  3. Copia el Project ID y el Web API Key aquí abajo
  4. Configura las reglas de Firestore (ver README)
"""
from __future__ import annotations
import json, os, time

try:
    import requests as _req
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ── CONFIGURA ESTOS DOS VALORES ───────────────────────────────────────────────
FIREBASE_PROJECT_ID = "logostamper-afddf"
FIREBASE_API_KEY    = "AIzaSyB1i171hVsIU-xSVYhB1UrqUJwiR9Ra6fE"
# ─────────────────────────────────────────────────────────────────────────────

COLLECTION   = "licenses"
CACHE_HOURS  = 24    # horas antes de re-validar con Firebase
GRACE_DAYS   = 7     # días sin internet antes de bloquear

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.json")


class LicenseResult:
    def __init__(self, valid: bool, message: str = "",
                 user_name: str = "", offline: bool = False):
        self.valid     = valid
        self.message   = message
        self.user_name = user_name
        self.offline   = offline


class LicenseManager:
    """Gestiona la licencia de activación de la aplicación."""

    def __init__(self):
        self._key:         str | None = None
        self._valid_until: float      = 0.0
        self._user_name:   str        = ""
        self._load()

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load(self):
        try:
            cfg = json.loads(open(CONFIG_PATH, encoding="utf-8").read())
            self._key          = cfg.get("license_key") or None
            self._valid_until  = float(cfg.get("license_valid_until", 0))
            self._user_name    = cfg.get("license_user", "")
        except Exception:
            pass

    def _save(self):
        cfg = {}
        try:
            cfg = json.loads(open(CONFIG_PATH, encoding="utf-8").read())
        except Exception:
            pass
        cfg["license_key"]          = self._key
        cfg["license_valid_until"]  = self._valid_until
        cfg["license_user"]         = self._user_name
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def save_key(self, key: str):
        """Guarda una nueva clave y fuerza re-validación."""
        self._key          = key.strip().upper()
        self._valid_until  = 0.0
        self._user_name    = ""
        self._save()

    def get_key(self) -> str | None:
        return self._key

    def get_user_name(self) -> str:
        return self._user_name

    def is_cached_valid(self) -> bool:
        """True si la caché de validación está vigente."""
        return bool(self._key) and time.time() < self._valid_until

    # ── Flujo de validación ───────────────────────────────────────────────────

    def check(self, force_online: bool = False) -> LicenseResult:
        """
        Flujo completo al iniciar la app:
          1. Sin clave guardada → pedir licencia
          2. Caché fresca y force_online=False → válido (sin llamada a red)
          3. Caché expirada o force_online=True → validar contra Firebase
          4. Sin internet pero caché reciente → periodo offline (GRACE_DAYS)
        """
        if not self._key:
            return LicenseResult(False,
                "Ingresa tu clave de licencia para continuar.")

        # Caché vigente (solo si no se fuerza validación online)
        if not force_online and self.is_cached_valid():
            return LicenseResult(True, "", self._user_name)

        # Validar online
        result = self._validate_online(self._key)

        if result.valid:
            self._valid_until = time.time() + CACHE_HOURS * 3600
            self._user_name   = result.user_name
            self._save()
            return result

        if result.offline:
            # Sin internet: ¿hay periodo de gracia disponible?
            grace_limit = self._valid_until + GRACE_DAYS * 86400
            if self._valid_until > 0 and time.time() < grace_limit:
                days_left = max(1, int((grace_limit - time.time()) / 86400))
                return LicenseResult(
                    True,
                    f"Sin conexión — modo offline ({days_left} día(s) restante(s))",
                    self._user_name, offline=True)
            return LicenseResult(
                False,
                "Sin conexión y el periodo offline expiró.\n"
                "Conecta a internet e inicia la app de nuevo.")

        # Clave revocada o inválida → limpiar caché
        self._valid_until = 0.0
        self._save()
        return result

    def validate_new_key(self, key: str) -> LicenseResult:
        """Valida una clave nueva ingresada por el usuario."""
        result = self._validate_online(key.strip().upper())
        if result.valid:
            self._key          = key.strip().upper()
            self._valid_until  = time.time() + CACHE_HOURS * 3600
            self._user_name    = result.user_name
            self._save()
        return result

    # ── Llamada a Firebase ────────────────────────────────────────────────────

    def check_revoked(self) -> bool:
        """
        Fuerza una validación en tiempo real contra Firebase (ignora caché).
        Devuelve True si la licencia fue REVOCADA (active=false).
        Devuelve False si sigue válida o si no hay internet (no interrumpe).
        """
        if not self._key:
            return True
        result = self._validate_online(self._key)
        if result.offline:
            return False   # Sin internet → no interrumpir
        if not result.valid:
            self._valid_until = 0.0
            self._save()
            return True    # Revocada
        # Actualizar caché
        self._valid_until = time.time() + CACHE_HOURS * 3600
        self._save()
        return False

    def _validate_online(self, key: str) -> LicenseResult:
        if not _REQUESTS_OK:
            return LicenseResult(False,
                "Falta la librería 'requests'.\nEjecuta: pip install requests")

        # Sin Firebase configurado → modo desarrollo (siempre válido)
        if not FIREBASE_PROJECT_ID or not FIREBASE_API_KEY:
            return LicenseResult(True, "", "Desarrollador")

        url = (
            f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
            f"/databases/(default)/documents/{COLLECTION}/{key}"
            f"?key={FIREBASE_API_KEY}"
        )
        try:
            r = _req.get(url, timeout=8)
        except Exception:
            return LicenseResult(False, "Sin conexión a internet.", offline=True)

        if r.status_code == 404:
            return LicenseResult(False, "Clave de licencia inválida.")
        if r.status_code != 200:
            return LicenseResult(False,
                f"Error del servidor (HTTP {r.status_code}).", offline=True)

        try:
            fields    = r.json().get("fields", {})
            active    = fields.get("active",    {}).get("booleanValue", True)
            user_name = fields.get("username", {}).get("stringValue",  "")
        except Exception:
            return LicenseResult(False,
                "Respuesta inesperada del servidor.", offline=True)

        if not active:
            return LicenseResult(False,
                "Tu licencia ha sido desactivada.\n"
                "Contacta al desarrollador para más información.")

        return LicenseResult(True, "", user_name)
