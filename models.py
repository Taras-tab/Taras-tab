from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class AxisMap:
    """Map pixel positions to numeric axis values."""
    points: List[Tuple[float, float]] = field(default_factory=list)

    def add_point(self, pixel: float, value: float) -> None:
        self.points.append((pixel, value))
        self.points.sort(key=lambda p: p[0])

    def move_pixel(self, index: int, pixel: float) -> None:
        p = list(self.points)
        p[index] = (pixel, p[index][1])
        self.points = sorted(p, key=lambda t: t[0])

    def edit_value(self, index: int, value: float) -> None:
        pixel, _ = self.points[index]
        self.points[index] = (pixel, value)

    def delete_point(self, index: int) -> None:
        del self.points[index]

    def clear(self) -> None:
        self.points.clear()

    def is_ready(self) -> bool:
        return len(self.points) >= 2

    def value_range(self) -> Tuple[Optional[float], Optional[float]]:
        if not self.points:
            return (None, None)
        vals = [v for _, v in self.points]
        return (min(vals), max(vals))

    # linear interpolation helpers
    def _interp(self, x0: float, y0: float, x1: float, y1: float, x: float) -> float:
        if x1 == x0:
            return y0
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

    def eval(self, pixel: float) -> float:
        if not self.is_ready():
            raise ValueError("AxisMap not calibrated")
        pts = sorted(self.points)
        if pixel <= pts[0][0]:
            x0, y0 = pts[0]
            x1, y1 = pts[1]
            return self._interp(x0, y0, x1, y1, pixel)
        if pixel >= pts[-1][0]:
            x0, y0 = pts[-2]
            x1, y1 = pts[-1]
            return self._interp(x0, y0, x1, y1, pixel)
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            if x0 <= pixel <= x1:
                return self._interp(x0, y0, x1, y1, pixel)
        return pts[0][1]

    def inverse(self, value: float) -> float:
        if not self.is_ready():
            raise ValueError("AxisMap not calibrated")
        pts = sorted(self.points, key=lambda t: t[1])
        if value <= pts[0][1]:
            x0, y0 = pts[0]
            x1, y1 = pts[1]
            return self._interp(y0, x0, y1, x1, value)
        if value >= pts[-1][1]:
            x0, y0 = pts[-2]
            x1, y1 = pts[-1]
            return self._interp(y0, x0, y1, x1, value)
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            if y0 <= value <= y1 or y1 <= value <= y0:
                return self._interp(y0, x0, y1, x1, value)
        return pts[0][0]


@dataclass
class Curve:
    label: float
    points_xy: List[Tuple[float, float]] = field(default_factory=list)

    def add_xy(self, x: float, y: float) -> None:
        self.points_xy.append((x, y))
        self.points_xy.sort(key=lambda t: t[0])

    def is_ready(self) -> bool:
        return len(self.points_xy) >= 2

    def x_span(self) -> Optional[Tuple[float, float]]:
        if not self.points_xy:
            return None
        xs = [x for x, _ in self.points_xy]
        return (min(xs), max(xs))

    def y_at_x(self, x: float, extrapolate: bool = False) -> Optional[float]:
        if not self.is_ready():
            return None
        pts = sorted(self.points_xy)
        if x < pts[0][0]:
            if not extrapolate:
                return None
            x0, y0 = pts[0]
            x1, y1 = pts[1]
            return AxisMap()._interp(x0, y0, x1, y1, x)
        if x > pts[-1][0]:
            if not extrapolate:
                return None
            x0, y0 = pts[-2]
            x1, y1 = pts[-1]
            return AxisMap()._interp(x0, y0, x1, y1, x)
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            if x0 <= x <= x1:
                return AxisMap()._interp(x0, y0, x1, y1, x)
        return None


@dataclass
class Panel:
    fn_fc: float
    roi: Tuple[int, int, int, int]
    axis_x: AxisMap = field(default_factory=AxisMap)
    curves: Dict[float, Curve] = field(default_factory=dict)
    x_marks: List[Tuple[float, float, float]] = field(default_factory=list)
    axis_x_tilt_deg: float = 0.0


@dataclass
class ImageEntry:
    group: str
    image_name: str
    size: Tuple[int, int]
    panels: List[Panel] = field(default_factory=list)
    axis_y: AxisMap = field(default_factory=AxisMap)
    y_marks: List[Tuple[float, float, float]] = field(default_factory=list)
    tilt_deg: float = 0.0
    axis_y_tilt_deg: float = 0.0


