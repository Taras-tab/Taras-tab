import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

TEE_HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".coef_tee_history.json")
TEE_LAYOUT_FILE = os.path.join(os.path.expanduser("~"), ".coef_tee_layout.json")

# Default relative positions for fields on the canvas (x, y in 0..1)
# Fc/Lc are shown on the right by default; Fo/Lo below the image
DEFAULT_LAYOUT = {
    "Fn": [0.05, 0.05],
    "Ln": [0.05, 0.25],
    "Fc": [0.65, 0.05],
    "Lc": [0.65, 0.25],
    "Fo": [0.30, 0.70],
    "Lo": [0.30, 0.88],
}


class TeePanel(ttk.Frame):
    """Panel for tee sketch with on-image input fields and history."""

    def __init__(self, master, on_ratios=None):
        super().__init__(master)
        self.pack(fill=tk.X, pady=(0, 6))

        self._pil_raw = None
        self._photo = None
        self.layout = self._load_layout()
        self._drag_name = None
        self._drag_offset = (0, 0)
        self.edit_mode = False
        self.on_ratios = on_ratios
        self.auto_mode = False

        self.canvas = tk.Canvas(self, width=374, height=288, highlightthickness=0)
        self.canvas.pack(padx=6, pady=(4, 2))
        self.canvas.bind("<Configure>", lambda e: self._position_fields())

        # create field widgets with integer-only validation
        self.fields = {}
        self.vars = {}
        vcmd = (self.register(self._validate_int), "%P")
        for name in ("Fn", "Ln", "Fc", "Lc", "Fo", "Lo"):
            var = tk.StringVar()
            frame = tk.Frame(self.canvas, bg="white")
            label = tk.Label(frame, text=f"{name}=", bg="white")
            label.pack(side=tk.LEFT)
            entry = tk.Entry(
                frame,
                textvariable=var,
                width=6,
                validate="key",
                validatecommand=vcmd,
            )
            entry.pack(side=tk.LEFT)
            for w in (frame, label, entry):
                w.bind("<ButtonPress-1>", lambda e, n=name: self._drag_start(n, e))
                w.bind("<B1-Motion>", lambda e, n=name: self._drag_move(n, e))
                w.bind("<ButtonRelease-1>", lambda e, n=name: self._drag_stop(n, e))
            self.canvas.create_window(0, 0, window=frame, anchor="nw", tags=name)
            self.fields[name] = frame
            self.vars[name] = var

        # ratio table
        table = ttk.Frame(self)
        table.pack(padx=6, pady=(2, 4))
        self.lbl_fn_fc = ttk.Label(table, text="Fn/Fc=—")
        self.lbl_fn_fc.grid(row=0, column=0, padx=4)
        self.lbl_fo_fc = ttk.Label(table, text="Fo/Fc=—")
        self.lbl_fo_fc.grid(row=0, column=1, padx=4)
        self.lbl_lo_lc = ttk.Label(table, text="Lo/Lc=—")
        self.lbl_lo_lc.grid(row=0, column=2, padx=4)

        for key in ("Fn", "Fc", "Fo", "Lo", "Lc"):
            self.vars[key].trace_add("write", lambda *args: self._update_ratios())

        # auto/manual toggle and controls
        self.btn_auto = ttk.Button(self, text="Ручна", command=self._toggle_auto)
        self.btn_auto.pack(fill=tk.X, padx=6, pady=(0, 2))
        ttk.Button(self, text="Зберегти трійник", command=self._save_current).pack(fill=tk.X, padx=6, pady=(0, 2))
        self.combo_history = ttk.Combobox(self, state="readonly", values=[])
        self.combo_history.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.combo_history.bind("<<ComboboxSelected>>", lambda e: self._load_selected())

        self.history = []
        self._load_history()
        self._position_fields()
        self._update_ratios()

    # --- layout management -------------------------------------------------
    def _validate_int(self, text: str) -> bool:
        """Allow only empty string or digits (integer values)."""
        return text.isdigit() or text == ""

    def _load_layout(self):
        try:
            with open(TEE_LAYOUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            layout = {k: list(map(float, v)) for k, v in data.items() if isinstance(v, (list, tuple)) and len(v) == 2}
        except Exception:
            layout = {}
        for k, v in DEFAULT_LAYOUT.items():
            layout.setdefault(k, v)
        return layout

    def _save_layout(self):
        try:
            with open(TEE_LAYOUT_FILE, "w", encoding="utf-8") as f:
                json.dump(self.layout, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def set_edit_mode(self, enabled: bool) -> None:
        """Enable or disable field-position editing."""
        self.edit_mode = bool(enabled)
        if not self.edit_mode:
            self._save_layout()

    def _position_fields(self):
        w = max(self.canvas.winfo_width(), 1)
        h = max(self.canvas.winfo_height(), 1)
        for name, frame in self.fields.items():
            relx, rely = self.layout.get(name, (0.0, 0.0))
            x = relx * w
            y = rely * h
            self.canvas.coords(name, x, y)

    def _drag_start(self, name, event):
        if not self.edit_mode:
            return
        self._drag_name = name
        self._drag_offset = (event.x, event.y)
        return "break"

    def _drag_move(self, name, event):
        if not self.edit_mode or self._drag_name != name:
            return
        x = event.x_root - self.canvas.winfo_rootx() - self._drag_offset[0]
        y = event.y_root - self.canvas.winfo_rooty() - self._drag_offset[1]
        self.canvas.coords(name, x, y)
        return "break"

    def _drag_stop(self, name, event):
        if not self.edit_mode or self._drag_name != name:
            return
        self._drag_name = None
        x, y = self.canvas.coords(name)
        w = max(self.canvas.winfo_width(), 1)
        h = max(self.canvas.winfo_height(), 1)
        self.layout[name] = [x / w, y / h]
        self._save_layout()
        return "break"

    # --- image handling ----------------------------------------------------
    def set_image(self, pil):
        """Attach PIL image as background of the tee panel."""
        self._pil_raw = pil
        if pil is None:
            self._photo = None
            self.canvas.config(width=374, height=288)
            self.canvas.delete("img")
            self._position_fields()
            return
        w = 374
        h = int(w * pil.height / pil.width) if pil.width else 288
        self._photo = ImageTk.PhotoImage(pil.resize((w, h), Image.LANCZOS))
        self.canvas.config(width=w, height=h)
        self.canvas.delete("img")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw", tags="img")
        self._position_fields()

    def enlarge_image(self):
        """Enlarge sketch image and reposition fields proportionally."""
        if not self._pil_raw:
            return
        current_w = self.canvas.winfo_width() or 1
        new_w = int(current_w * 1.2)
        pil = self._pil_raw
        new_h = int(new_w * pil.height / pil.width) if pil.width else self.canvas.winfo_height()
        self._photo = ImageTk.PhotoImage(pil.resize((new_w, new_h), Image.LANCZOS))
        self.canvas.config(width=new_w, height=new_h)
        self.canvas.delete("img")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw", tags="img")
        self._position_fields()

    # --- history helpers ---------------------------------------------------
    def _load_history(self):
        try:
            with open(TEE_HISTORY_FILE, "r", encoding="utf-8") as f:
                self.history = json.load(f)
        except Exception:
            self.history = []
        self._update_history_combo()

    def _save_history(self):
        try:
            with open(TEE_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history[:20], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _save_current(self):
        """Store current tee parameters in history.

        Ln is optional; it will be saved only if provided and numeric.
        Required numeric fields: Fn, Fc, Fo, Lo, Lc.
        """
        try:
            entry = {name: float(self.vars[name].get()) for name in ("Fn", "Fc", "Lc", "Fo", "Lo")}
        except ValueError:
            messagebox.showwarning(
                "Трійник",
                "Введіть числові значення для Fn, Fc, Fo, Lo та Lc",
            )
            return

        ln_text = self.vars["Ln"].get().strip()
        if ln_text:
            try:
                entry["Ln"] = float(ln_text)
            except ValueError:
                pass

        self.history.insert(0, entry)
        self.history = self.history[:20]
        self._save_history()
        self._update_history_combo()

    def _toggle_auto(self):
        """Toggle automatic transfer of ratios to the main calculator."""
        self.auto_mode = not self.auto_mode
        self.btn_auto.config(text="Авто" if self.auto_mode else "Ручна")
        if self.auto_mode:
            # push current ratios immediately
            self._update_ratios()

    def _update_history_combo(self):
        items = [f"Fn={h['Fn']} Fc={h['Fc']} Fo={h['Fo']}" for h in self.history]
        self.combo_history["values"] = items
        if items:
            self.combo_history.current(0)

    def _load_selected(self):
        idx = self.combo_history.current()
        if idx < 0 or idx >= len(self.history):
            return
        h = self.history[idx]
        for name in ("Fn", "Ln", "Fc", "Lc", "Fo", "Lo"):
            self.vars[name].set(str(h.get(name, "")))
        self._update_ratios()

    # --- ratio computation -------------------------------------------------
    def _update_ratios(self):
        fn_fc = fo_fc = lo_lc = None
        try:
            fn = float(self.vars["Fn"].get())
            fc = float(self.vars["Fc"].get())
            fn_fc = fn * fn / (fc * fc)
            self.lbl_fn_fc.config(text=f"Fn/Fc={fn_fc:.2f}")
        except Exception:
            self.lbl_fn_fc.config(text="Fn/Fc=—")
        try:
            fo = float(self.vars["Fo"].get())
            fc = float(self.vars["Fc"].get())
            fo_fc = fo * fo / (fc * fc)
            self.lbl_fo_fc.config(text=f"Fo/Fc={fo_fc:.2f}")
        except Exception:
            self.lbl_fo_fc.config(text="Fo/Fc=—")
        try:
            lo = float(self.vars["Lo"].get())
            lc = float(self.vars["Lc"].get())
            lo_lc = lo / lc
            self.lbl_lo_lc.config(text=f"Lo/Lc={lo_lc:.2f}")
        except Exception:
            self.lbl_lo_lc.config(text="Lo/Lc=—")

        if self.on_ratios and self.auto_mode and None not in (fn_fc, fo_fc, lo_lc):
            self.on_ratios(fn_fc, fo_fc, lo_lc)
