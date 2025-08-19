import os
import math
from typing import Optional, Tuple

import tkinter as tk
from tkinter import messagebox, simpledialog
from PIL import Image, ImageTk

from models import Panel, ImageEntry, Curve


class CanvasMixin:
    def _rotate_point(self, x: float, y: float, angle_deg: float, cx: float, cy: float):
        if not angle_deg:
            return x, y
        a = math.radians(angle_deg)
        dx, dy = x - cx, y - cy
        return (
            cx + dx * math.cos(a) - dy * math.sin(a),
            cy + dx * math.sin(a) + dy * math.cos(a),
        )

    def img_to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        ox, oy = self.offset
        if self.current_image:
            iw, ih = self.current_image.size
            x, y = self._rotate_point(
                x, y, getattr(self.current_image, "tilt_deg", 0.0), iw / 2, ih / 2
            )
        return ox + x * self.scale, oy + y * self.scale

    def canvas_to_img(self, x: float, y: float) -> Tuple[float, float]:
        ox, oy = self.offset
        if self.scale == 0:
            xi, yi = x, y
        else:
            xi, yi = (x - ox) / self.scale, (y - oy) / self.scale
        if self.current_image:
            iw, ih = self.current_image.size
            xi, yi = self._rotate_point(
                xi, yi, -getattr(self.current_image, "tilt_deg", 0.0), iw / 2, ih / 2
            )
        return xi, yi

    def on_mouse_wheel(self, e):
        self.zoom_at(1.1 if e.delta > 0 else 0.9, (e.x, e.y))

    def zoom_at(self, factor: float, focus_xy: Optional[Tuple[int, int]]):
        if self.get_current_pil() is None:
            return
        new_scale = max(0.2, min(10.0, self.scale * factor))
        if focus_xy is None:
            focus_xy = (
                self.canvas.winfo_width() // 2,
                self.canvas.winfo_height() // 2,
            )
        fx, fy = focus_xy
        ix, iy = self.canvas_to_img(fx, fy)
        self.scale = new_scale
        cx, cy = self.img_to_canvas(ix, iy)
        dx, dy = fx - cx, fy - cy
        ox, oy = self.offset
        self.offset = (ox + dx, oy + dy)
        self.redraw()

    def reset_zoom_100(self):
        self.scale = 1.0
        self.offset = (20.0, 20.0)
        self.redraw()

    def fit_to_view(self):
        pil = self.get_current_pil()
        if pil is None:
            return
        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())
        iw, ih = pil.size
        s = min((cw - 40) / iw, (ch - 40) / ih)
        self.scale = max(0.2, min(10.0, s))
        self.offset = ((cw - iw * self.scale) / 2, (ch - ih * self.scale) / 2)
        self.redraw()

    def on_pan_start(self, e):
        self._pan_start = (e.x, e.y)
        self.canvas.config(cursor="fleur")

    def on_pan_move(self, e):
        if not self._pan_start:
            return
        x0, y0 = self._pan_start
        dx, dy = e.x - x0, e.y - y0
        ox, oy = self.offset
        self.offset = (ox + dx, oy + dy)
        self._pan_start = (e.x, e.y)
        self.redraw()

    def on_pan_end(self, e):
        self._pan_start = None
        self.canvas.config(cursor="crosshair")

    def redraw(self):
        self.canvas.delete("all")
        pil = self.get_current_pil()
        if not pil:
            self.status.config(text="(Немає вибраного фото)")
            return
        iw, ih = pil.size
        key = f"{self.current_image.image_name}@{int(iw*self.scale)}x{int(ih*self.scale)}"
        if key not in self._tk_cache:
            view = pil.resize(
                (max(1, int(iw * self.scale)), max(1, int(ih * self.scale))),
                Image.LANCZOS,
            )
            self._tk_cache[key] = ImageTk.PhotoImage(view)
        ox, oy = self.offset
        self.canvas.create_image(ox, oy, anchor="nw", image=self._tk_cache[key])

        if self.current_image:
            for p in self.current_image.panels:
                self.draw_panel_box(p, outline="#00FF88", width=2)
            if self.current_panel:
                self.draw_panel_box(self.current_panel, outline="#FFD966", width=3)
                self.draw_axis_x(self.current_panel)

        if self.current_image and self.current_image.axis_y.points:
            self.draw_axis_y(self.current_image)

        if self.current_panel and self.current_image:
            self.draw_curves(self.current_panel, self.current_image)

        imname = (
            os.path.basename(self.current_image.image_name)
            if self.current_image
            else "-"
        )
        panel_txt = (
            f"Fn/fc={self.current_panel.fn_fc:g}" if self.current_panel else "—"
        )
        self.status.config(
            text=f"Фото: {imname}  |  Панель: {panel_txt}  |  Режим: {self.mode}  |  Масштаб: {self.scale:.2f}"
        )

    def draw_panel_box(self, p: Panel, outline="#00FF88", width=2):
        x0, y0, x1, y1 = p.roi
        self.canvas.create_rectangle(
            *self.img_to_canvas(x0, y0),
            *self.img_to_canvas(x1, y1),
            outline=outline,
            width=width,
        )
        self.canvas.create_text(
            *self.img_to_canvas((x0 + x1) / 2, y0 - 14),
            text=f"Fn/fc={p.fn_fc:g}",
            fill=outline,
            font=("Segoe UI", 9, "bold"),
        )
        if self.mode == "panel_edit" and p is self.current_panel:
            for tag, (px, py) in self._roi_handles_coords(p.roi).items():
                x, y = self.img_to_canvas(px, py)
                self.canvas.create_rectangle(
                    x - 4,
                    y - 4,
                    x + 4,
                    y + 4,
                    outline="#FFD966",
                    fill="#1f1f1f",
                    tags=("roi_handle", tag),
                )

    def draw_axis_y(self, im: ImageEntry):
        iw, ih = im.size
        angle = getattr(im, "axis_y_tilt_deg", 0.0)
        pivot_x, pivot_y = 0, ih
        for (py, val) in im.axis_y.points:
            x1, y1 = self._rotate_point(0, py, angle, pivot_x, pivot_y)
            x2, y2 = self._rotate_point(iw, py, angle, pivot_x, pivot_y)
            self.canvas.create_line(
                *self.img_to_canvas(x1, y1),
                *self.img_to_canvas(x2, y2),
                fill="#1E90FF",
                dash=(3, 3),
            )
            ax, ay = self._rotate_point(10, py, angle, pivot_x, pivot_y)
            cx, cy = self.img_to_canvas(ax, ay)
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            cy = max(0, min(ch, cy))
            self.canvas.create_oval(
                cx - 4,
                cy - 4,
                cx + 4,
                cy + 4,
                outline="#1E90FF",
                fill="#0c0c0c",
                width=2,
            )
            self.canvas.create_text(
                4,
                cy,
                text=f"{val:g}",
                fill="#1E90FF",
                anchor="w",
                font=("Segoe UI", 12),
            )

    def draw_axis_x(self, p: Panel):
        x0, y0, x1, y1 = p.roi
        angle = getattr(p, "axis_x_tilt_deg", 0.0)
        for (u, val) in p.axis_x.points:
            px = x0 + u
            pivot_x, pivot_y = px, y1
            py_top, py_bot = y0, y1
            x_top, y_top = self._rotate_point(px, py_top, angle, pivot_x, pivot_y)
            x_bot, y_bot = self._rotate_point(px, py_bot, angle, pivot_x, pivot_y)
            x_lbl, y_lbl = self._rotate_point(px, y1 - 6, angle, pivot_x, pivot_y)
            cx, cy = self.img_to_canvas(x_lbl, y_lbl)
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            cx = max(0, min(cw, cx))
            self.canvas.create_line(
                *self.img_to_canvas(x_top, y_top),
                *self.img_to_canvas(x_bot, y_bot),
                fill="#00FF66",
                dash=(3, 3),
            )
            self.canvas.create_oval(
                cx - 4,
                cy - 4,
                cx + 4,
                cy + 4,
                outline="#00FF66",
                fill="#0c0c0c",
                width=2,
            )
            self.canvas.create_text(
                cx,
                ch - 2,
                text=f"{val:g}",
                fill="#00FF66",
                font=("Segoe UI", 12),
                anchor="s",
            )

    def draw_curves(self, p: Panel, im: ImageEntry):
        x0, y0, x1, y1 = p.roi
        for lab, cur in sorted(p.curves.items(), key=lambda t: t[0]):
            pts = sorted(cur.points_xy, key=lambda t: t[0])
            prev = None
            for i, (xv, yv) in enumerate(pts):
                try:
                    u = p.axis_x.inverse(xv)
                    v = im.axis_y.inverse(yv)
                except Exception:
                    continue
                px = x0 + u
                py = v
                px, py = self._rotate_point(px, py, getattr(p, "axis_x_tilt_deg", 0.0), px, y1)
                px, py = self._rotate_point(px, py, getattr(im, "axis_y_tilt_deg", 0.0), 0, im.size[1])
                cx, cy = self.img_to_canvas(px, py)
                if prev is not None:
                    self.canvas.create_line(prev[0], prev[1], cx, cy, fill="#FFD966", width=2)
                prev = (cx, cy)
                self.canvas.create_oval(
                    cx - 4,
                    cy - 4,
                    cx + 4,
                    cy + 4,
                    outline="#FFD966",
                    width=2,
                    tags=("curve_point", str(lab), str(i)),
                )
                self.canvas.create_line(
                    *self.img_to_canvas(x0, py),
                    *self.img_to_canvas(px, py),
                    fill="#666",
                    dash=(2, 2),
                )
                self.canvas.create_line(
                    *self.img_to_canvas(px, y0),
                    *self.img_to_canvas(px, py),
                    fill="#666",
                    dash=(2, 2),
                )
            if pts:
                try:
                    mx = sum(t[0] for t in pts) / len(pts)
                    my = sum(t[1] for t in pts) / len(pts)
                    mu = p.axis_x.inverse(mx)
                    mv = im.axis_y.inverse(my)
                    px, py = x0 + mu, mv
                    px, py = self._rotate_point(px, py, getattr(p, "axis_x_tilt_deg", 0.0), px, y1)
                    px, py = self._rotate_point(px, py, getattr(im, "axis_y_tilt_deg", 0.0), 0, im.size[1])
                    cx, cy = self.img_to_canvas(px, py)
                    self.canvas.create_text(
                        cx + 6,
                        cy,
                        text=f"Lo/Lc={lab:g}",
                        fill="#FFD966",
                        anchor="w",
                        font=("Segoe UI", 8, "bold"),
                        tags=("curve_label", str(lab)),
                    )
                except Exception:
                    pass
            if self.project.extrapolate and cur.is_ready() and p.axis_x.is_ready():
                try:
                    x_min_curve, x_max_curve = cur.x_span()
                    ax_min, ax_max = p.axis_x.value_range()
                    if ax_min is not None and ax_max is not None:
                        if ax_min < x_min_curve and len(pts) >= 2:
                            x1, y1 = pts[0]
                            x2, y2 = pts[1]
                            if x2 != x1:
                                y_ext = y1 + (y2 - y1) * ((ax_min - x1) / (x2 - x1))
                                u_ext = p.axis_x.inverse(ax_min)
                                u1 = p.axis_x.inverse(x1)
                                v_ext = im.axis_y.inverse(y_ext)
                                v1 = im.axis_y.inverse(y1)
                                x_a, y_a = x0 + u_ext, v_ext
                                x_b, y_b = x0 + u1, v1
                                x_a, y_a = self._rotate_point(x_a, y_a, getattr(p, "axis_x_tilt_deg", 0.0), x_a, y1)
                                x_a, y_a = self._rotate_point(x_a, y_a, getattr(im, "axis_y_tilt_deg", 0.0), 0, im.size[1])
                                x_b, y_b = self._rotate_point(x_b, y_b, getattr(p, "axis_x_tilt_deg", 0.0), x_b, y1)
                                x_b, y_b = self._rotate_point(x_b, y_b, getattr(im, "axis_y_tilt_deg", 0.0), 0, im.size[1])
                                self.canvas.create_line(
                                    *self.img_to_canvas(x_a, y_a),
                                    *self.img_to_canvas(x_b, y_b),
                                    fill="#EBCB8B",
                                    dash=(4, 3),
                                )
                        if ax_max > x_max_curve and len(pts) >= 2:
                            x1, y1 = pts[-2]
                            x2, y2 = pts[-1]
                            if x2 != x1:
                                y_ext = y2 + (y2 - y1) * ((ax_max - x2) / (x2 - x1))
                                u2 = p.axis_x.inverse(ax_max)
                                u1 = p.axis_x.inverse(x2)
                                v_ext = im.axis_y.inverse(y_ext)
                                v1 = im.axis_y.inverse(y2)
                                x_a, y_a = x0 + u1, v1
                                x_b, y_b = x0 + u2, v_ext
                                x_a, y_a = self._rotate_point(x_a, y_a, getattr(p, "axis_x_tilt_deg", 0.0), x_a, y1)
                                x_a, y_a = self._rotate_point(x_a, y_a, getattr(im, "axis_y_tilt_deg", 0.0), 0, im.size[1])
                                x_b, y_b = self._rotate_point(x_b, y_b, getattr(p, "axis_x_tilt_deg", 0.0), x_b, y1)
                                x_b, y_b = self._rotate_point(x_b, y_b, getattr(im, "axis_y_tilt_deg", 0.0), 0, im.size[1])
                                self.canvas.create_line(
                                    *self.img_to_canvas(x_a, y_a),
                                    *self.img_to_canvas(x_b, y_b),
                                    fill="#EBCB8B",
                                    dash=(4, 3),
                                )
                except Exception:
                    pass

    def on_left_press(self, e):
        pil = self.get_current_pil()
        if not pil:
            return
        ix, iy = self.canvas_to_img(e.x, e.y)
        if self.mode == "panel_roi":
            self.roi_start = (ix, iy)
            if getattr(self, "roi_rect", None):
                self.canvas.delete(self.roi_rect)
            self.roi_rect = self.canvas.create_rectangle(
                e.x, e.y, e.x, e.y, outline="#00FF88", width=2, dash=(4, 2)
            )
            return
        if self.mode == "panel_edit" and self.current_panel:
            hit = self._hit_roi_handle(ix, iy, self.current_panel.roi)
            if hit:
                self._roi_drag_kind = hit
                self._roi_start_mouse = (ix, iy)
                self._roi_start_roi = self.current_panel.roi
                return
            x0, y0, x1, y1 = self.current_panel.roi
            if x0 <= ix <= x1 and y0 <= iy <= y1:
                self._roi_drag_kind = "move"
                self._roi_start_mouse = (ix, iy)
                self._roi_start_roi = self.current_panel.roi
                return
        if self.mode == "calib_y":
            val = self.ask_float("Калібрування Y (ζ)", "Значення ζ:", None)
            if val is None:
                return
            self.current_image.axis_y.add_point(iy, val)
            self.current_image.y_marks.append((iy, ix, val))
            self.redraw()
            return
        if self.mode == "calib_x":
            if not self.current_panel:
                return
            x0, y0, x1, y1 = self.current_panel.roi
            if not (x0 <= ix <= x1 and y0 <= iy <= y1):
                messagebox.showwarning("Панель", "Клік має бути в межах панелі.")
                return
            val = self.ask_float("Калібрування X (fo/fc)", "Значення fo/fc:", None)
            if val is None:
                return
            u = ix - x0
            self.current_panel.axis_x.add_point(u, val)
            self.current_panel.x_marks.append((u, iy, val))
            self.redraw()
            return
        if self.mode == "curve_add":
            if not (self.current_panel and self.current_image):
                return
            x0, y0, x1, y1 = self.current_panel.roi
            if not (x0 <= ix <= x1 and y0 <= iy <= y1):
                return
            try:
                xv = self.current_panel.axis_x.eval(ix - x0)
                yv = self.current_image.axis_y.eval(iy)
            except Exception as ex:
                messagebox.showwarning(
                    "Калібрування", f"Спершу відкалібруй X і Y. Деталі: {ex}"
                )
                return
            cur = self.current_panel.curves[self.active_curve_label]
            cur.add_xy(xv, yv)
            self.redraw()
            self.refresh_calc_curves()
            return
        if self.mode == "axes_edit":
            hitY = self._hit_axis_y_anchor(iy)
            if hitY is not None:
                self.selected_axis = ("Y", hitY)
                self.dragging = True
                return
            hitX = self._hit_axis_x_anchor(ix)
            if hitX is not None:
                self.selected_axis = ("X", hitX)
                self.dragging = True
                return
        hit = self.hit_curve_point(ix, iy)
        self.selected_point = hit if hit else None
        self.dragging = bool(hit)
        self.redraw()

    def on_left_drag(self, e):
        ix, iy = self.canvas_to_img(e.x, e.y)
        if (
            self.mode == "panel_edit"
            and self.current_panel
            and self._roi_drag_kind
            and self._roi_start_roi
        ):
            self._apply_roi_drag(ix, iy)
            self.redraw()
            return
        if self.mode == "axes_edit" and self.dragging and self.selected_axis:
            kind, idx = self.selected_axis
            if kind == "Y":
                self.current_image.axis_y.move_pixel(idx, iy)
            else:
                x0, y0, x1, y1 = self.current_panel.roi
                u = max(0.0, min(ix - x0, x1 - x0))
                self.current_panel.axis_x.move_pixel(idx, u)
            self.redraw()
            return
        if self.dragging and self.selected_point and self.current_panel and self.current_image:
            lab, idx = self.selected_point
            cur = self.current_panel.curves.get(lab)
            if cur is None or not (0 <= idx < len(cur.points_xy)):
                return
            x0, y0, x1, y1 = self.current_panel.roi
            if not (x0 <= ix <= x1 and y0 <= iy <= y1):
                return
            try:
                xv = self.current_panel.axis_x.eval(ix - x0)
                yv = self.current_image.axis_y.eval(iy)
            except Exception:
                return
            cur.points_xy[idx] = (xv, yv)
            self.redraw()

    def on_left_release(self, e):
        if self.mode == "panel_roi" and self.roi_start and getattr(self, "roi_rect", None):
            ix0, iy0 = self.roi_start
            ix1, iy1 = self.canvas_to_img(e.x, e.y)
            x0 = int(round(min(ix0, ix1)))
            y0 = int(round(min(iy0, iy1)))
            x1 = int(round(max(ix0, ix1)))
            y1 = int(round(max(iy0, iy1)))
            self.canvas.delete(self.roi_rect)
            self.roi_rect = None
            self.roi_start = None
            self.set_mode_idle()
            if x1 - x0 < 10 or y1 - y0 < 10:
                messagebox.showwarning("Панель", "Надто малий прямокутник.")
                return
            s = simpledialog.askstring("Fn/fc", "Введи Fn/fc для цієї панелі:", parent=self)
            if not s:
                return
            try:
                val = float(s.replace(",", "."))
            except:
                messagebox.showwarning("Fn/fc", "Це має бути число.")
                return
            p = Panel(fn_fc=val, roi=(x0, y0, x1, y1))
            self.current_image.panels.append(p)
            self.current_panel = p
            self.refresh_panel_list()
            self.redraw()
            self.refresh_calc_panels()
            self.combo_fnfc.set(f"{p.fn_fc:g}")
            self.refresh_calc_curves()
        self.dragging = False
        self._roi_drag_kind = None
        self._roi_start_mouse = None
        self._roi_start_roi = None

    def on_right_click(self, e):
        ix, iy = self.canvas_to_img(e.x, e.y)
        menu = tk.Menu(self, tearoff=0)
        pt = self.hit_curve_point(ix, iy)
        if pt and self.current_panel:
            lab, idx = pt
            cur = self.current_panel.curves.get(lab)
            if not cur:
                return
            def do_rename():
                s = simpledialog.askstring(
                    "Перейменувати криву", "Нове Lo/Lc:", initialvalue=f"{lab:g}"
                )
                if not s:
                    return
                try:
                    newlab = float(s.replace(",", "."))
                except:
                    return
                if newlab == lab:
                    return
                if newlab in self.current_panel.curves:
                    messagebox.showwarning("Lo/Lc", "Крива з таким Lo/Lc вже існує.")
                    return
                self.current_panel.curves[newlab] = self.current_panel.curves.pop(lab)
                self.current_panel.curves[newlab].label = newlab
                self.redraw()
                self.refresh_calc_curves()
            def do_add_here():
                try:
                    xv = self.current_panel.axis_x.eval(ix - self.current_panel.roi[0])
                    yv = self.current_image.axis_y.eval(iy)
                except Exception:
                    return
                cur.add_xy(xv, yv)
                self.redraw()
            def do_delete_point():
                if 0 <= idx < len(cur.points_xy):
                    del cur.points_xy[idx]
                    self.redraw()
                    self.refresh_calc_curves()
            def do_delete_curve():
                if messagebox.askyesno("Видалити криву", f"Lo/Lc={lab:g}?"):
                    del self.current_panel.curves[lab]
                    self.redraw()
                    self.refresh_calc_curves()
            menu.add_command(label=f"Крива Lo/Lc={lab:g}")
            menu.add_separator()
            menu.add_command(label="Перейменувати криву…", command=do_rename)
            menu.add_command(label="Додати точку тут", command=do_add_here)
            menu.add_command(label="Видалити точку", command=do_delete_point)
            menu.add_command(label="Видалити криву", command=do_delete_curve)
            menu.post(e.x_root, e.y_root)
            return
        if self.current_panel and self.current_image:
            x0, y0, x1, y1 = self.current_panel.roi
            if x0 <= ix <= x1 and y0 <= iy <= y1 and self.current_panel.curves:
                sub = tk.Menu(menu, tearoff=0)
                def add_to_curve(label):
                    try:
                        xv = self.current_panel.axis_x.eval(ix - x0)
                        yv = self.current_image.axis_y.eval(iy)
                    except Exception:
                        return
                    cur = self.current_panel.curves.get(label)
                    if cur is None:
                        cur = Curve(label=label)
                        self.current_panel.curves[label] = cur
                    cur.add_xy(xv, yv)
                    self.redraw()
                for lab in sorted(self.current_panel.curves.keys()):
                    sub.add_command(
                        label=f"Lo/Lc={lab:g}",
                        command=lambda l=lab: add_to_curve(l),
                    )
                menu.add_cascade(label="Додати точку у криву…", menu=sub)
                menu.post(e.x_root, e.y_root)
                return
        if self.mode in ("axes_edit", "calib_y", "calib_x"):
            y_idx = self._hit_axis_y_anchor(iy)
            if y_idx is not None:
                def edit_val():
                    val = self.ask_float(
                        "Значення ζ",
                        "Нове значення ζ:",
                        self.current_image.axis_y.points[y_idx][1],
                    )
                    if val is None:
                        return
                    self.current_image.axis_y.edit_value(y_idx, val)
                    self.redraw()
                def delete_pt():
                    self.current_image.axis_y.delete_point(y_idx)
                    self.redraw()
                menu.add_command(label="Змінити значення ζ…", command=edit_val)
                menu.add_command(label="Видалити точку", command=delete_pt)
                menu.post(e.x_root, e.y_root)
                return
            x_idx = self._hit_axis_x_anchor(ix)
            if x_idx is not None:
                def edit_val():
                    val = self.ask_float(
                        "Значення fo/fc",
                        "Нове значення fo/fc:",
                        self.current_panel.axis_x.points[x_idx][1],
                    )
                    if val is None:
                        return
                    self.current_panel.axis_x.edit_value(x_idx, val)
                    self.redraw()
                def delete_pt():
                    self.current_panel.axis_x.delete_point(x_idx)
                    self.redraw()
                menu.add_command(label="Змінити значення fo/fc…", command=edit_val)
                menu.add_command(label="Видалити точку", command=delete_pt)
                menu.post(e.x_root, e.y_root)
                return

    def hit_curve_point(self, ix: float, iy: float) -> Optional[Tuple[float, int]]:
        if not (self.current_panel and self.current_image):
            return None
        x0, y0, x1, y1 = self.current_panel.roi
        best = (None, None, 1e9)
        for lab, cur in self.current_panel.curves.items():
            for i, (xv, yv) in enumerate(cur.points_xy):
                try:
                    u = self.current_panel.axis_x.inverse(xv)
                    v = self.current_image.axis_y.inverse(yv)
                except Exception:
                    continue
                px = x0 + u
                py = v
                cx, cy = self.img_to_canvas(px, py)
                mx, my = self.img_to_canvas(ix, iy)
                d2 = (mx - cx) ** 2 + (my - cy) ** 2
                if d2 < best[2]:
                    best = (lab, i, d2)
        if best[0] is not None and best[2] <= (8 ** 2):
            return (best[0], best[1])
        return None

    def _hit_axis_y_anchor(self, iy: float) -> Optional[int]:
        if not self.current_image:
            return None
        best = (-1, 1e9)
        for idx, (py, val) in enumerate(self.current_image.axis_y.points):
            cx, cy = self.img_to_canvas(0, py)
            _, my = self.img_to_canvas(0, iy)
            d = abs(my - cy)
            if d < best[1]:
                best = (idx, d)
        return best[0] if best[1] <= 10 else None

    def _hit_axis_x_anchor(self, ix: float) -> Optional[int]:
        if not (self.current_panel and self.current_image):
            return None
        x0, y0, x1, y1 = self.current_panel.roi
        best = (-1, 1e9)
        for idx, (u, val) in enumerate(self.current_panel.axis_x.points):
            px = x0 + u
            mx, _ = self.img_to_canvas(ix, 0)
            cx, _ = self.img_to_canvas(px, 0)
            d = abs(mx - cx)
            if d < best[1]:
                best = (idx, d)
        return best[0] if best[1] <= 10 else None

    def _roi_handles_coords(self, roi):
        x0, y0, x1, y1 = roi
        return {
            "lt": (x0, y0),
            "rt": (x1, y0),
            "lb": (x0, y1),
            "rb": (x1, y1),
            "t": ((x0 + x1) / 2, y0),
            "b": ((x0 + x1) / 2, y1),
            "l": (x0, (y0 + y1) / 2),
            "r": (x1, (y0 + y1) / 2),
        }

    def _hit_roi_handle(self, ix, iy, roi) -> Optional[str]:
        for tag, (px, py) in self._roi_handles_coords(roi).items():
            cx, cy = self.img_to_canvas(px, py)
            mx, my = self.img_to_canvas(ix, iy)
            if abs(mx - cx) <= 8 and abs(my - cy) <= 8:
                return tag
        return None

    def _apply_roi_drag(self, ix, iy):
        if not (self._roi_drag_kind and self._roi_start_roi):
            return
        x0, y0, x1, y1 = self._roi_start_roi
        sx, sy = self._roi_start_mouse
        dx, dy = ix - sx, iy - sy
        kind = self._roi_drag_kind
        old_w = x1 - x0
        new = [x0, y0, x1, y1]
        if kind == "move":
            new = [x0 + dx, y0 + dy, x1 + dx, y1 + dy]
        else:
            if "l" in kind:
                new[0] = x0 + dx
            if "r" in kind:
                new[2] = x1 + dx
            if "t" in kind:
                new[1] = y0 + dy
            if "b" in kind:
                new[3] = y1 + dy
        x0n = int(round(min(new[0], new[2])))
        y0n = int(round(min(new[1], new[3])))
        x1n = int(round(max(new[0], new[2])))
        y1n = int(round(max(new[1], new[3])))
        self.current_panel.roi = (x0n, y0n, x1n, y1n)
        new_w = max(1, x1n - x0n)
        scale = 1.0 if old_w <= 0 else (new_w / old_w)
        self.current_panel.axis_x.points = [
            ((u * scale), v) for (u, v) in self.current_panel.axis_x.points
        ]
        self.current_panel.x_marks = [
            ((u * scale), y, v) for (u, y, v) in self.current_panel.x_marks
        ]