@dataclass
class Project:
    images: List[ImageEntry] = field(default_factory=list)
    extrapolate: bool = False
    sketch_name: Optional[str] = None
    preview_source: Optional[str] = None

    def to_json(self) -> str:
        data = {
            "version": 38,
            "extrapolate": self.extrapolate,
            "sketch_name": self.sketch_name,
            "preview_source": self.preview_source,
            "images": [],
        }
        for im in self.images:
            im_data = {
                "group": im.group,
                "image_name": im.image_name,
                "size": list(im.size),
                "tilt_deg": getattr(im, "tilt_deg", 0.0),
                "axis_y_tilt_deg": getattr(im, "axis_y_tilt_deg", 0.0),
                "axis_y": {"points": im.axis_y.points},
                "y_marks": im.y_marks,
                "panels": [],
            }
            for p in im.panels:
                p_data = {
                    "fn_fc": p.fn_fc,
                    "roi": list(p.roi),
                    "axis_x": {"points": p.axis_x.points},
                    "x_marks": p.x_marks,
                    "axis_x_tilt_deg": getattr(p, "axis_x_tilt_deg", 0.0),
                    "curves": [
                        {"label": lab, "points_xy": cur.points_xy}
                        for lab, cur in sorted(p.curves.items(), key=lambda t: t[0])
                    ],
                }
                im_data["panels"].append(p_data)
            data["images"].append(im_data)
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def from_json(text: str) -> "Project":
        obj = json.loads(text)
        proj = Project(
            extrapolate=obj.get("extrapolate", False),
            sketch_name=obj.get("sketch_name"),
            preview_source=obj.get("preview_source"),
        )
        for imd in obj.get("images", []):
            image = ImageEntry(
                group=imd.get("group"),
                image_name=imd.get("image_name"),
                size=tuple(imd.get("size", (0, 0))),
                tilt_deg=float(imd.get("tilt_deg", 0.0)),
                axis_y_tilt_deg=float(imd.get("axis_y_tilt_deg", 0.0)),
            )

            axis_y_data = imd.get("axis_y", {})
            if isinstance(axis_y_data, dict):
                pts = axis_y_data.get("points", [])
            elif isinstance(axis_y_data, list):
                pts = axis_y_data
            else:
                pts = []
            image.axis_y.points = [(float(a), float(b)) for a, b, *_ in pts]

            image.y_marks = [
                (float(y), float(x), float(v))
                for y, x, v, *_ in imd.get("y_marks", [])
            ]

            for pd in imd.get("panels", []):
                panel = Panel(
                    fn_fc=float(pd.get("fn_fc", 0.0)),
                    roi=tuple(pd.get("roi", (0, 0, 0, 0))),
                    axis_x_tilt_deg=float(pd.get("axis_x_tilt_deg", 0.0)),
                )

                axis_x_data = pd.get("axis_x", {})
                if isinstance(axis_x_data, dict):
                    pts_x = axis_x_data.get("points", [])
                elif isinstance(axis_x_data, list):
                    pts_x = axis_x_data
                else:
                    pts_x = []
                panel.axis_x.points = [(float(u), float(v)) for u, v, *_ in pts_x]

                panel.x_marks = [
                    (float(u), float(y), float(v))
                    for u, y, v, *_ in pd.get("x_marks", [])
                ]

                curves_data = pd.get("curves", {})
                if isinstance(curves_data, dict):
                    iterable = curves_data.items()
                    for lab, pts in iterable:
                        panel.curves[float(lab)] = Curve(
                            label=float(lab),
                            points_xy=[(float(x), float(y)) for x, y, *_ in pts],
                        )
                elif isinstance(curves_data, list):
                    for item in curves_data:
                        if isinstance(item, dict):
                            label = item.get("label")
                            points = item.get("points_xy") or item.get("points", [])
                        elif isinstance(item, (list, tuple)) and len(item) == 2:
                            label, points = item
                        else:
                            raise ValueError(
                                "Неправильний формат кривої: очікується словник або [label, points]",
                            )
                        if label is None:
                            raise ValueError("Відсутнє поле 'label' у даних кривої")
                        panel.curves[float(label)] = Curve(
                            label=float(label),
                            points_xy=[(float(x), float(y)) for x, y, *_ in points],
                        )
                else:
                    raise ValueError(
                        f"Непідтримуваний тип 'curves': {type(curves_data).__name__}"
                    )

                image.panels.append(panel)
            proj.images.append(image)
        return proj
