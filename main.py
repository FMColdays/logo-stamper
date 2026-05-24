from __future__ import annotations
import json
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageTk

# ── Drag & drop (opcional) ───────────────────────────────────────────────────
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _AppBase = type("_AppBase", (ctk.CTk, TkinterDnD.DnDWrapper), {})
    _DND = True
except Exception:
    _AppBase = ctk.CTk
    _DND = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
IMAGE_EXTS  = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff"}
CANVAS_BG   = "#1e1e1e"
THUMB_H     = 76   # altura de la barra de miniaturas

_POS_SYMBOLS = [["↖", "↑", "↗"], ["←", "·", "→"], ["↙", "↓", "↘"]]
_POS_NAMES   = [
    ["top-left",    "top-center",    "top-right"],
    ["mid-left",    "center",        "mid-right"],
    ["bottom-left", "bottom-center", "bottom-right"],
]


class App(_AppBase):
    def __init__(self):
        super().__init__()
        if _DND:
            self.TkdndVersion = TkinterDnD._require(self)

        self.title("Logo Stamper")
        self.geometry("1030x740")
        self.minsize(820, 620)

        # ── Estado principal ─────────────────────────────────────────────────
        self.images: list[str]         = []
        self.logo_path: str | None     = None
        self.output_folder: str | None = None
        self.forced_pos: str | None    = None
        self._last_output: str | None  = None
        self._preview_idx   = 0
        self._preview_timer = None

        # Posición personalizada POR IMAGEN {ruta: (fx, fy)} normalizada 0-1
        self._logo_positions: dict[str, tuple[float, float]] = {}

        # ── Estado del canvas ────────────────────────────────────────────────
        self._canvas_img_x0   = 0
        self._canvas_img_y0   = 0
        self._canvas_scale    = 1.0
        self._canvas_base_wh  = (0, 0)
        self._canvas_logo_pos = (0, 0)
        self._canvas_logo_wh  = (0, 0)
        self._canvas_bg_item  = None
        self._canvas_logo_item   = None
        self._canvas_logo_border = None
        self._tk_bg_photo    = None
        self._tk_logo_photo  = None

        # Drag logo / pan fondo
        self._drag_mode: str | None            = None  # "logo" | "pan"
        self._drag_start: tuple | None         = None
        self._drag_logo_origin: tuple | None   = None
        self._pan_delta                        = [0, 0]

        # Zoom / pan
        self._zoom_level = 1.0
        self._pan_offset = [0, 0]
        self._stored_preview_data: tuple | None = None

        # Miniaturas
        self._thumb_size   = 56
        self._thumb_photos: list = []
        self._thumb_pil:    list = []

        # Logos recientes (se cargan desde config)
        self._recent_logos: list[str] = []
        self._recent_thumb_photos: list = []   # evitar GC de PhotoImages

        # Ícono de la ventana
        self._icon_photo = None

        self._build_ui()
        self._load_config()
        self._update_license_label()            # muestra quién tiene licencia activa
        self._set_window_icon(self.logo_path)   # ícono: logo guardado o app_icon.png
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Monitor de licencia: verifica en Firebase cada 5 minutos
        self._license_monitor_id = None
        self._schedule_license_monitor()

        self.bind("<Left>",  lambda e: self._kb_navigate(-1))
        self.bind("<Right>", lambda e: self._kb_navigate(+1))

    # ════════════════════════════════════════════════════════════════════════
    #  CONSTRUCCIÓN DE LA INTERFAZ
    # ════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Panel izquierdo ──────────────────────────────────────────────────
        left = ctk.CTkScrollableFrame(self, width=315)
        left.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)

        r = 0
        ctk.CTkLabel(left, text="Logo Stamper",
                     font=ctk.CTkFont(size=21, weight="bold")).grid(
            row=r, column=0, pady=(12, 16)); r += 1

        # ── 1. Imágenes ──────────────────────────────────────────────────────
        self._section_label(left, "1. Imágenes", row=r); r += 1

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.grid(row=r, column=0, padx=12, pady=(0, 4), sticky="ew")
        btn_row.grid_columnconfigure((0, 1), weight=1); r += 1
        ctk.CTkButton(btn_row, text="Archivos",
                      command=self._pick_images).grid(
            row=0, column=0, sticky="ew", padx=(0, 3))
        ctk.CTkButton(btn_row, text="Carpeta",
                      command=self._pick_images_folder).grid(
            row=0, column=1, sticky="ew", padx=(3, 3))
        ctk.CTkButton(btn_row, text="✕", width=32,
                      fg_color="transparent", border_width=1,
                      command=self._clear_images).grid(row=0, column=2)

        dnd_hint = "  (o arrastra aquí)" if _DND else ""
        self.lbl_images = ctk.CTkLabel(
            left, text=f"0 imágenes{dnd_hint}", text_color="gray")
        self.lbl_images.grid(row=r, column=0, padx=12, sticky="w"); r += 1

        # ── 2. Logo ──────────────────────────────────────────────────────────
        self._section_label(left, "2. Logo (PNG recomendado)", row=r); r += 1
        ctk.CTkButton(left, text="Seleccionar logo",
                      command=self._pick_logo).grid(
            row=r, column=0, padx=12, pady=(0, 4), sticky="ew"); r += 1
        self.lbl_logo = ctk.CTkLabel(
            left, text="Sin logo seleccionado", text_color="gray")
        self.lbl_logo.grid(row=r, column=0, padx=12, sticky="w"); r += 1

        # Logos recientes (el label y el frame se ocultan cuando no hay ninguno)
        self._recent_lbl = ctk.CTkLabel(left, text="Recientes:",
                     font=ctk.CTkFont(size=11), text_color="gray")
        self._recent_lbl.grid(row=r, column=0, padx=12, pady=(6, 0), sticky="w"); r += 1
        self._recent_frame = ctk.CTkFrame(left, fg_color="transparent")
        self._recent_frame.grid(row=r, column=0, padx=12, pady=(0, 4), sticky="ew")
        self._recent_frame.grid_columnconfigure(0, weight=1); r += 1

        # Tamaño
        ctk.CTkLabel(left, text="Tamaño del logo:").grid(
            row=r, column=0, padx=12, pady=(8, 0), sticky="w"); r += 1
        self.slider_size = ctk.CTkSlider(
            left, from_=5, to=40, number_of_steps=35,
            command=self._on_size_change)
        self.slider_size.set(15)
        self.slider_size.grid(row=r, column=0, padx=12, sticky="ew"); r += 1
        self.lbl_size = ctk.CTkLabel(left, text="15% del ancho")
        self.lbl_size.grid(row=r, column=0, padx=12, sticky="w"); r += 1

        # Opacidad
        ctk.CTkLabel(left, text="Opacidad del logo:").grid(
            row=r, column=0, padx=12, pady=(8, 0), sticky="w"); r += 1
        self.slider_opacity = ctk.CTkSlider(
            left, from_=10, to=100, number_of_steps=18,
            command=self._on_opacity_change)
        self.slider_opacity.set(80)
        self.slider_opacity.grid(row=r, column=0, padx=12, sticky="ew"); r += 1
        self.lbl_opacity = ctk.CTkLabel(left, text="80% de opacidad")
        self.lbl_opacity.grid(row=r, column=0, padx=12, sticky="w"); r += 1

        # ── 3. Posición del logo ─────────────────────────────────────────────
        r = self._build_position_grid(left, r)

        # ── 4. Carpeta de salida ─────────────────────────────────────────────
        self._section_label(left, "4. Carpeta de salida", row=r); r += 1

        folder_row = ctk.CTkFrame(left, fg_color="transparent")
        folder_row.grid(row=r, column=0, padx=12, pady=(0, 2), sticky="ew")
        folder_row.grid_columnconfigure(0, weight=1); r += 1
        self.entry_folder = ctk.CTkEntry(
            folder_row, placeholder_text="Nombre de carpeta nueva…")
        self.entry_folder.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(folder_row, text="Buscar", width=68,
                      command=self._pick_folder).grid(row=0, column=1)

        self.lbl_folder = ctk.CTkLabel(
            left, text="Se creará junto a la primera imagen",
            text_color="gray", wraplength=285)
        self.lbl_folder.grid(row=r, column=0, padx=12, sticky="w"); r += 1

        # Sufijo
        ctk.CTkLabel(left, text="Sufijo en nombre de salida:").grid(
            row=r, column=0, padx=12, pady=(8, 0), sticky="w"); r += 1
        self.entry_suffix = ctk.CTkEntry(
            left,
            placeholder_text='ej: _logo  →  foto_logo.jpg  (vacío = mismo nombre)')
        self.entry_suffix.grid(
            row=r, column=0, padx=12, pady=(0, 4), sticky="ew"); r += 1

        # Exportar siempre como JPEG
        jpeg_row = ctk.CTkFrame(left, fg_color="transparent")
        jpeg_row.grid(row=r, column=0, padx=12, pady=(4, 6), sticky="ew"); r += 1
        self.switch_jpeg = ctk.CTkSwitch(jpeg_row, text="Exportar siempre como JPEG")
        self.switch_jpeg.grid(row=0, column=0, sticky="w")

        # ── Botones de acción ────────────────────────────────────────────────
        self.btn_process = ctk.CTkButton(
            left, text="✦  Procesar imágenes",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=46, command=self._start_processing)
        self.btn_process.grid(
            row=r, column=0, padx=12, pady=(14, 6), sticky="ew"); r += 1

        self.progress = ctk.CTkProgressBar(left)
        self.progress.set(0)
        self.progress.grid(row=r, column=0, padx=12, sticky="ew"); r += 1

        self.lbl_status = ctk.CTkLabel(
            left, text="", text_color="gray", wraplength=285)
        self.lbl_status.grid(
            row=r, column=0, padx=12, pady=(3, 4), sticky="w"); r += 1

        self.btn_open = ctk.CTkButton(
            left, text="📂  Abrir carpeta de salida",
            fg_color="transparent", border_width=1,
            state="disabled", command=self._open_output)
        self.btn_open.grid(
            row=r, column=0, padx=12, pady=(2, 4), sticky="ew"); r += 1

        ctk.CTkButton(
            left, text="📤  Subir a Facebook",
            fg_color="transparent", border_width=1,
            command=self._open_facebook_window).grid(
            row=r, column=0, padx=12, pady=(0, 6), sticky="ew"); r += 1

        # ── Info de licencia activa ──────────────────────────────────────────
        ctk.CTkFrame(left, height=1, fg_color="#2a2a2a").grid(
            row=r, column=0, padx=8, pady=(4, 0), sticky="ew"); r += 1

        self._lbl_license = ctk.CTkLabel(
            left, text="🔑 Verificando licencia…",
            text_color="gray", font=ctk.CTkFont(size=10),
            anchor="w", cursor="hand2")
        self._lbl_license.grid(
            row=r, column=0, padx=12, pady=(4, 12), sticky="ew"); r += 1
        self._lbl_license.bind("<Button-1>", lambda e: self._show_license_info())

        # ── Panel derecho ────────────────────────────────────────────────────
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # Barra superior (←  Vista previa  →)
        top_bar = ctk.CTkFrame(right, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        top_bar.grid_columnconfigure(1, weight=1)

        self.btn_prev = ctk.CTkButton(
            top_bar, text="←", width=36, height=30,
            fg_color="transparent", border_width=1,
            command=self._prev_preview, state="disabled")
        self.btn_prev.grid(row=0, column=0, padx=(0, 6))

        ctk.CTkLabel(top_bar, text="Vista previa",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=1)

        self.btn_next = ctk.CTkButton(
            top_bar, text="→", width=36, height=30,
            fg_color="transparent", border_width=1,
            command=self._next_preview, state="disabled")
        self.btn_next.grid(row=0, column=2, padx=(6, 0))

        self.lbl_preview_idx = ctk.CTkLabel(
            right, text="", text_color="gray", font=ctk.CTkFont(size=11))
        self.lbl_preview_idx.grid(row=1, column=0, pady=(2, 0))

        # Canvas principal
        self.canvas = tk.Canvas(
            right, bg=CANVAS_BG, highlightthickness=0, cursor="")
        self.canvas.grid(row=2, column=0, sticky="nsew", padx=10, pady=(8, 4))

        hint = "Selecciona imágenes y logo,\nluego presiona «Ver vista previa»"
        if _DND:
            hint += "\n\nArrastra imágenes directamente aquí"
        hint += "\n\nScroll = zoom  ·  Arrastra fondo = mover  ·  Doble-clic = reset zoom"
        self._hint_id = self.canvas.create_text(
            300, 200, text=hint, fill="#505050",
            font=("Segoe UI", 11), justify="center", tags="hint")

        # Barra de miniaturas
        self.thumb_canvas = tk.Canvas(
            right, height=THUMB_H, bg="#161616", highlightthickness=0)
        self.thumb_canvas.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 6))

        # Scrollbar horizontal para miniaturas (oculta si no hace falta)
        self._thumb_xsb = tk.Scrollbar(
            right, orient="horizontal", command=self.thumb_canvas.xview)
        self.thumb_canvas.configure(xscrollcommand=self._thumb_xsb.set)

        # Eventos del canvas principal
        self.canvas.bind("<Configure>",       self._on_canvas_resize)
        self.canvas.bind("<Motion>",          self._on_canvas_motion)
        self.canvas.bind("<ButtonPress-1>",   self._on_canvas_press)
        self.canvas.bind("<B1-Motion>",       self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<MouseWheel>",      self._on_canvas_wheel)
        self.canvas.bind("<Double-Button-1>", self._on_canvas_double_click)

        # Miniaturas
        self.thumb_canvas.bind("<Button-1>", self._on_thumb_click)

        # Drop target
        if _DND:
            self.canvas.drop_target_register(DND_FILES)
            self.canvas.dnd_bind("<<Drop>>", self._on_drop)
            self.lbl_images.drop_target_register(DND_FILES)
            self.lbl_images.dnd_bind("<<Drop>>", self._on_drop)

    # ── Sección 3: cuadrícula de posición ────────────────────────────────────

    def _build_position_grid(self, parent, row: int) -> int:
        self._section_label(parent, "3. Posición del logo", row=row); row += 1

        # Fila 1: indicador de modo  +  ↺ Esta imagen
        row1 = ctk.CTkFrame(parent, fg_color="transparent")
        row1.grid(row=row, column=0, padx=12, pady=(0, 2), sticky="ew")
        row1.grid_columnconfigure(0, weight=1); row += 1

        self._auto_lbl = ctk.CTkLabel(
            row1, text="● Auto  (inteligente)", text_color="#4CAF50")
        self._auto_lbl.grid(row=0, column=0, sticky="w")

        self.btn_reset_pos = ctk.CTkButton(
            row1, text="↺ Esta imagen", width=110, height=26,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=11),
            state="disabled", command=self._reset_position)
        self.btn_reset_pos.grid(row=0, column=1, padx=(6, 0))

        # Fila 2: ↺ Resetear todas  +  → Aplicar a todas
        row2 = ctk.CTkFrame(parent, fg_color="transparent")
        row2.grid(row=row, column=0, padx=12, pady=(0, 2), sticky="ew")
        row2.grid_columnconfigure((0, 1), weight=1); row += 1

        self.btn_reset_all = ctk.CTkButton(
            row2, text="↺ Resetear todas", height=26,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=11),
            state="disabled", command=self._reset_all_positions)
        self.btn_reset_all.grid(row=0, column=0, sticky="ew", padx=(0, 3))

        self.btn_apply_all = ctk.CTkButton(
            row2, text="→ Aplicar a todas", height=26,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=11),
            state="disabled", command=self._apply_pos_to_all)
        self.btn_apply_all.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        grid_f = ctk.CTkFrame(parent)
        grid_f.grid(row=row, column=0, padx=14, pady=(6, 2)); row += 1

        self._pos_btns: dict[str, ctk.CTkButton] = {}
        for ri, (sym_row, name_row) in enumerate(zip(_POS_SYMBOLS, _POS_NAMES)):
            for ci, (sym, name) in enumerate(zip(sym_row, name_row)):
                btn = ctk.CTkButton(
                    grid_f, text=sym, width=46, height=46,
                    font=ctk.CTkFont(size=18),
                    fg_color="transparent", border_width=1,
                    command=lambda n=name: self._toggle_pos(n))
                btn.grid(row=ri, column=ci, padx=2, pady=2)
                self._pos_btns[name] = btn

        return row

    # ════════════════════════════════════════════════════════════════════════
    #  POSICIÓN — ACCIONES
    # ════════════════════════════════════════════════════════════════════════

    def _toggle_pos(self, name: str):
        if self.forced_pos == name:
            self._pos_btns[name].configure(fg_color="transparent")
            self.forced_pos = None
        else:
            if self.forced_pos and self.forced_pos in self._pos_btns:
                self._pos_btns[self.forced_pos].configure(fg_color="transparent")
            self._pos_btns[name].configure(fg_color=("#1565c0", "#1e88e5"))
            self.forced_pos = name
        self._update_pos_indicator()
        self._schedule_auto_preview()

    def _reset_position(self):
        """Borra la posición personalizada SOLO de la imagen actual."""
        if self.images:
            path = self.images[self._preview_idx]
            self._logo_positions.pop(path, None)
        self._update_pos_indicator()
        self._draw_thumbstrip()
        self._schedule_auto_preview()

    def _reset_all_positions(self):
        """Borra las posiciones personalizadas de TODAS las imágenes."""
        count = len(self._logo_positions)
        self._logo_positions.clear()
        self._update_pos_indicator()
        self._draw_thumbstrip()
        self._schedule_auto_preview()
        self._set_status(
            f"↺  Posición reseteada en {count} imagen(es) → vuelven a Auto.")

    def _apply_pos_to_all(self):
        """Copia la posición de la imagen actual a todas las demás."""
        if not self.images:
            return
        path = self.images[self._preview_idx]
        pos  = self._logo_positions.get(path)
        if pos is None:
            self._set_status("La imagen actual no tiene posición personalizada.", error=True)
            return
        for p in self.images:
            self._logo_positions[p] = pos
        self._update_pos_indicator()
        self._draw_thumbstrip()
        self._set_status(
            f"→  Posición aplicada a las {len(self.images)} imágenes.")

    def _update_pos_indicator(self):
        path       = self.images[self._preview_idx] if self.images else None
        has_custom = path in self._logo_positions if path else False
        any_custom = bool(self._logo_positions)   # hay al menos una con posición manual

        if has_custom:
            self._auto_lbl.configure(
                text="✏  Posición personalizada", text_color="#FF9800")
            self.btn_reset_pos.configure(state="normal")
            self.btn_apply_all.configure(state="normal")
        elif self.forced_pos:
            self._auto_lbl.configure(
                text="○ Auto  (desactivado)", text_color="gray")
            self.btn_reset_pos.configure(state="disabled")
            self.btn_apply_all.configure(state="disabled")
        else:
            self._auto_lbl.configure(
                text="● Auto  (inteligente)", text_color="#4CAF50")
            self.btn_reset_pos.configure(state="disabled")
            self.btn_apply_all.configure(state="disabled")

        # "Resetear todas" se activa si hay CUALQUIER posición manual, no solo la actual
        self.btn_reset_all.configure(state="normal" if any_custom else "disabled")

    # ════════════════════════════════════════════════════════════════════════
    #  LOGOS RECIENTES
    # ════════════════════════════════════════════════════════════════════════

    def _add_recent_logo(self, path: str):
        if path in self._recent_logos:
            self._recent_logos.remove(path)
        self._recent_logos.insert(0, path)
        self._recent_logos = self._recent_logos[:5]
        self._refresh_recent_ui()

    def _refresh_recent_ui(self):
        for w in self._recent_frame.winfo_children():
            w.destroy()
        self._recent_thumb_photos = []   # resetear refs

        self._recent_frame.grid_columnconfigure(1, weight=1)

        if not self._recent_logos:
            # Ocultar sección completa cuando no hay logos recientes
            self._recent_lbl.grid_remove()
            self._recent_frame.grid_remove()
            return

        # Mostrar sección si estaba oculta
        self._recent_lbl.grid()
        self._recent_frame.grid()

        for i, path in enumerate(self._recent_logos):
            exists = os.path.exists(path)
            name   = os.path.basename(path)
            if len(name) > 22:
                name = name[:19] + "…"

            # ── Miniatura ──────────────────────────────────────────────────
            photo = None
            if exists:
                try:
                    img   = Image.open(path).convert("RGBA")
                    img.thumbnail((38, 38), Image.LANCZOS)
                    # Fondo oscuro para logos con transparencia
                    bg    = Image.new("RGB", (38, 38), "#2b2b2b")
                    bg.paste(img, ((38 - img.width) // 2,
                                   (38 - img.height) // 2), img)
                    photo = ImageTk.PhotoImage(bg)
                except Exception:
                    photo = None
            self._recent_thumb_photos.append(photo)

            thumb_lbl = tk.Label(
                self._recent_frame,
                image=photo if photo else "",
                bg="#2b2b2b",
                width=38, height=38,
                relief="flat", cursor="hand2")
            thumb_lbl.grid(row=i, column=0, padx=(0, 4), pady=2)
            thumb_lbl.bind("<Button-1>", lambda e, p=path: self._select_recent_logo(p))

            # ── Botón con nombre ───────────────────────────────────────────
            ctk.CTkButton(
                self._recent_frame,
                text=name,
                height=38,
                anchor="w",
                font=ctk.CTkFont(size=10),
                fg_color="transparent",
                border_width=1,
                text_color="white" if exists else "gray",
                command=lambda p=path: self._select_recent_logo(p)
            ).grid(row=i, column=1, sticky="ew", pady=2)

            # ── Botón eliminar ─────────────────────────────────────────────
            ctk.CTkButton(
                self._recent_frame,
                text="✕",
                width=28, height=38,
                fg_color="transparent",
                border_width=0,
                text_color="#888888",
                hover_color="#3a3a3a",
                font=ctk.CTkFont(size=12),
                command=lambda p=path: self._remove_recent_logo(p)
            ).grid(row=i, column=2, padx=(2, 0), pady=2)

    def _select_recent_logo(self, path: str):
        if not os.path.exists(path):
            self._set_status(
                f"El logo ya no existe: {os.path.basename(path)}", error=True)
            return
        self.logo_path = path
        self.lbl_logo.configure(text=os.path.basename(path), text_color="white")
        self._add_recent_logo(path)
        self._set_window_icon(path)
        self._trigger_preview_soon()

    def _remove_recent_logo(self, path: str):
        """Elimina un logo de la lista de recientes."""
        if path in self._recent_logos:
            self._recent_logos.remove(path)
        self._refresh_recent_ui()

    # ════════════════════════════════════════════════════════════════════════
    #  ÍCONO DE LA VENTANA
    # ════════════════════════════════════════════════════════════════════════

    def _set_window_icon(self, path: str | None = None):
        """
        Establece el ícono de la ventana.
        Prioridad: path explícito → app_icon.png/ico en la carpeta del proyecto.
        """
        proj = os.path.dirname(os.path.abspath(__file__))
        candidates: list[str] = []
        if path and os.path.exists(path):
            candidates.append(path)
        for name in ("app_icon.png", "app_icon.ico", "app_icon.jpg"):
            p = os.path.join(proj, name)
            if os.path.exists(p):
                candidates.append(p)
        for p in candidates:
            try:
                img   = Image.open(p).resize((64, 64), Image.LANCZOS).convert("RGBA")
                photo = ImageTk.PhotoImage(img)
                self.iconphoto(True, photo)
                self._icon_photo = photo   # evitar GC
                return
            except Exception:
                continue

    # ════════════════════════════════════════════════════════════════════════
    #  AUTO-PREVIEW (debounce)
    # ════════════════════════════════════════════════════════════════════════

    def _trigger_preview_soon(self):
        """Dispara la vista previa casi inmediatamente (sin logo también)."""
        if self.images:
            if self._preview_timer:
                self.after_cancel(self._preview_timer)
            self._preview_timer = self.after(180, self._update_preview)

    def _schedule_auto_preview(self, _=None):
        if not self.images:
            return
        if self._preview_timer:
            self.after_cancel(self._preview_timer)
        self._preview_timer = self.after(900, self._update_preview)

    def _on_size_change(self, v):
        self.lbl_size.configure(text=f"{int(v)}% del ancho")
        self._schedule_auto_preview()

    def _on_opacity_change(self, v):
        self.lbl_opacity.configure(text=f"{int(v)}% de opacidad")
        self._schedule_auto_preview()

    # ════════════════════════════════════════════════════════════════════════
    #  MINIATURAS
    # ════════════════════════════════════════════════════════════════════════

    def _start_thumb_generation(self):
        paths = list(self.images)
        threading.Thread(
            target=self._thumb_thread, args=(paths,), daemon=True).start()

    def _thumb_thread(self, paths: list[str]):
        size  = self._thumb_size
        pils  = []
        for path in paths:
            try:
                img = Image.open(path).convert("RGB")
                img.thumbnail((size, size), Image.LANCZOS)
                pils.append(img)
            except Exception:
                pils.append(None)
        self.after(0, lambda: self._on_thumbs_ready(pils))

    def _on_thumbs_ready(self, pils: list):
        self._thumb_pil    = pils
        self._thumb_photos = []
        for img in pils:
            if img is not None:
                self._thumb_photos.append(ImageTk.PhotoImage(img))
            else:
                self._thumb_photos.append(None)
        self._draw_thumbstrip()

    def _draw_thumbstrip(self):
        self.thumb_canvas.delete("all")
        if not self.images or not self._thumb_photos:
            return

        pad    = 5
        sz     = self._thumb_size
        slot_w = sz + pad * 2
        cy     = THUMB_H // 2

        for i, photo in enumerate(self._thumb_photos):
            x0 = i * slot_w
            cx = x0 + slot_w // 2

            if photo:
                pw = photo.width()
                ph = photo.height()
                self.thumb_canvas.create_image(cx, cy, anchor="center", image=photo)
            else:
                pw = ph = sz
                self.thumb_canvas.create_rectangle(
                    cx - sz // 2, cy - sz // 2,
                    cx + sz // 2, cy + sz // 2,
                    fill="#2a2a2a", outline="#444")

            # Borde del seleccionado
            if i == self._preview_idx:
                hw = pw // 2
                hh = ph // 2
                self.thumb_canvas.create_rectangle(
                    cx - hw - 2, cy - hh - 2,
                    cx + hw + 2, cy + hh + 2,
                    outline="#1e88e5", width=2)

            # Punto naranja si tiene posición personalizada
            p = self.images[i] if i < len(self.images) else None
            if p and p in self._logo_positions:
                self.thumb_canvas.create_oval(
                    x0 + slot_w - 13, 4,
                    x0 + slot_w - 4,  13,
                    fill="#FF9800", outline="")

        total_w = len(self.images) * slot_w
        self.thumb_canvas.configure(scrollregion=(0, 0, total_w, THUMB_H))

        # Auto-scroll al elemento actual
        if self.images:
            n = len(self.images)
            frac = (self._preview_idx * slot_w) / max(total_w, 1)
            self.thumb_canvas.xview_moveto(max(0.0, frac - 0.15))

    def _on_thumb_click(self, event):
        pad    = 5
        slot_w = self._thumb_size + pad * 2
        cx     = self.thumb_canvas.canvasx(event.x)
        idx    = int(cx // slot_w)
        if 0 <= idx < len(self.images) and idx != self._preview_idx:
            self._preview_idx = idx
            self._update_nav_buttons()
            self._update_pos_indicator()
            self._draw_thumbstrip()
            self._update_preview()

    # ════════════════════════════════════════════════════════════════════════
    #  CANVAS — INTERACTIVIDAD
    # ════════════════════════════════════════════════════════════════════════

    def _on_canvas_resize(self, event):
        if self._canvas_bg_item is None:
            self.canvas.coords("hint", event.width // 2, event.height // 2)
        elif self._stored_preview_data:
            self._render_canvas_from_stored()

    def _is_on_logo(self, x: int, y: int) -> bool:
        if self._canvas_logo_item is None:
            return False
        lx, ly = self._canvas_logo_pos
        lw, lh = self._canvas_logo_wh
        return lx <= x <= lx + lw and ly <= y <= ly + lh

    def _on_canvas_motion(self, event):
        if self._is_on_logo(event.x, event.y):
            self.canvas.config(cursor="fleur")
        elif self._canvas_bg_item is not None:
            self.canvas.config(cursor="hand2")
        else:
            self.canvas.config(cursor="")

    def _on_canvas_press(self, event):
        if self._is_on_logo(event.x, event.y):
            self._drag_mode       = "logo"
            self._drag_start      = (event.x, event.y)
            self._drag_logo_origin = self._canvas_logo_pos
        elif self._canvas_bg_item is not None:
            self._drag_mode  = "pan"
            self._drag_start = (event.x, event.y)
            self._pan_delta  = [0, 0]

    def _on_canvas_drag(self, event):
        if self._drag_start is None:
            return

        if self._drag_mode == "logo":
            dx = event.x - self._drag_start[0]
            dy = event.y - self._drag_start[1]
            ox, oy = self._drag_logo_origin
            lw, lh = self._canvas_logo_wh
            ix0, iy0 = self._canvas_img_x0, self._canvas_img_y0
            iw_c = int(self._canvas_base_wh[0] * self._canvas_scale)
            ih_c = int(self._canvas_base_wh[1] * self._canvas_scale)
            new_lx = max(ix0, min(ox + dx, ix0 + iw_c - lw))
            new_ly = max(iy0, min(oy + dy, iy0 + ih_c - lh))
            self.canvas.coords(self._canvas_logo_item, new_lx, new_ly)
            if self._canvas_logo_border:
                self.canvas.coords(self._canvas_logo_border,
                                   new_lx, new_ly,
                                   new_lx + lw, new_ly + lh)
            self._canvas_logo_pos = (new_lx, new_ly)

        elif self._drag_mode == "pan":
            dx = event.x - self._drag_start[0]
            dy = event.y - self._drag_start[1]
            delta_x = dx - self._pan_delta[0]
            delta_y = dy - self._pan_delta[1]
            self._pan_delta[0] = dx
            self._pan_delta[1] = dy
            # Mover todos los items del canvas
            self.canvas.move("all", delta_x, delta_y)
            self._canvas_img_x0   += delta_x
            self._canvas_img_y0   += delta_y
            self._canvas_logo_pos  = (self._canvas_logo_pos[0] + delta_x,
                                      self._canvas_logo_pos[1] + delta_y)

    def _on_canvas_release(self, event):
        if self._drag_start is None:
            return

        if self._drag_mode == "logo":
            lx, ly    = self._canvas_logo_pos
            ix0, iy0  = self._canvas_img_x0, self._canvas_img_y0
            iw_a, ih_a = self._canvas_base_wh
            fx = (lx - ix0) / (iw_a * self._canvas_scale)
            fy = (ly - iy0) / (ih_a * self._canvas_scale)
            pos = (max(0.0, min(fx, 1.0)), max(0.0, min(fy, 1.0)))
            if self.images:
                path = self.images[self._preview_idx]
                self._logo_positions[path] = pos
            self._update_pos_indicator()
            self._draw_thumbstrip()
            n = len(self.images)
            self._set_status(
                f"✏  Posición guardada para imagen {self._preview_idx + 1}/{n}."
                f"   Las demás usarán Auto o la cuadrícula.")

        elif self._drag_mode == "pan":
            self._pan_offset[0] += self._pan_delta[0]
            self._pan_offset[1] += self._pan_delta[1]
            self._pan_delta = [0, 0]
            self._render_canvas_from_stored()

        self._drag_mode        = None
        self._drag_start       = None
        self._drag_logo_origin = None

    # ── Zoom ─────────────────────────────────────────────────────────────────

    def _on_canvas_wheel(self, event):
        if not self._stored_preview_data:
            return
        base_img = self._stored_preview_data[0]
        iw, ih   = base_img.size
        cw = max(self.canvas.winfo_width(),  200)
        ch = max(self.canvas.winfo_height(), 150)

        fit_scale = min((cw - 20) / iw, (ch - 20) / ih)
        old_zoom  = self._zoom_level
        factor    = 1.15 if event.delta > 0 else (1.0 / 1.15)
        new_zoom  = max(0.4, min(5.0, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 0.001:
            return

        old_rs   = fit_scale * old_zoom
        old_tw   = int(iw * old_rs)
        old_th   = int(ih * old_rs)
        old_ix0  = (cw - old_tw) // 2 + self._pan_offset[0]
        old_iy0  = (ch - old_th) // 2 + self._pan_offset[1]

        mx, my   = event.x, event.y
        img_px   = (mx - old_ix0) / old_rs
        img_py   = (my - old_iy0) / old_rs

        self._zoom_level = new_zoom
        new_rs  = fit_scale * new_zoom
        new_tw  = int(iw * new_rs)
        new_th  = int(ih * new_rs)

        new_ix0 = mx - img_px * new_rs
        new_iy0 = my - img_py * new_rs
        base_x0 = (cw - new_tw) // 2
        base_y0 = (ch - new_th) // 2
        self._pan_offset[0] = int(new_ix0 - base_x0)
        self._pan_offset[1] = int(new_iy0 - base_y0)

        self._render_canvas_from_stored()

    def _on_canvas_double_click(self, event):
        if not self._stored_preview_data:
            return
        if abs(self._zoom_level - 1.0) < 0.02 and \
           self._pan_offset[0] == 0 and self._pan_offset[1] == 0:
            return
        self._zoom_level   = 1.0
        self._pan_offset   = [0, 0]
        self._render_canvas_from_stored()

    # ════════════════════════════════════════════════════════════════════════
    #  DRAG & DROP
    # ════════════════════════════════════════════════════════════════════════

    def _on_drop(self, event):
        nuevos = [f for f in self._parse_drop(event.data)
                  if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
        if nuevos:
            self.images.extend(nuevos)
            self._preview_idx = 0
            self._refresh_images_label()
            self._start_thumb_generation()
            self._trigger_preview_soon()

    @staticmethod
    def _parse_drop(data: str) -> list[str]:
        return [p.strip("{}") for p in re.findall(r"\{[^}]+\}|\S+", data)]

    # ════════════════════════════════════════════════════════════════════════
    #  SELECTORES
    # ════════════════════════════════════════════════════════════════════════

    def _pick_images(self):
        files = filedialog.askopenfilenames(
            title="Seleccionar imágenes",
            filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.bmp *.webp *.tiff"),
                       ("Todos", "*.*")])
        if files:
            self.images = list(files)
            self._preview_idx = 0
            self._logo_positions.clear()
            self._refresh_images_label()
            self._start_thumb_generation()
            self._trigger_preview_soon()

    def _pick_images_folder(self):
        folder = filedialog.askdirectory(title="Seleccionar carpeta con imágenes")
        if not folder:
            return
        found = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS)
        if found:
            self.images = found
            self._preview_idx = 0
            self._logo_positions.clear()
            self._refresh_images_label()
            self._start_thumb_generation()
            self._trigger_preview_soon()
        else:
            self._set_status("La carpeta no contiene imágenes compatibles.", error=True)

    def _clear_images(self):
        self.images = []
        self._preview_idx = 0
        self._logo_positions.clear()
        self._thumb_photos = []
        self._thumb_pil    = []
        self.thumb_canvas.delete("all")
        self._stored_preview_data = None
        self._zoom_level = 1.0
        self._pan_offset = [0, 0]
        self._refresh_images_label()

    def _refresh_images_label(self):
        n = len(self.images)
        if n:
            self.lbl_images.configure(
                text=f"{n} imagen(es) seleccionada(s)", text_color="white")
            self._update_nav_buttons()
        else:
            hint = "  (o arrastra aquí)" if _DND else ""
            self.lbl_images.configure(text=f"0 imágenes{hint}", text_color="gray")
            self.btn_prev.configure(state="disabled")
            self.btn_next.configure(state="disabled")
            self.lbl_preview_idx.configure(text="")
            self._canvas_bg_item = None

    def _pick_logo(self):
        file = filedialog.askopenfilename(
            title="Seleccionar logo",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg"), ("Todos", "*.*")])
        if file:
            self.logo_path = file
            self.lbl_logo.configure(text=os.path.basename(file), text_color="white")
            self._add_recent_logo(file)
            self._set_window_icon(file)
            self._trigger_preview_soon()

    def _pick_folder(self):
        folder = filedialog.askdirectory(title="Seleccionar carpeta de salida")
        if folder:
            self.output_folder = folder
            self.entry_folder.delete(0, "end")
            self.lbl_folder.configure(text=folder, text_color="white")

    def _resolve_output(self) -> str | None:
        name = self.entry_folder.get().strip()
        if name:
            base = (os.path.dirname(self.images[0]) if self.images
                    else os.path.expanduser("~/Desktop"))
            path = os.path.join(base, name)
            os.makedirs(path, exist_ok=True)
            return path
        if self.output_folder:
            return self.output_folder
        return None

    # ════════════════════════════════════════════════════════════════════════
    #  VISTA PREVIA + NAVEGACIÓN
    # ════════════════════════════════════════════════════════════════════════

    def _update_nav_buttons(self):
        n = len(self.images)
        self.btn_prev.configure(
            state="normal" if n > 1 and self._preview_idx > 0 else "disabled")
        self.btn_next.configure(
            state="normal" if n > 1 and self._preview_idx < n - 1 else "disabled")
        if n:
            self.lbl_preview_idx.configure(
                text=f"{self._preview_idx + 1} / {n}")

    def _prev_preview(self):
        if self._preview_idx > 0:
            self._preview_idx -= 1
            self._zoom_level   = 1.0
            self._pan_offset   = [0, 0]
            self._update_nav_buttons()
            self._update_pos_indicator()
            self._draw_thumbstrip()
            self._update_preview()

    def _next_preview(self):
        if self._preview_idx < len(self.images) - 1:
            self._preview_idx += 1
            self._zoom_level   = 1.0
            self._pan_offset   = [0, 0]
            self._update_nav_buttons()
            self._update_pos_indicator()
            self._draw_thumbstrip()
            self._update_preview()

    def _kb_navigate(self, direction: int):
        focused = self.focus_get()
        if focused and "entry" in type(focused).__name__.lower():
            return
        if direction < 0:
            self._prev_preview()
        else:
            self._next_preview()

    def _update_preview(self):
        if not self.images:
            self._set_status("Primero selecciona las imágenes.", error=True)
            return
        self._preview_idx = min(self._preview_idx, len(self.images) - 1)
        self._update_nav_buttons()
        self._set_status("Generando vista previa…")
        self.btn_process.configure(state="disabled")
        threading.Thread(target=self._preview_thread, daemon=True).start()

    def _preview_thread(self):
        idx    = self._preview_idx
        path   = self.images[idx]
        abs_xy = self._logo_positions.get(path)
        try:
            if self.logo_path:
                from logo_placer import prepare_preview
                base_img, logo_img, px, py = prepare_preview(
                    path, self.logo_path,
                    size_pct=int(self.slider_size.get()),
                    opacity=int(self.slider_opacity.get()),
                    force_position=self.forced_pos if abs_xy is None else None,
                    absolute_xy=abs_xy)
            else:
                # Sin logo: solo mostrar la imagen
                base_img = Image.open(path).convert("RGBA")
                logo_img = None
                px, py   = 0, 0
            self.after(0, lambda: self._render_canvas(base_img, logo_img, px, py))
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Error: {e}", error=True))
        finally:
            self.after(0, lambda: self.btn_process.configure(state="normal"))

    # ── Render del canvas ────────────────────────────────────────────────────

    def _render_canvas(self, base_img: Image.Image, logo_img: Image.Image,
                       px: int, py: int):
        """Almacena los datos y renderiza con el zoom/pan actual."""
        self._stored_preview_data = (base_img, logo_img, px, py)
        self._render_canvas_from_stored()

    def _render_canvas_from_stored(self):
        if not self._stored_preview_data:
            return
        base_img, logo_img, px, py = self._stored_preview_data

        cw = max(self.canvas.winfo_width(),  200)
        ch = max(self.canvas.winfo_height(), 150)
        iw, ih = base_img.size

        fit_scale    = min((cw - 20) / iw, (ch - 20) / ih)
        render_scale = fit_scale * self._zoom_level

        # Dimensiones completas de la imagen renderizada
        tw = int(iw * render_scale)
        th = int(ih * render_scale)

        # Posición top-left de la imagen en el canvas
        img_x0 = (cw - tw) // 2 + self._pan_offset[0]
        img_y0 = (ch - th) // 2 + self._pan_offset[1]

        # Región visible de la imagen (en coordenadas del render)
        vis_x0 = max(0, -img_x0)
        vis_y0 = max(0, -img_y0)
        vis_x1 = min(tw, cw - img_x0)
        vis_y1 = min(th, ch - img_y0)

        if vis_x1 <= vis_x0 or vis_y1 <= vis_y0:
            return

        draw_x0 = img_x0 + vis_x0
        draw_y0 = img_y0 + vis_y0

        # Recorte en coords de la imagen original
        crop_x0 = max(0, int(vis_x0 / render_scale))
        crop_y0 = max(0, int(vis_y0 / render_scale))
        crop_x1 = min(iw, int(vis_x1 / render_scale))
        crop_y1 = min(ih, int(vis_y1 / render_scale))

        vis_w = vis_x1 - vis_x0
        vis_h = vis_y1 - vis_y0

        cropped = base_img.crop((crop_x0, crop_y0, crop_x1, crop_y1)).convert("RGB")
        thumb   = cropped.resize((vis_w, vis_h), Image.LANCZOS)

        # Logo escalado (solo si existe)
        if logo_img is not None:
            lw_orig, lh_orig = logo_img.size
            lw = max(1, int(lw_orig * render_scale))
            lh = max(1, int(lh_orig * render_scale))
            logo_scaled = logo_img.resize((lw, lh), Image.LANCZOS)
            lx = img_x0 + int(px * render_scale)
            ly = img_y0 + int(py * render_scale)
        else:
            logo_scaled = lw = lh = lx = ly = None

        bg_photo = ImageTk.PhotoImage(thumb)

        self.canvas.delete("all")
        self._canvas_bg_item = self.canvas.create_image(
            draw_x0, draw_y0, anchor="nw", image=bg_photo)

        # ── Logo (solo si existe) ────────────────────────────────────────────
        if logo_img is not None:
            logo_photo = ImageTk.PhotoImage(logo_scaled)
            self._canvas_logo_item = self.canvas.create_image(
                lx, ly, anchor="nw", image=logo_photo)
            self._canvas_logo_border = self.canvas.create_rectangle(
                lx, ly, lx + lw, ly + lh,
                outline="#1e88e5", width=2, dash=(5, 3))
            self.canvas.create_text(
                lx + lw // 2, ly + lh + 12,
                text="arrastra para reposicionar",
                fill="#4a4a4a", font=("Segoe UI", 9))
            self._tk_logo_photo   = logo_photo
            self._canvas_logo_pos = (lx, ly)
            self._canvas_logo_wh  = (lw, lh)
        else:
            logo_photo = None
            self._canvas_logo_item   = None
            self._canvas_logo_border = None
            self._tk_logo_photo      = None
            self._canvas_logo_pos    = (0, 0)
            self._canvas_logo_wh     = (0, 0)
            # Aviso de que falta logo
            self.canvas.create_text(
                cw // 2, ch - 18,
                text="Sin logo · selecciona uno para aplicarlo",
                fill="#555", font=("Segoe UI", 9))

        # Indicador de zoom
        if abs(self._zoom_level - 1.0) > 0.04:
            self.canvas.create_text(
                cw - 8, ch - 8,
                text=f"{self._zoom_level:.1f}×",
                fill="#888", font=("Segoe UI", 10, "bold"),
                anchor="se")
            self.canvas.create_text(
                cw - 8, ch - 22,
                text="doble-clic = reset",
                fill="#555", font=("Segoe UI", 8),
                anchor="se")

        # Guardar refs (evitar GC de PhotoImage)
        self._tk_bg_photo = bg_photo

        # Estado del canvas para drag
        self._canvas_img_x0  = img_x0
        self._canvas_img_y0  = img_y0
        self._canvas_scale   = render_scale
        self._canvas_base_wh = (iw, ih)

        n    = len(self.images)
        name = os.path.basename(self.images[self._preview_idx])
        extra = "  ·   Arrastra logo · Scroll=zoom · Doble-clic=reset zoom" \
                if logo_img is not None else "  ·   Scroll=zoom · Doble-clic=reset zoom"
        self._set_status(f"Vista previa: {name}  ({self._preview_idx + 1}/{n}){extra}")

    # ════════════════════════════════════════════════════════════════════════
    #  PROCESAMIENTO
    # ════════════════════════════════════════════════════════════════════════

    def _start_processing(self):
        if not self._check_license_now():
            return
        if not self.images:
            self._set_status("Selecciona imágenes primero.", error=True)
            return
        if not self.logo_path:
            self._set_status("Selecciona un logo primero.", error=True)
            return
        output = self._resolve_output()
        if not output:
            self._set_status(
                "Escribe un nombre de carpeta o presiona «Buscar».", error=True)
            return

        self.btn_process.configure(state="disabled")
        self.btn_open.configure(state="disabled")
        self.progress.set(0)
        self._set_status(f"Guardando en:\n{output}")
        threading.Thread(
            target=self._process_thread, args=(output,), daemon=True).start()

    def _process_thread(self, output: str):
        from logo_placer import place_logo
        total         = len(self.images)
        size          = int(self.slider_size.get())
        opacity       = int(self.slider_opacity.get())
        pos           = self.forced_pos
        suffix        = self.entry_suffix.get().strip()
        force_jpeg    = bool(self.switch_jpeg.get())
        saved         = 0
        errores: list[str] = []

        for i, path in enumerate(self.images):
            try:
                abs_xy = self._logo_positions.get(path)
                result = place_logo(
                    path, self.logo_path,
                    size_pct=size, opacity=opacity,
                    force_position=pos if abs_xy is None else None,
                    absolute_xy=abs_xy)

                base, ext = os.path.splitext(os.path.basename(path))

                if force_jpeg:
                    out_name = f"{base}{suffix}.jpg"
                    out_path = os.path.join(output, out_name)
                    result.convert("RGB").save(out_path, "JPEG", quality=95)
                else:
                    out_name = f"{base}{suffix}{ext}"
                    out_path = os.path.join(output, out_name)
                    if ext.lower() in (".jpg", ".jpeg"):
                        result.convert("RGB").save(out_path, quality=95)
                    else:
                        result.save(out_path)

                saved += 1

            except Exception as e:
                errores.append(f"{os.path.basename(path)}: {e}")

            pct = (i + 1) / total
            self.after(0, lambda p=pct, c=i + 1: self._on_progress(p, c, total))

        if errores:
            try:
                with open(os.path.join(output, "_errores.txt"),
                          "w", encoding="utf-8") as f:
                    f.write("\n".join(errores))
            except Exception:
                pass

        self.after(0, lambda: self._on_done(output, saved, total, errores))

    def _on_progress(self, value: float, current: int, total: int):
        self.progress.set(value)
        self._set_status(f"Procesando {current} de {total}…")

    def _on_done(self, output: str, saved: int, total: int, errores: list[str]):
        self._last_output = output
        self.btn_process.configure(state="normal")
        self.progress.set(1)
        if saved == total:
            self.btn_open.configure(state="normal")
            self._set_status(f"¡Listo!  {saved} imagen(es) guardada(s) en:\n{output}")
        elif saved == 0:
            primer = errores[0] if errores else "error desconocido"
            self._set_status(f"Error: 0/{total} guardadas.\n{primer}", error=True)
        else:
            self.btn_open.configure(state="normal")
            self._set_status(
                f"Guardadas {saved}/{total}.  "
                f"{len(errores)} con error → _errores.txt", error=True)

    def _open_output(self):
        if self._last_output and os.path.exists(self._last_output):
            os.startfile(self._last_output)

    # ════════════════════════════════════════════════════════════════════════
    #  MONITOR DE LICENCIA EN TIEMPO REAL
    # ════════════════════════════════════════════════════════════════════════

    def _update_license_label(self):
        """Actualiza el badge de licencia en el sidebar."""
        try:
            from license_manager import LicenseManager
            lm   = LicenseManager()
            key  = lm.get_key() or ""
            name = lm.get_user_name() or ""
            if lm.is_cached_valid():
                text  = f"🔑 {name}  ({key})" if name else f"🔑 {key}"
                color = "#4CAF50"
            else:
                text  = "🔑 Sin licencia activa — haz clic aquí"
                color = "#ff6b6b"
        except Exception:
            text  = "🔑 Error al leer licencia"
            color = "#ff6b6b"
        self._lbl_license.configure(text=text, text_color=color)

    def _show_license_info(self):
        """Muestra un diálogo con la información de la licencia activa."""
        import tkinter.messagebox as mb
        try:
            from license_manager import LicenseManager
            lm   = LicenseManager()
            key  = lm.get_key() or "(ninguna)"
            name = lm.get_user_name() or "(desconocido)"
            if lm.is_cached_valid():
                mb.showinfo(
                    "Licencia activa",
                    f"Usuario:  {name}\n"
                    f"Clave:    {key}\n\n"
                    "Para cambiar la clave cierra la app y vuelve a abrirla.")
            else:
                mb.showwarning(
                    "Sin licencia activa",
                    "No hay una licencia válida en este momento.\n"
                    "Cierra la app y actívala con tu clave.")
        except Exception as e:
            mb.showerror("Error", str(e))

    def _check_license_now(self) -> bool:
        """
        Verifica si la licencia sigue vigente antes de ejecutar una función.
        Usa la caché local (sin red) si está fresca; llama a Firebase si expiró.
        Devuelve True si se puede continuar, False si se debe bloquear.
        """
        try:
            from license_manager import LicenseManager
            lm     = LicenseManager()
            result = lm.check()
            if result.valid:
                self._update_license_label()
                return True
            import tkinter.messagebox as mb
            mb.showerror(
                "Licencia requerida",
                result.message or
                "Tu licencia no está activa.\n"
                "Contacta a tu distribuidor.")
            self._update_license_label()
            return False
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("Error de licencia", str(e))
            return False

    def _schedule_license_monitor(self):
        """Programa la próxima verificación de licencia (cada 5 minutos)."""
        self._license_monitor_id = self.after(5 * 60 * 1000,
                                              self._run_license_check)

    def _run_license_check(self):
        """Verifica en Firebase si la licencia sigue activa."""
        def _check():
            try:
                from license_manager import LicenseManager
                lm      = LicenseManager()
                revoked = lm.check_revoked()
                if revoked:
                    self.after(0, self._on_license_revoked)
                else:
                    self.after(0, self._update_license_label)
                    self.after(0, self._schedule_license_monitor)
            except Exception:
                # Cualquier error → no interrumpir, reintentar en 5 min
                self.after(0, self._schedule_license_monitor)
        threading.Thread(target=_check, daemon=True).start()

    def _on_license_revoked(self):
        """Cierra la app cuando la licencia es revocada en tiempo real."""
        import tkinter.messagebox as mb
        self._lbl_license.configure(
            text="🔑 Licencia desactivada", text_color="#ff6b6b")
        mb.showerror(
            "Licencia desactivada",
            "Tu licencia ha sido desactivada por el administrador.\n"
            "La aplicación se cerrará.")
        self._on_close()

    def _open_facebook_window(self):
        if not self._check_license_now():
            return
        FacebookWindow(self)

    # ════════════════════════════════════════════════════════════════════════
    #  CONFIGURACIÓN PERSISTENTE
    # ════════════════════════════════════════════════════════════════════════

    def _load_config(self):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            # logo_path NO se restaura al abrir — el usuario elige desde recientes
            if cfg.get("output_folder") and os.path.exists(cfg["output_folder"]):
                self.output_folder = cfg["output_folder"]
                self.lbl_folder.configure(text=self.output_folder, text_color="white")
            if cfg.get("suffix"):
                self.entry_suffix.insert(0, cfg["suffix"])
            if cfg.get("size_pct"):
                v = int(cfg["size_pct"])
                self.slider_size.set(v)
                self.lbl_size.configure(text=f"{v}% del ancho")
            if cfg.get("opacity"):
                v = int(cfg["opacity"])
                self.slider_opacity.set(v)
                self.lbl_opacity.configure(text=f"{v}% de opacidad")
            if cfg.get("recent_logos"):
                self._recent_logos = [
                    p for p in cfg["recent_logos"] if isinstance(p, str)][:5]
                self._refresh_recent_ui()
            if cfg.get("force_jpeg"):
                self.switch_jpeg.select()
        except Exception:
            pass

    def _save_config(self):
        # Leer config existente para no borrar campos de licencia u otros
        cfg = {}
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
        cfg.update({
            "logo_path":     self.logo_path,
            "output_folder": self.output_folder,
            "suffix":        self.entry_suffix.get().strip(),
            "size_pct":      int(self.slider_size.get()),
            "opacity":       int(self.slider_opacity.get()),
            "recent_logos":  self._recent_logos,
            "force_jpeg":    bool(self.switch_jpeg.get()),
        })
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _on_close(self):
        self._save_config()
        self.destroy()

    # ════════════════════════════════════════════════════════════════════════
    #  HELPERS
    # ════════════════════════════════════════════════════════════════════════

    def _section_label(self, parent, text: str, row: int):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=row, column=0, padx=12, pady=(12, 2), sticky="w")

    def _set_status(self, msg: str, error: bool = False):
        self.lbl_status.configure(
            text=msg, text_color="#ff6b6b" if error else "gray")


# ══════════════════════════════════════════════════════════════════════════════
#  VENTANA DE SUBIDA A FACEBOOK
# ══════════════════════════════════════════════════════════════════════════════

class FacebookWindow(ctk.CTkToplevel):
    """Ventana modal para subir imágenes a un álbum de Facebook."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Subir a Facebook")
        self.geometry("490x600")
        self.resizable(False, False)
        self.grab_set()   # modal: bloquea la ventana principal

        from facebook_uploader import FacebookAuth, FacebookUploader
        self._auth     = FacebookAuth()
        self._uploader = FacebookUploader(self._auth)
        self._pages:  list[dict] = []
        self._albums: list[dict] = []
        self._stop_evt = threading.Event()
        self._folder:  str | None = None

        self._build()
        self._refresh_login_ui()

    # ── Construcción de la UI ─────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        r = 0

        # ── Sección: Cuenta ───────────────────────────────────────────────────
        self._sec("Cuenta de Facebook", r); r += 1

        self._lbl_user = ctk.CTkLabel(self, text="No has iniciado sesión",
                                      text_color="gray")
        self._lbl_user.grid(row=r, column=0, padx=20, pady=(4, 0), sticky="w"); r += 1

        login_row = ctk.CTkFrame(self, fg_color="transparent")
        login_row.grid(row=r, column=0, padx=20, pady=(6, 0), sticky="ew")
        login_row.grid_columnconfigure(0, weight=1); r += 1

        self._btn_login = ctk.CTkButton(
            login_row, text="🔵  Iniciar sesión con Facebook",
            fg_color="#1877F2", hover_color="#166fe5",
            command=self._do_login)
        self._btn_login.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self._btn_logout = ctk.CTkButton(
            login_row, text="Cerrar sesión", width=110,
            fg_color="transparent", border_width=1,
            command=self._do_logout)
        self._btn_logout.grid(row=0, column=1)

        # ── Sección: Destino ──────────────────────────────────────────────────
        self._sec("Página de Facebook", r); r += 1

        dest_row = ctk.CTkFrame(self, fg_color="transparent")
        dest_row.grid(row=r, column=0, padx=20, pady=(4, 0), sticky="ew")
        dest_row.grid_columnconfigure(1, weight=1); r += 1

        ctk.CTkLabel(dest_row, text="Página:").grid(
            row=0, column=0, padx=(0, 8))
        self._page_menu = ctk.CTkOptionMenu(
            dest_row, values=["(inicia sesión primero)"],
            state="disabled",
            command=lambda _: self._load_albums())
        self._page_menu.grid(row=0, column=1, sticky="ew")

        # ── Sección: Álbum ────────────────────────────────────────────────────
        self._sec("Álbum de destino", r); r += 1

        alb_row = ctk.CTkFrame(self, fg_color="transparent")
        alb_row.grid(row=r, column=0, padx=20, pady=(4, 0), sticky="ew")
        alb_row.grid_columnconfigure(0, weight=1); r += 1

        self._album_menu = ctk.CTkOptionMenu(
            alb_row, values=["(carga después de iniciar sesión)"],
            state="disabled", command=lambda _: None)
        self._album_menu.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(alb_row, text="↻", width=32,
                      fg_color="transparent", border_width=1,
                      command=self._load_albums).grid(
            row=0, column=1, padx=(6, 0))

        ctk.CTkLabel(self,
                     text="  Selecciona un álbum o elige «Sin álbum» para subir "
                          "las fotos sueltas a la página",
                     text_color="gray", font=ctk.CTkFont(size=10),
                     wraplength=440, justify="left").grid(
            row=r, column=0, padx=20, pady=(2, 0), sticky="w"); r += 1

        ctk.CTkLabel(self, text="Título / descripción (opcional):",
                     anchor="w").grid(
            row=r, column=0, padx=20, pady=(10, 0), sticky="w"); r += 1
        self._entry_caption = ctk.CTkEntry(
            self, placeholder_text="Se añade como descripción a las fotos")
        self._entry_caption.grid(
            row=r, column=0, padx=20, pady=(2, 0), sticky="ew"); r += 1

        # ── Sección: Carpeta ──────────────────────────────────────────────────
        self._sec("Carpeta de imágenes a subir", r); r += 1

        frow = ctk.CTkFrame(self, fg_color="transparent")
        frow.grid(row=r, column=0, padx=20, pady=(4, 0), sticky="ew")
        frow.grid_columnconfigure(0, weight=1); r += 1

        self._entry_folder = ctk.CTkEntry(
            frow, placeholder_text="Selecciona la carpeta con las imágenes…")
        self._entry_folder.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(frow, text="📁", width=36,
                      command=self._pick_folder).grid(row=0, column=1)

        self._lbl_folder_info = ctk.CTkLabel(
            self, text="", text_color="gray", font=ctk.CTkFont(size=11))
        self._lbl_folder_info.grid(
            row=r, column=0, padx=20, pady=(2, 0), sticky="w"); r += 1

        # ── Progreso ──────────────────────────────────────────────────────────
        self._progress = ctk.CTkProgressBar(self)
        self._progress.set(0)
        self._progress.grid(row=r, column=0, padx=20, pady=(16, 4), sticky="ew"); r += 1

        self._lbl_progress = ctk.CTkLabel(
            self, text="", text_color="gray",
            font=ctk.CTkFont(size=11), wraplength=440)
        self._lbl_progress.grid(
            row=r, column=0, padx=20, sticky="w"); r += 1

        # ── Botón principal ───────────────────────────────────────────────────
        self._btn_upload = ctk.CTkButton(
            self, text="📤  Subir imágenes a Facebook",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=46, state="disabled",
            command=self._start_upload)
        self._btn_upload.grid(
            row=r, column=0, padx=20, pady=(14, 20), sticky="ew"); r += 1

    def _sec(self, text: str, row: int):
        ctk.CTkLabel(self, text=text,
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=row, column=0, padx=20, pady=(14, 0), sticky="w")

    # ── Estado de sesión ──────────────────────────────────────────────────────

    def _refresh_login_ui(self):
        if self._auth.is_logged_in():
            name = self._auth.get_user_name() or "Usuario"
            self._lbl_user.configure(
                text=f"✓  Conectado como: {name}", text_color="#4CAF50")
            self._btn_login.configure(state="disabled",
                                      text="🔵  Iniciar sesión con Facebook")
            self._btn_logout.configure(state="normal")
            self._load_pages()
        else:
            self._lbl_user.configure(
                text="No has iniciado sesión", text_color="gray")
            self._btn_login.configure(state="normal")
            self._btn_logout.configure(state="disabled")
        self._check_ready()

    # ── Login / logout ────────────────────────────────────────────────────────

    def _do_login(self):
        self._btn_login.configure(state="disabled", text="Abriendo navegador…")
        self._lbl_user.configure(
            text="Esperando autorización en el navegador (hasta 5 min)…",
            text_color="#FF9800")

        self._auth.login(
            on_success=lambda tok, name: self.after(0, lambda: self._on_login_ok(name)),
            on_error=lambda msg:         self.after(0, lambda: self._on_login_err(msg)),
        )

    def _on_login_ok(self, name: str):
        self._refresh_login_ui()

    def _on_login_err(self, msg: str):
        self._lbl_user.configure(text=f"✗  {msg}", text_color="#ff6b6b")
        self._btn_login.configure(state="normal",
                                  text="🔵  Iniciar sesión con Facebook")

    def _do_logout(self):
        self._auth.logout()
        self._pages  = []
        self._albums = []
        self._page_menu.configure(
            values=["(inicia sesión primero)"], state="disabled")
        self._album_menu.configure(
            values=["(carga después de iniciar sesión)"], state="disabled")
        self._refresh_login_ui()

    # ── Páginas ───────────────────────────────────────────────────────────────

    def _load_pages(self):
        def _fetch():
            try:
                pages = self._uploader.get_pages()
                self.after(0, lambda: self._on_pages_ready(pages))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self._lbl_progress.configure(
                    text=f"No se pudieron cargar páginas: {msg}",
                    text_color="gray"))
        threading.Thread(target=_fetch, daemon=True).start()

    def _on_pages_ready(self, pages: list[dict]):
        self._pages = pages
        if pages:
            names = [p["name"] for p in pages]
            self._page_menu.configure(values=names, state="normal")
            self._page_menu.set(names[0])
        else:
            self._page_menu.configure(
                values=["Sin páginas administradas"], state="disabled")
        self._load_albums()
        self._check_ready()

    # ── Álbumes ───────────────────────────────────────────────────────────────

    def _get_target_id(self) -> str:
        if self._pages:
            sel = self._page_menu.get()
            for p in self._pages:
                if p["name"] == sel:
                    return p["id"]
            return self._pages[0]["id"]
        return ""

    def _get_page_token(self) -> str | None:
        if self._pages:
            sel = self._page_menu.get()
            for p in self._pages:
                if p["name"] == sel:
                    return p.get("access_token")
        return None

    def _load_albums(self):
        if not self._auth.is_logged_in() or not self._pages:
            return
        tid  = self._get_target_id()
        ptok = self._get_page_token()

        def _fetch():
            try:
                albs = self._uploader.get_albums(tid, token=ptok)
                self.after(0, lambda: self._on_albums_ready(albs))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self._lbl_progress.configure(
                    text=f"No se pudieron cargar álbumes: {msg}",
                    text_color="gray"))
        threading.Thread(target=_fetch, daemon=True).start()

    def _on_albums_ready(self, albs: list[dict]):
        self._albums = albs
        album_names = [f"{a['name']}  ({a.get('count', '?')} fotos)" for a in albs]
        names = ["— Sin álbum (fotos sueltas) —"] + album_names
        self._album_menu.configure(values=names, state="normal")
        self._album_menu.set(names[0])

    # ── Carpeta ───────────────────────────────────────────────────────────────

    def _pick_folder(self):
        folder = filedialog.askdirectory(
            title="Carpeta con imágenes ya procesadas")
        if not folder:
            return
        self._folder = folder
        self._entry_folder.delete(0, "end")
        self._entry_folder.insert(0, folder)
        exts  = {".jpg", ".jpeg", ".png", ".webp"}
        count = sum(1 for f in os.listdir(folder)
                    if os.path.splitext(f.lower())[1] in exts)
        self._lbl_folder_info.configure(
            text=f"→ {count} imagen(es) encontradas",
            text_color="white" if count else "#ff6b6b")
        self._check_ready()

    def _check_ready(self):
        ok = (self._auth.is_logged_in() and
              bool(self._pages) and
              bool(self._folder) and
              os.path.isdir(self._folder or ""))
        self._btn_upload.configure(state="normal" if ok else "disabled")

    # ── Subida ────────────────────────────────────────────────────────────────

    def _start_upload(self):
        if not self._folder or not os.path.isdir(self._folder):
            return

        self._stop_evt.clear()
        self._btn_upload.configure(state="disabled", text="Subiendo…")
        self._progress.set(0)
        self._lbl_progress.configure(text="Preparando…", text_color="gray")

        tid  = self._get_target_id()
        ptok = self._get_page_token()

        if not tid:
            self._on_error("No hay ninguna página seleccionada.")
            return
        if not ptok:
            self._on_error(
                "No se pudo obtener el token de la página.\n"
                "Cierra sesión, inicia sesión de nuevo e inténtalo otra vez.")
            return

        sel     = self._album_menu.get()
        caption = self._entry_caption.get().strip()

        def _cb(n, total, fname):
            self.after(0, lambda: self._on_progress(n, total, fname))

        def _run():
            try:
                if sel.startswith("— Sin álbum"):
                    # Un solo post con TODAS las fotos agrupadas (sin dividir en lotes)
                    uploaded, total = self._uploader.upload_folder_as_post(
                        tid, self._folder,
                        caption=caption,
                        progress_cb=_cb, stop_evt=self._stop_evt,
                        token=ptok,
                        batch_size=9999)
                else:
                    # Subir al álbum existente seleccionado
                    upload_target = None
                    for a in self._albums:
                        if f"{a['name']}  ({a.get('count','?')} fotos)" == sel:
                            upload_target = a["id"]
                            break
                    if not upload_target:
                        raise RuntimeError("No se encontró el álbum seleccionado.")
                    uploaded, total = self._uploader.upload_folder(
                        upload_target, self._folder,
                        caption=caption,
                        progress_cb=_cb, stop_evt=self._stop_evt,
                        token=ptok)

                self.after(0, lambda: self._on_done(uploaded, total))

            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda: self._on_error(msg))

        threading.Thread(target=_run, daemon=True).start()

    def _on_progress(self, n: int, total: int, fname: str):
        if total > 0:
            self._progress.set(n / total)
        self._lbl_progress.configure(
            text=f"{n}/{total}  ·  {fname}", text_color="gray")

    def _on_done(self, uploaded: int, total: int):
        self._progress.set(1)
        self._btn_upload.configure(
            state="normal", text="📤  Subir imágenes a Facebook")
        self._lbl_progress.configure(
            text=f"✓  {uploaded} de {total} fotos subidas con éxito. ¡Listo!",
            text_color="#4CAF50")

    def _on_error(self, msg: str):
        self._btn_upload.configure(
            state="normal", text="📤  Subir imágenes a Facebook")
        self._lbl_progress.configure(
            text=f"✗  Error: {msg}", text_color="#ff6b6b")


# ══════════════════════════════════════════════════════════════════════════════
#  VENTANA DE LICENCIA
# ══════════════════════════════════════════════════════════════════════════════

class LicenseWindow(ctk.CTk):
    """Ventana de activación de licencia — se muestra antes de abrir la app."""

    def __init__(self, lm, initial_msg: str = ""):
        super().__init__()
        self._lm        = lm
        self._activated = False

        self.title("Logo Stamper — Activar licencia")
        self.geometry("420x340")
        self.resizable(False, False)
        self.grid_columnconfigure(0, weight=1)

        # ── Ícono de ventana ─────────────────────────────────────────────────
        proj = os.path.dirname(os.path.abspath(__file__))
        for name in ("app_icon.png", "app_icon.ico"):
            p = os.path.join(proj, name)
            if os.path.exists(p):
                try:
                    from PIL import Image
                    img   = Image.open(p).resize((64, 64)).convert("RGBA")
                    photo = ImageTk.PhotoImage(img)
                    self.iconphoto(True, photo)
                    self._icon = photo
                except Exception:
                    pass
                break

        # ── UI ───────────────────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Logo Stamper",
                     font=ctk.CTkFont(size=26, weight="bold")).grid(
            row=0, column=0, pady=(32, 4))

        ctk.CTkLabel(self, text="🔑  Ingresa tu clave de licencia",
                     text_color="gray").grid(row=1, column=0, pady=(0, 20))

        self._entry = ctk.CTkEntry(
            self, placeholder_text="LS-XXXX-XXXX-XXXX",
            width=290, height=42, font=ctk.CTkFont(size=15),
            justify="center")
        existing = lm.get_key()
        if existing:
            self._entry.insert(0, existing)
        self._entry.grid(row=2, column=0, pady=(0, 12))
        self._entry.bind("<Return>", lambda e: self._activate())

        self._btn = ctk.CTkButton(
            self, text="Activar", width=180, height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._activate)
        self._btn.grid(row=3, column=0, pady=(0, 14))

        color = "#ff6b6b" if initial_msg else "gray"
        self._lbl = ctk.CTkLabel(
            self, text=initial_msg, text_color=color,
            wraplength=370, font=ctk.CTkFont(size=12))
        self._lbl.grid(row=4, column=0, padx=20)

        ctk.CTkLabel(
            self,
            text="¿No tienes licencia? Contacta a tu distribuidor.",
            text_color="#444", font=ctk.CTkFont(size=10)).grid(
            row=5, column=0, pady=(24, 0))

    def _activate(self):
        key = self._entry.get().strip()
        if not key:
            self._set_status("Ingresa tu clave de licencia.", error=True)
            return
        self._btn.configure(state="disabled", text="Validando…")
        self._lbl.configure(text="Conectando con el servidor…",
                            text_color="gray")
        self.update()

        def _check():
            result = self._lm.validate_new_key(key)
            self.after(0, lambda: self._on_result(result))
        threading.Thread(target=_check, daemon=True).start()

    def _on_result(self, result):
        if result.valid:
            self._activated = True
            name = f"  —  {result.user_name}" if result.user_name else ""
            self._set_status(f"✓ Licencia válida{name}", error=False)
            self.after(900, self.destroy)
        else:
            self._btn.configure(state="normal", text="Activar")
            self._set_status(result.message, error=True)

    def _set_status(self, msg: str, error: bool = False):
        self._lbl.configure(
            text=msg,
            text_color="#ff6b6b" if error else "#4CAF50")


if __name__ == "__main__":
    from license_manager import LicenseManager
    lm     = LicenseManager()
    result = lm.check()

    if not result.valid:
        # Mostrar ventana de activación
        lw = LicenseWindow(lm, initial_msg=result.message if lm.get_key() else "")
        lw.mainloop()
        # Re-verificar después de que el usuario ingresó la clave
        if not lm.is_cached_valid():
            import sys; sys.exit(0)   # cerró sin activar

    app = App()
    app.mainloop()
