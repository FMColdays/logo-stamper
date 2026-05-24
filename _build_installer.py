"""
Construye LogoStamper y lo empaqueta en un instalador de Windows.
  · Paso 1 – Compila la app con PyInstaller  (se instala solo)
  · Paso 2 – Genera el script de Inno Setup
  · Paso 3 – Crea el instalador  (.exe listo para compartir)

Requisito externo: Inno Setup 6  (gratis, ~3 MB)
  https://jrsoftware.org/isdl.php
"""
import os, sys, shutil, subprocess, textwrap

# Forzar UTF-8 en la consola de Windows para que los caracteres especiales funcionen
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Configuración ─────────────────────────────────────────────────────────────
APP_NAME     = "LogoStamper"
APP_DISPLAY  = "Logo Stamper"
APP_VERSION  = "1.0"
APP_AUTHOR   = "Ritmo Son"

PROJ         = os.path.dirname(os.path.abspath(__file__))
DIST_APP     = os.path.join(PROJ, "_dist_app")
DIST_OUT     = os.path.join(PROJ, "_dist_installer")
BUILD_TMP    = os.path.join(PROJ, "_build_tmp")
ISS_PATH     = os.path.join(PROJ, "_installer_script.iss")

ISCC_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    r"C:\Program Files\Inno Setup 5\ISCC.exe",
]


def title(msg):
    line = "─" * 54
    print(f"\n{line}\n  {msg}\n{line}")


def ok(msg):  print(f"  ✓  {msg}")
def err(msg): print(f"  ✗  {msg}")
def info(msg):print(f"  ·  {msg}")


# ── Paso 0: ícono ─────────────────────────────────────────────────────────────
def prepare_icon():
    ico = os.path.join(PROJ, "app_icon.ico")
    png = os.path.join(PROJ, "app_icon.png")
    if not os.path.exists(ico) and os.path.exists(png):
        title("Generando app_icon.ico")
        try:
            from PIL import Image
            img = Image.open(png).convert("RGBA").resize((256, 256), Image.LANCZOS)
            img.save(ico, format="ICO",
                     sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
            ok("app_icon.ico generado")
        except Exception as e:
            info(f"No se pudo generar icono: {e}")
    return ico if os.path.exists(ico) else None


# ── Paso 1: compilar con PyInstaller ──────────────────────────────────────────
def build_app(ico_path):
    title("Compilando la aplicación  (puede tardar 3-6 min)")

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller", "--quiet"],
        check=True)

    if os.path.exists(DIST_APP):
        shutil.rmtree(DIST_APP)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--windowed",
        "--name",         APP_NAME,
        "--collect-all",  "customtkinter",
        "--collect-all",  "cv2",
        "--hidden-import","logo_placer",
        "--distpath",     DIST_APP,
        "--workpath",     BUILD_TMP,
        "--noconfirm",
        "--clean",
    ]
    if ico_path:
        cmd += ["--icon", ico_path]
    cmd.append(os.path.join(PROJ, "main.py"))

    result = subprocess.run(cmd, cwd=PROJ)
    if result.returncode != 0:
        err("PyInstaller terminó con error.")
        return False

    exe = os.path.join(DIST_APP, APP_NAME, f"{APP_NAME}.exe")
    if not os.path.exists(exe):
        err(f"No se encontró: {exe}")
        return False

    ok(f"Aplicación compilada → {exe}")
    return True


# ── Paso 2: generar script Inno Setup ─────────────────────────────────────────
def write_iss(ico_path):
    title("Generando script de instalador")

    app_src  = os.path.join(DIST_APP, APP_NAME)
    icon_line = f"SetupIconFile={ico_path}" if ico_path else ""

    iss = textwrap.dedent(f"""\
        [Setup]
        AppName={APP_DISPLAY}
        AppVersion={APP_VERSION}
        AppPublisher={APP_AUTHOR}
        AppId={{{{B3F2A1D0-7E4C-4B5A-9F8E-1234567890AB}}}}
        DefaultDirName={{autopf}}\\{APP_NAME}
        DefaultGroupName={APP_DISPLAY}
        AllowNoIcons=yes
        OutputDir={DIST_OUT}
        OutputBaseFilename={APP_NAME}_Instalador
        {icon_line}
        Compression=lzma
        SolidCompression=yes
        WizardStyle=modern
        PrivilegesRequired=lowest
        PrivilegesRequiredOverridesAllowed=dialog

        [Languages]
        Name: "spanish"; MessagesFile: "compiler:Languages\\Spanish.isl"

        [Tasks]
        Name: "desktopicon"; Description: "Crear acceso directo en el &Escritorio"; GroupDescription: "Iconos adicionales:"

        [Files]
        Source: "{app_src}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

        [Icons]
        Name: "{{group}}\\{APP_DISPLAY}"; Filename: "{{app}}\\{APP_NAME}.exe"
        Name: "{{group}}\\Desinstalar {APP_DISPLAY}"; Filename: "{{uninstallexe}}"
        Name: "{{commondesktop}}\\{APP_DISPLAY}"; Filename: "{{app}}\\{APP_NAME}.exe"; Tasks: desktopicon

        [Run]
        Filename: "{{app}}\\{APP_NAME}.exe"; Description: "Abrir {APP_DISPLAY} ahora"; Flags: nowait postinstall skipifsilent
    """)

    with open(ISS_PATH, "w", encoding="utf-8") as f:
        f.write(iss)
    ok(f"Script generado → {ISS_PATH}")


# ── Paso 3: compilar instalador con Inno Setup ────────────────────────────────
def compile_installer():
    title("Buscando Inno Setup")

    iscc = None
    for p in ISCC_PATHS:
        if os.path.exists(p):
            iscc = p
            break

    if not iscc:
        print("""
  ✗  Inno Setup no está instalado.

     Descárgalo GRATIS (un solo clic) desde:
     ► https://jrsoftware.org/isdl.php

     Instálalo y vuelve a correr este script.
     (La aplicación ya quedó compilada en _dist_app\\)
        """)
        return False

    ok(f"Encontrado: {iscc}")
    os.makedirs(DIST_OUT, exist_ok=True)

    title("Empaquetando instalador")
    result = subprocess.run([iscc, ISS_PATH])
    if result.returncode != 0:
        err("Inno Setup terminó con error.")
        return False

    installer = os.path.join(DIST_OUT, f"{APP_NAME}_Instalador.exe")
    if not os.path.exists(installer):
        err("No se encontró el instalador generado.")
        return False

    size_mb = os.path.getsize(installer) / 1_048_576
    print(f"""
╔══════════════════════════════════════════════════╗
║   ✓  ¡INSTALADOR LISTO PARA COMPARTIR!          ║
╚══════════════════════════════════════════════════╝

  Archivo : {installer}
  Tamaño  : {size_mb:.1f} MB

  Al instalarlo en otra PC:
    · Se instala en Archivos de Programa
    · Crea acceso directo en el Escritorio
    · Agrega entrada al Menú Inicio
    · Incluye desinstalador limpio
""")
    os.startfile(DIST_OUT)
    return True


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════╗
║        Creando instalador de Logo Stamper        ║
╚══════════════════════════════════════════════════╝""")

    ico  = prepare_icon()
    ok_build = build_app(ico)
    if not ok_build:
        input("\nPresiona Enter para salir...")
        sys.exit(1)

    write_iss(ico)
    ok_inst = compile_installer()

    input("\nPresiona Enter para salir...")
    sys.exit(0 if ok_inst else 1)
