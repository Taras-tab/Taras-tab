import io, os, json, zipfile
from typing import List, Tuple, Dict, Optional

import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox, ttk
from PIL import Image, ImageTk
from .canvas import CanvasMixin
from .tee import TeePanel

from models import AxisMap, Curve, Panel, ImageEntry, Project

# file that stores path to last opened project
LAST_PROJECT_FILE = os.path.join(os.path.expanduser("~"), ".coef_last_project")

# ----- увесь ваш клас App з монолітного скрипта без датакласів -----
# Код нижче ідентичний тому, що ви надали, починаючи
# з коментаря "# ----------------- Додаток -----------------".
# Змінено лише імпорти вище та вилучено блок `if __name__ == "__main__":`.
#
# (Повний код занадто довгий, тому тут його опущено.
# Скопіюйте свій клас `App` сюди без змін.)

class App(CanvasMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Калькулятор коефіцієнтів — v3.8")
        self.geometry("1320x900")
        self.minsize(1180, 820)

        self.project = Project()
        self.package: Dict[str, bytes] = {}
        self.package_path: Optional[str] = None
        self._pil: Dict[str, Image.Image] = {}
        self._tk_cache: Dict[str, ImageTk.PhotoImage] = {}

        self.current_image: Optional[ImageEntry] = None
        self.current_panel: Optional[Panel] = None

        self.mode = "idle"
        self.active_curve_label: Optional[float] = None
        self.selected_point: Optional[Tuple[float, int]] = None
        self.selected_axis: Optional[Tuple[str, int]] = None
        self.dragging = False

        self.scale = 1.0
        self.offset = (20.0, 20.0)
        self._pan_start = None

        self._roi_drag_kind: Optional[str] = None
        self._roi_start_mouse: Optional[Tuple[float, float]] = None
        self._roi_start_roi: Optional[Tuple[int, int, int, int]] = None

        self._build_ui()
        self._load_last_project()
        # ensure any initially loaded image fits the canvas once the window is ready
        self.after(100, self.fit_to_view)

    def _remember_last_project(self, path: str) -> None:
        try:
            with open(LAST_PROJECT_FILE, "w", encoding="utf-8") as f:
                f.write(path)
        except Exception:
            pass

    def _load_last_project(self) -> None:
        try:
            with open(LAST_PROJECT_FILE, "r", encoding="utf-8") as f:
                path = f.read().strip()
            if path and os.path.exists(path):
                self.open_project(path)
        except Exception:
            pass
    # ---------- UI ----------
    def _build_ui(self):
        self._build_menubar()

        top = ttk.Frame(self); top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)
        ttk.Button(top, text="Додати фото", command=self.add_image).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Нова панель (Fn/fc)", command=self.start_panel_roi).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Калібр. Y", command=self.set_mode_calib_y).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Калібр. X", command=self.set_mode_calib_x).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Крива +", command=self.set_mode_curve_add).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Вибір/Перетяг", command=self.set_mode_select_drag).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Ред. осі", command=self.set_mode_axes_edit).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Ред. панель", command=self.set_mode_panel_edit).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="–", width=3, command=lambda: self.zoom_at(0.9, None)).pack(side=tk.LEFT, padx=(10,0))
        ttk.Button(top, text="+", width=3, command=lambda: self.zoom_at(1.1, None)).pack(side=tk.LEFT, padx=(2,6))
        ttk.Button(top, text="100%", command=self.reset_zoom_100).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Вмістити", command=self.fit_to_view).pack(side=tk.LEFT, padx=2)

        center = ttk.Frame(self)
        center.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        center.columnconfigure(0, weight=4)
        center.columnconfigure(1, weight=1)

        # Канвас займає приблизно 80% ширини, решта відведена під праву панель
        self.canvas = tk.Canvas(center, bg="#000000", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)  # Win
        self.canvas.bind("<Button-4>", lambda e: self.zoom_at(1.1, (e.x, e.y)))  # Linux
        self.canvas.bind("<Button-5>", lambda e: self.zoom_at(0.9, (e.x, e.y)))
        self.canvas.bind("<ButtonPress-2>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonRelease-2>", self.on_pan_end)
        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Button-3>", self.on_right_click)

        right = ttk.Frame(center)
        right.grid(row=0, column=1, sticky="ns", padx=8, pady=8)

        # Ескіз трійника з полями введення
        self.tee_panel = TeePanel(right, on_ratios=self._tee_to_calc)

        # Вибір фото/панелі
        grp_sel = ttk.LabelFrame(right, text="Вибір фото та панелі"); grp_sel.pack(fill=tk.X, pady=6)
        row = ttk.Frame(grp_sel); row.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(row, text="Фото:").pack(side=tk.LEFT)
        self.combo_image = ttk.Combobox(row, state="readonly", width=28, values=[])
        self.combo_image.pack(side=tk.LEFT, padx=4)
        self.combo_image.bind("<<ComboboxSelected>>", lambda e: self.select_image_by_combo())
        ttk.Button(row, text="◀", width=3, command=lambda: self.step_image(-1)).pack(side=tk.LEFT, padx=(6,2))
        ttk.Button(row, text="▶", width=3, command=lambda: self.step_image(+1)).pack(side=tk.LEFT, padx=2)

        ttk.Label(grp_sel, text="Панелі (Fn/fc):").pack(anchor="w", padx=6)
        self.list_panels = tk.Listbox(grp_sel, height=6)
        self.list_panels.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0,6))
        self.list_panels.bind("<<ListboxSelect>>", lambda e: self.select_panel_from_list())

        # Калькулятор
        grp_calc = ttk.LabelFrame(right, text="Калькулятор ζ (обидві групи)"); grp_calc.pack(fill=tk.X, pady=6)
        frm = ttk.Frame(grp_calc); frm.pack(fill=tk.X, padx=6, pady=6)
        # Порядок: Fn/Fc -> Fo/Fc -> Lo/Lc
        ttk.Label(frm, text="Fn/fc:").grid(row=0, column=0, sticky="e")
        self.combo_fnfc = ttk.Combobox(frm, state="readonly", width=18, values=[])
        self.combo_fnfc.grid(row=0, column=1, padx=4)
        self.combo_fnfc.bind("<<ComboboxSelected>>", lambda e: self.refresh_calc_curves())
        ttk.Label(frm, text="fo/fc:").grid(row=1, column=0, sticky="e")
        self.entry_x = ttk.Entry(frm, width=20); self.entry_x.grid(row=1, column=1, padx=4)
        ttk.Label(frm, text="Lo/Lc:").grid(row=2, column=0, sticky="e")
        self.combo_curve = ttk.Combobox(frm, state="normal", width=18, values=[])
        self.combo_curve.grid(row=2, column=1, padx=4)

        ttk.Button(grp_calc, text="Обчислити ζ", command=self.compute_both).pack(fill=tk.X, padx=6, pady=(0,6))
        self.lbl_p = ttk.Label(grp_calc, text="ζ_п (прохід) = —", font=("Segoe UI", 11, "bold")); self.lbl_p.pack(anchor="w", padx=6)
        self.lbl_v = ttk.Label(grp_calc, text="ζ_в (відгал.) = —", font=("Segoe UI", 11, "bold")); self.lbl_v.pack(anchor="w", padx=6, pady=(0,2))
        self.lbl_src_p = ttk.Label(grp_calc, text="Джерело (прохід): —", wraplength=260, justify="left"); self.lbl_src_p.pack(anchor="w", padx=6)
        self.lbl_src_v = ttk.Label(grp_calc, text="Джерело (відгал.): —", wraplength=260, justify="left"); self.lbl_src_v.pack(anchor="w", padx=6, pady=(0,4))
        self.lbl_dev_p = ttk.Label(grp_calc, text="Відхилення від кривої (прохід): —", wraplength=260, justify="left"); self.lbl_dev_p.pack(anchor="w", padx=6)
        self.lbl_dev_v = ttk.Label(grp_calc, text="Відхилення від кривої (відгал.): —", wraplength=260, justify="left"); self.lbl_dev_v.pack(anchor="w", padx=6, pady=(0,8))

        self.status = ttk.Label(self, text="—", anchor="w"); self.status.pack(side=tk.BOTTOM, fill=tk.X)

        self.update_preview()

        # хоткеї
        self.bind("<Escape>", lambda e: self.set_mode_idle())
        self.bind("<Return>", lambda e: self.set_mode_idle())
        self.bind("<Delete>", lambda e: self.delete_selected_point())
        self.bind_all("<Control-n>", lambda e: self.new_project())
        self.bind_all("<Control-o>", lambda e: self.open_project())
        self.bind_all("<Control-s>", lambda e: self.save_project())
        # tilt adjust
        self.bind("[", lambda e: self.adjust_tilt(-0.2))
        self.bind("]", lambda e: self.adjust_tilt(+0.2))

    def _build_menubar(self):
        m = tk.Menu(self)
        m_file = tk.Menu(m, tearoff=0)
        m_file.add_command(label="Новий проєкт", command=self.new_project, accelerator="Ctrl+N")
        m_file.add_command(label="Відкрити…", command=self.open_project, accelerator="Ctrl+O")
        m_file.add_separator()
        m_file.add_command(label="Зберегти", command=self.save_project, accelerator="Ctrl+S")
        m_file.add_command(label="Зберегти як…", command=self.save_project_as)
        m_file.add_separator()
        m_file.add_command(label="Вихід", command=self.destroy, accelerator="Alt+F4")
        m.add_cascade(label="Файл", menu=m_file)

        m_edit = tk.Menu(m, tearoff=0)
        m_edit.add_command(label="Видалити фото", command=self.delete_image)
        m_edit.add_command(label="Видалити панель", command=self.delete_panel)
        m_edit.add_separator()
        m_edit.add_command(label="Очистити калібрування Y", command=lambda: self.clear_axis("Y"))
        m_edit.add_command(label="Очистити калібрування X", command=lambda: self.clear_axis("X"))
        m.add_cascade(label="Правка", menu=m_edit)

        m_view = tk.Menu(m, tearoff=0)
        m_view.add_command(label="Збільшити", command=lambda: self.zoom_at(1.1, None))
        m_view.add_command(label="Зменшити", command=lambda: self.zoom_at(0.9, None))
        m_view.add_command(label="100%", command=self.reset_zoom_100)
        m_view.add_command(label="Вмістити", command=self.fit_to_view)
        m_view.add_command(label="Вставити ескіз трійника…", command=self.load_sketch)
        m_view.add_separator()
        self.var_extrap = tk.BooleanVar(value=self.project.extrapolate)
        m_view.add_checkbutton(label="Екстраполяція коротких кривих", variable=self.var_extrap, command=self.toggle_extrapolate)
        m.add_cascade(label="Вигляд", menu=m_view)

        m_ins = tk.Menu(m, tearoff=0)
        m_ins.add_command(label="Додати фото…", command=self.add_image)
        m_ins.add_command(label="Нова панель (Fn/fc)…", command=self.start_panel_roi)
        m.add_cascade(label="Вставка", menu=m_ins)

        m_tools = tk.Menu(m, tearoff=0)
        m_tools.add_command(label="Калібрування Y", command=self.set_mode_calib_y)
        m_tools.add_command(label="Калібрування X", command=self.set_mode_calib_x)
        m_tools.add_command(label="Нова крива (Lo/Lc)…", command=self.set_mode_curve_add)
        m_tools.add_command(label="Вибір/Перетяг точок", command=self.set_mode_select_drag)
        m_tools.add_command(label="Редагування осей", command=self.set_mode_axes_edit)
        m_tools.add_command(label="Редагування панелі", command=self.set_mode_panel_edit)
        m_tools.add_command(label="Нахил осі…", command=self.set_axis_tilt)
        self.var_edit_fields = tk.BooleanVar(value=False)
        m_tools.add_checkbutton(label="Редагувати поля трійника", variable=self.var_edit_fields, command=self.toggle_tee_fields_edit)
        m_tools.add_command(label="Збільшити ескіз трійника", command=lambda: self.tee_panel.enlarge_image())
        m.add_cascade(label="Інструменти", menu=m_tools)

        m_help = tk.Menu(m, tearoff=0)
        m_help.add_command(label="Про програму", command=lambda: messagebox.showinfo("Про програму", "Калькулятор коефіцієнтів v3.8"))
        m.add_cascade(label="Довідка", menu=m_help)

        self.config(menu=m)

    def _tee_to_calc(self, fn_fc: float, fo_fc: float, lo_lc: float) -> None:
        """Populate calculator fields with ratios from the tee panel."""
        vals = [float(v.replace(",", ".")) for v in self.combo_fnfc["values"]]
        if vals:
            nearest = min(vals, key=lambda v: abs(v - fn_fc))
            self.combo_fnfc.set(f"{nearest:g}")
        else:
            self.combo_fnfc.set(f"{fn_fc:.2f}")

        self.entry_x.delete(0, tk.END)
        self.entry_x.insert(0, f"{fo_fc:.2f}")

        val_lo = f"{lo_lc:.2f}"
        vals = list(self.combo_curve["values"])
        if val_lo not in vals:
            vals.append(val_lo)
            self.combo_curve["values"] = vals
        self.combo_curve.set(val_lo)

    # ---------- Режими ----------
    def set_mode_idle(self): self._set_mode("idle", "Режим: очікування")
    def set_mode_calib_y(self): self._set_mode("calib_y", "Калібрування Y — клікайте по відомих рівнях ζ (сині мітки).")
    def set_mode_calib_x(self):
        if not self.current_panel: messagebox.showwarning("Панель", "Виберіть/створіть Панель (Fn/fc)."); return
        self._set_mode("calib_x", "Калібрування X (fo/fc) — клікайте в межах панелі (зелені мітки).")
    def set_mode_curve_add(self):
        if not self.current_panel: messagebox.showwarning("Панель", "Виберіть/створіть Панель (Fn/fc)."); return
        s = simpledialog.askstring("Нова крива", "Введіть Lo/Lc (наприклад 0.5):", parent=self)
        if not s: return
        try: lab = float(s.replace(",", "."))
        except: messagebox.showwarning("Lo/Lc", "Це має бути число."); return
        self.active_curve_label = lab
        if lab not in self.current_panel.curves: self.current_panel.curves[lab] = Curve(label=lab)
        self._set_mode("curve_add", f"Крива Lo/Lc={lab:g} — клікайте ЛКМ по кривій; Esc/Enter — завершити.")
        self.refresh_calc_panels(); self.refresh_calc_curves()
    def set_mode_select_drag(self): self._set_mode("select_drag", "Вибір/Перетяг точок кривих (ЛКМ), Delete — видалити.")
    def set_mode_axes_edit(self): self._set_mode("axes_edit", "Редагування осей: перетягайте маркери, ПКМ — змінити/видалити.")
    def set_mode_panel_edit(self): self._set_mode("panel_edit", "Редагування панелі: перетяг для зсуву, за ручки — зміна розміру.")
    def _set_mode(self, mode, text):
        self.mode = mode; self.selected_point = None; self.selected_axis = None; self.dragging = False
        self.status.config(text=text)

    # ---------- Проєкт/файли ----------
    def new_project(self):
        if not self.confirm_discard(): return
        self.project = Project(); self.package = {}; self.package_path = None
        self._pil.clear(); self._tk_cache.clear()
        self.current_image = None; self.current_panel = None
        self.refresh_image_combo(); self.list_panels.delete(0, tk.END)
        self.update_preview()
        self.reset_zoom_100(); self.redraw()

    def open_project(self, path: Optional[str] = None):
        if path is None:
            path = filedialog.askopenfilename(title="Відкрити проєкт (.kpz)", filetypes=[("КПЗ", "*.kpz")])
            if not path:
                return
        try:
            with zipfile.ZipFile(path, "r") as zf:
                self.package = {n: zf.read(n) for n in zf.namelist()}
            meta = self.package.get("project.json")
            if not meta:
                raise ValueError("project.json не знайдено.")
            self.project = Project.from_json(meta.decode("utf-8"))
            self.package_path = path
            self._pil.clear()
            self._tk_cache.clear()
            for im in self.project.images:
                if im.image_name not in self.package:
                    raise ValueError(f"Відсутнє зображення {im.image_name}")
                img = Image.open(io.BytesIO(self.package[im.image_name])).convert("RGB")
                self._pil[im.image_name] = img
                im.size = img.size
            self.refresh_image_combo()
            self.update_preview()
            self.fit_to_view()
            self._remember_last_project(path)
        except Exception as e:
            messagebox.showerror("Помилка відкриття", str(e))

    def save_project(self):
        if not self.package_path:
            self.save_project_as()
            return
        self._write_package(self.package_path)
        self._remember_last_project(self.package_path)

    def save_project_as(self):
        path = filedialog.asksaveasfilename(title="Зберегти як", defaultextension=".kpz",
                                            filetypes=[("КПЗ", "*.kpz")])
        if not path:
            return
        self._write_package(path)
        self.package_path = path
        self._remember_last_project(path)

    def _write_package(self, path: str):
        for im in self.project.images:
            if im.image_name not in self.package:
                pil = self._pil.get(im.image_name)
                if pil is None: raise ValueError(f"Немає даних для {im.image_name}")
                bio = io.BytesIO(); pil.save(bio, format="PNG"); self.package[im.image_name] = bio.getvalue()
        if self.project.sketch_name and self.project.sketch_name in self.package:
            pass
        self.package["project.json"] = self.project.to_json().encode("utf-8")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for n, d in self.package.items():
                zf.writestr(n, d)
        messagebox.showinfo("Збережено", f"Проєкт збережено:\n{path}")

    def add_image(self):
        path = filedialog.askopenfilename(title="Додати фото", filetypes=[("Зображення", "*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff")])
        if not path: return
        try: pil = Image.open(path).convert("RGB")
        except Exception as e: messagebox.showerror("Зображення", str(e)); return
        group = self.ask_choice("Група", "Вибери групу:", ["прохід", "відгалуження"])
        if not group: return
        base = os.path.splitext(os.path.basename(path))[0]; name = f"images/{base}.png"; i = 1
        while name in self.package: i += 1; name = f"images/{base}_{i}.png"
        bio = io.BytesIO(); pil.save(bio, format="PNG"); self.package[name] = bio.getvalue()
        ie = ImageEntry(group=group, image_name=name, size=pil.size)
        self.project.images.append(ie); self._pil[name] = pil
        self.refresh_image_combo(); self.select_image(ie); self.fit_to_view(); self.update_preview()

    def delete_image(self):
        if not self.current_image: return
        im = self.current_image
        ok = messagebox.askyesno("Видалити фото", f"Справді видалити: {os.path.basename(im.image_name)} ?")
        if not ok: return
        idx = self.project.images.index(im); del self.project.images[idx]
        self.current_image = self.project.images[idx - 1] if self.project.images else None
        self.current_panel = self.current_image.panels[0] if (self.current_image and self.current_image.panels) else None
        self.refresh_image_combo(); self.redraw(); self.refresh_calc_panels(); self.refresh_calc_curves(); self.update_preview()

    def delete_panel(self):
        if not (self.current_image and self.current_panel): return
        ok = messagebox.askyesno("Видалити панель", f"Справді видалити панель Fn/fc={self.current_panel.fn_fc:g}?")
        if not ok: return
        lst = self.current_image.panels; idx = lst.index(self.current_panel); del lst[idx]
        self.current_panel = lst[idx - 1] if lst else None
        self.refresh_panel_list(); self.redraw(); self.refresh_calc_panels(); self.refresh_calc_curves()

    def load_sketch(self):
        path = filedialog.askopenfilename(title="Ескіз", filetypes=[("Зображення", "*.png;*.jpg;*.jpeg;*.bmp")])
        if not path:
            return
        pil = Image.open(path).convert("RGB")
        self.project.sketch_name = "sketch.png"
        bio = io.BytesIO()
        pil.save(bio, format="PNG")
        self.package[self.project.sketch_name] = bio.getvalue()
        self.project.preview_source = "sketch"
        self.update_preview()

    def update_preview(self):
        if self.project.sketch_name and self.project.sketch_name in self.package:
            pil = Image.open(io.BytesIO(self.package[self.project.sketch_name])).convert("RGB")
            self.tee_panel.set_image(pil)
            self.project.preview_source = "sketch"
        else:
            self.tee_panel.set_image(None)
            self.project.preview_source = None

    # ---------- Вибір фото/панелі ----------
    def refresh_image_combo(self):
        items = [f"{os.path.basename(im.image_name)} — {im.group}" for im in self.project.images]
        self.combo_image["values"] = items
        if self.current_image is None and items:
            self.combo_image.set(items[0]); self.current_image = self.project.images[0]
        elif self.current_image:
            i = self.project.images.index(self.current_image)
            if i < len(items): self.combo_image.set(items[i])
        self.refresh_panel_list(); self.refresh_calc_panels()

    def select_image_by_combo(self):
        s = self.combo_image.get()
        for im in self.project.images:
            if s.startswith(os.path.basename(im.image_name)):
                self.select_image(im); break

    def select_image(self, im: ImageEntry):
        self.current_image = im
        self.current_panel = im.panels[0] if im.panels else None
        self.refresh_panel_list(); self.fit_to_view()
        if self.current_panel:
            self.combo_fnfc.set(f"{self.current_panel.fn_fc:g}")
            self.refresh_calc_curves()

    def step_image(self, step: int):
        if not self.project.images: return
        if self.current_image is None: self.select_image(self.project.images[0]); return
        i = self.project.images.index(self.current_image); i = (i + step) % len(self.project.images)
        self.select_image(self.project.images[i])

    def refresh_panel_list(self):
        self.list_panels.delete(0, tk.END)
        if not self.current_image: return
        for p in self.current_image.panels:
            self.list_panels.insert(tk.END, f"Fn/fc={p.fn_fc:g}  ({len(p.curves)} кривих)")
        if self.current_panel:
            idx = self.current_image.panels.index(self.current_panel); self.list_panels.select_set(idx)

    def select_panel_from_list(self):
        if not self.current_image: return
        sel = self.list_panels.curselection()
        if not sel: return
        idx = sel[0]
        if 0 <= idx < len(self.current_image.panels):
            self.current_panel = self.current_image.panels[idx]
            self.combo_fnfc.set(f"{self.current_panel.fn_fc:g}")
            self.refresh_calc_curves(); self.redraw()

    # ---------- ROI панелі ----------
    def start_panel_roi(self):
        if not self.current_image: messagebox.showwarning("Фото", "Спочатку додай і вибери фото."); return
        messagebox.showinfo("Панель (Fn/fc)", "Перетягни прямокутник на зображенні для виділення панелі (колонки).")
        self.mode = "panel_roi"
        self.roi_start = None; self.roi_rect = None

    # ---------- Калькулятор ----------
    def refresh_calc_panels(self):
        vals = set()
        for im in self.project.images:
            for p in im.panels: vals.add(p.fn_fc)
        lst = sorted(vals)
        self.combo_fnfc["values"] = [f"{v:g}" for v in lst]
        if lst and self.combo_fnfc.get() not in [f"{v:g}" for v in lst]:
            self.combo_fnfc.set(f"{lst[0]:g}")
        elif not lst:
            self.combo_fnfc.set("")
        self.refresh_calc_curves()

    def refresh_calc_curves(self):
        try: fnfc = float(self.combo_fnfc.get().replace(",", ".")); has = True
        except: has = False
        labels = set()
        for im in self.project.images:
            for p in im.panels:
                if not has or abs(p.fn_fc - fnfc) < 1e-12:
                    labels.update(p.curves.keys())
        lst = sorted([f"{l:g}" for l in labels], key=lambda s: float(s))
        self.combo_curve["values"] = lst
        if not self.combo_curve.get() and lst:
            self.combo_curve.set(lst[0])

    def _percent_distance_from_curve(self, cur: Curve, x: float) -> Optional[float]:
        span = cur.x_span()
        if span is None: return None
        xmin, xmax = span; width = max(xmax - xmin, 1e-12)
        if xmin <= x <= xmax: return 0.0
        delta = (xmin - x) if x < xmin else (x - xmax)
        return 100.0 * (delta / width)

    def _calc_group_value(self, group_name: str, fnfc: float, lab: float, x: float):
        panel_found = False
        range_found = False
        for im in self.project.images:
            if im.group != group_name:
                continue
            for p in im.panels:
                if abs(p.fn_fc - fnfc) > 1e-12:
                    continue
                panel_found = True
                ax_range = p.axis_x.value_range()
                if ax_range is None or not (ax_range[0] <= x <= ax_range[1]):
                    continue
                range_found = True
                # Точна крива
                if lab in p.curves:
                    cur = p.curves[lab]
                    if not cur.is_ready(): return ("замало точок", None, None, None, None, None)
                    y = cur.y_at_x(x, extrapolate=self.project.extrapolate)
                    pct = self._percent_distance_from_curve(cur, x)
                    out_flag = (y is None)
                    res = "X поза діапазоном" if y is None else f"{y:.2f}"
                    src = f"{os.path.basename(im.image_name)} | Fn/fc={p.fn_fc:g} | Lo/Lc={lab:g}"
                    return (res, im, p, pct, out_flag, src)
                # Інтерполяція між двома сусідніми Lo/Lc
                if p.curves:
                    keys = sorted(p.curves.keys())
                    low = None; high = None
                    for i in range(len(keys)-1):
                        if keys[i] <= lab <= keys[i+1]:
                            low = keys[i]; high = keys[i+1]; break
                    if low is None:
                        continue
                    c_low = p.curves[low]; c_high = p.curves[high]
                    if not (c_low.is_ready() and c_high.is_ready()): continue
                    y_low = c_low.y_at_x(x, extrapolate=self.project.extrapolate)
                    y_high = c_high.y_at_x(x, extrapolate=self.project.extrapolate)
                    if y_low is None or y_high is None:
                        res = "X поза діапазоном"
                        pct = None
                        if y_low is not None and y_high is None:
                            pct = self._percent_distance_from_curve(c_low, x)
                        elif y_high is not None and y_low is None:
                            pct = self._percent_distance_from_curve(c_high, x)
                        else:
                            pct = max(
                                v for v in [
                                    self._percent_distance_from_curve(c_low, x),
                                    self._percent_distance_from_curve(c_high, x)
                                ] if v is not None
                            ) if (self._percent_distance_from_curve(c_low, x) is not None or self._percent_distance_from_curve(c_high, x) is not None) else None
                        src = f"{os.path.basename(im.image_name)} | Fn/fc={p.fn_fc:g} | Lo/Lc≈{lab:g} (інтерп. між {low:g} і {high:g})"
                        return (res, im, p, pct, True, src)
                    t = (lab - low) / (high - low) if high != low else 0.0
                    y = y_low + t * (y_high - y_low)
                    pct = max(
                        v for v in [
                            self._percent_distance_from_curve(c_low, x),
                            self._percent_distance_from_curve(c_high, x)
                        ] if v is not None
                    ) if (self._percent_distance_from_curve(c_low, x) is not None or self._percent_distance_from_curve(c_high, x) is not None) else None
                    src = f"{os.path.basename(im.image_name)} | Fn/fc={p.fn_fc:g} | Lo/Lc≈{lab:g} (інтерп. між {low:g} і {high:g})"
                    return (f"{y:.2f}", im, p, pct, False, src)
        if panel_found and not range_found:
            return ("не існує", None, None, None, None, None)
        return ("нема даних", None, None, None, None, None)

    def compute_both(self):
        try: fnfc = float(self.combo_fnfc.get().replace(",", "."))
        except: messagebox.showwarning("Fn/fc", "Оберіть Fn/fc."); return
        try: x = float(self.entry_x.get().replace(",", "."))
        except: messagebox.showwarning("fo/fc", "Введіть fo/fc."); return
        try: lab = float(self.combo_curve.get().replace(",", "."))
        except: messagebox.showwarning("Lo/Lc", "Введіть/оберіть Lo/Lc."); return

        res_p, im_p, p_p, pct_p, out_p, src_p = self._calc_group_value("прохід", fnfc, lab, x)
        res_v, im_v, p_v, pct_v, out_v, src_v = self._calc_group_value("відгалуження", fnfc, lab, x)

        self.lbl_p.config(text=f"ζ_п (прохід) = {res_p}")
        self.lbl_v.config(text=f"ζ_в (відгал.) = {res_v}")
        self.lbl_src_p.config(text=("Джерело: —" if not src_p else f"Джерело: {src_p}"))
        self.lbl_src_v.config(text=("Джерело: —" if not src_v else f"Джерело: {src_v}"))

        def fmt_pct(pct, out_flag):
            if pct is None: return "—"
            s = f"{pct:.1f}%"
            if out_flag: s += " (поза діапазоном)"
            return s
        self.lbl_dev_p.config(text=f"Відхилення від кривої (прохід): {fmt_pct(pct_p, out_p)}")
        self.lbl_dev_v.config(text=f"Відхилення від кривої (відгал.): {fmt_pct(pct_v, out_v)}")

    def delete_selected_point(self):
        if not (self.selected_point and self.current_panel): return
        lab, idx = self.selected_point
        cur = self.current_panel.curves.get(lab)
        if cur and 0 <= idx < len(cur.points_xy):
            del cur.points_xy[idx]
            self.selected_point = None
            self.redraw()
            self.refresh_calc_curves()

    def adjust_tilt(self, delta_deg: float):
        if not self.current_image:
            return
        self.current_image.tilt_deg = getattr(self.current_image, "tilt_deg", 0.0) + float(delta_deg)
        self.status.config(text=f"Кут вирівнювання: {self.current_image.tilt_deg:+.1f}°")
        self.redraw()

    def set_axis_tilt(self):
        if not self.current_image:
            messagebox.showwarning("Нахил осі", "Спочатку додай і вибери фото.")
            return
        axis = simpledialog.askstring("Нахил осі", "Вісь (X або Y):", parent=self)
        if not axis:
            return
        axis = axis.upper()
        if axis not in ("X", "Y"):
            messagebox.showwarning("Вісь", "Введіть 'X' або 'Y'.")
            return
        angle = simpledialog.askfloat(
            "Нахил осі",
            "Кут [-10..10]°:",
            minvalue=-10.0,
            maxvalue=10.0,
            parent=self,
        )
        if angle is None:
            return
        angle = round(float(angle), 2)
        if axis == "X":
            if not self.current_panel:
                messagebox.showwarning("Панель", "Виберіть панель.")
                return
            self.current_panel.axis_x_tilt_deg = angle
        else:
            self.current_image.axis_y_tilt_deg = angle
        self.redraw()

    def toggle_extrapolate(self):
        self.project.extrapolate = bool(self.var_extrap.get())
        self.redraw()

    def toggle_tee_fields_edit(self):
        self.tee_panel.set_edit_mode(self.var_edit_fields.get())

    def clear_axis(self, which: str):
        if which == "Y":
            if self.current_image: self.current_image.axis_y.clear()
        else:
            if self.current_panel: self.current_panel.axis_x.clear()
        self.redraw()

    def confirm_discard(self) -> bool:
        return messagebox.askyesno("Підтвердити", "Почати спочатку/відкрити інший проєкт? Незбережені зміни буде втрачено.")

    def ask_choice(self, title, prompt, choices: List[str]) -> Optional[str]:
        dlg = tk.Toplevel(self); dlg.title(title); dlg.transient(self); dlg.grab_set()
        ttk.Label(dlg, text=prompt).pack(padx=10, pady=10)
        var = tk.StringVar(value=choices[0])
        combo = ttk.Combobox(dlg, state="readonly", values=choices, textvariable=var, width=18); combo.pack(padx=10, pady=6)
        ttk.Button(dlg, text="OK", command=dlg.destroy).pack(pady=8); dlg.wait_window(); return var.get()

    def get_current_pil(self):
        if not self.current_image: return None
        return self._pil.get(self.current_image.image_name)

    def ask_float(self, title, prompt, initial=None):
        s = simpledialog.askstring(title, prompt, initialvalue=("" if initial is None else f"{initial:g}"), parent=self)
        if s is None: return None
        try: return float(s.replace(",", "."))
        except: messagebox.showwarning("Число", "Введіть коректне число."); return None
