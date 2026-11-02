"""The heat map as an image for the report and slides: SVG (served to the browser) and PNG, both drawn from one layout.
PNG uses Pillow, which the PDF writer (xhtml2pdf) already installs, with the platform's bundled IBM Plex Sans font."""
from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

FONTS = Path(__file__).resolve().parents[1] / "documents" / "fonts"
FILL = {"low": "#E1F2E7", "medium": "#FFF1D6", "high": "#FBD9D3", "critical": "#F4B7AE"}
CHIP = {"critical": ("#7A1F1F", "#FFFFFF"), "high": ("#B93A0B", "#FFFFFF"), "medium": ("#F2C14E", "#1D2433"), "low": ("#2F6B45", "#FFFFFF")}
INK, MUTED = "#16233A", "#5A6577"
W, LEFT, TOP, CELL_W, CELL_H, GAP = 960, 120, 70, 200, 110, 6


def layout(data: dict) -> list[dict]:
    """Shapes: rect {x, y, w, h, fill, stroke?} and text {x, y, text, size, fill, bold?, anchor?}."""
    out: list[dict] = [{"t": "rect", "x": 0, "y": 0, "w": W, "h": TOP + 4 * (CELL_H + GAP) + 110, "fill": "#FFFFFF"}]
    title = f"Risk heat map · {data['engagement']['audit_ref'] or ''}"
    out.append({"t": "text", "x": 24, "y": 34, "text": title, "size": 20, "fill": INK, "bold": True})
    out.append({"t": "text", "x": 24, "y": 56, "text": "Inherent risk (columns) × control maturity (rows). Cell colour: residual band. * provisional score.", "size": 12, "fill": MUTED})
    for ri, row in enumerate(data["rows"]):
        y = TOP + ri * (CELL_H + GAP)
        out.append({"t": "text", "x": 24, "y": y + CELL_H / 2 + 4, "text": f"Maturity {row}", "size": 12, "fill": MUTED, "bold": True})
        for ci, cell in enumerate(data["grid"][row]):
            x = LEFT + ci * (CELL_W + GAP)
            out.append({"t": "rect", "x": x, "y": y, "w": CELL_W, "h": CELL_H, "fill": FILL.get(cell["band"], "#EEF1F5")})
            for k, chip in enumerate(cell["systems"][:6]):
                cx, cy = x + 8 + (k % 2) * 96, y + 8 + (k // 2) * 32
                bg, ink = CHIP.get(chip.get("final_rating") or "", ("#FFFFFF", INK))
                out.append({"t": "rect", "x": cx, "y": cy, "w": 90, "h": 26, "fill": bg, "stroke": INK})
                out.append({"t": "text", "x": cx + 45, "y": cy + 17, "text": chip["reference_id"] + ("*" if chip.get("provisional") else ""), "size": 12, "fill": ink, "bold": True, "anchor": "middle"})
            if len(cell["systems"]) > 6:
                out.append({"t": "text", "x": x + 8, "y": y + CELL_H - 8, "text": f"+{len(cell['systems']) - 6} more", "size": 11, "fill": INK})
    base = TOP + 4 * (CELL_H + GAP)
    for ci, col in enumerate(data["columns"]):
        out.append({"t": "text", "x": LEFT + ci * (CELL_W + GAP) + CELL_W / 2, "y": base + 16, "text": f"Inherent {col['label']}", "size": 12, "fill": MUTED, "bold": True, "anchor": "middle"})
    x = LEFT
    for band in ("low", "medium", "high", "critical"):
        out.append({"t": "rect", "x": x, "y": base + 40, "w": 14, "h": 14, "fill": FILL[band]})
        out.append({"t": "text", "x": x + 20, "y": base + 52, "text": band.capitalize(), "size": 12, "fill": INK})
        x += 100
    out.append({"t": "text", "x": x + 10, "y": base + 52, "text": "Knock-out rules can raise a system above its cell.", "size": 12, "fill": MUTED})
    return out


def height(shapes: list[dict]) -> int:
    return int(shapes[0]["h"])


def to_svg(data: dict) -> bytes:
    shapes = layout(data)
    h = height(shapes)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" role="img" aria-label="Risk heat map" font-family="IBM Plex Sans, Arial, sans-serif">']
    for s in shapes:
        if s["t"] == "rect":
            stroke = f' stroke="{s["stroke"]}" stroke-width="1"' if s.get("stroke") else ""
            parts.append(f'<rect x="{s["x"]:g}" y="{s["y"]:g}" width="{s["w"]:g}" height="{s["h"]:g}" rx="6" fill="{s["fill"]}"{stroke}/>')
        else:
            anchor = f' text-anchor="{s["anchor"]}"' if s.get("anchor") else ""
            weight = ' font-weight="600"' if s.get("bold") else ""
            parts.append(f'<text x="{s["x"]:g}" y="{s["y"]:g}" font-size="{s["size"]}" fill="{s["fill"]}"{anchor}{weight}>{escape(s["text"])}</text>')
    parts.append("</svg>")
    return "".join(parts).encode()


def to_png(data: dict, scale: int = 2) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    shapes = layout(data)
    img = Image.new("RGB", (W * scale, height(shapes) * scale), "#FFFFFF")
    d = ImageDraw.Draw(img)
    fonts: dict = {}

    def font(size: int, bold: bool):
        key = (size, bold)
        if key not in fonts:
            path = FONTS / ("IBMPlexSans-SemiBold.ttf" if bold else "IBMPlexSans-Regular.ttf")
            try:
                fonts[key] = ImageFont.truetype(str(path), size * scale)
            except OSError:
                fonts[key] = ImageFont.load_default()
        return fonts[key]

    for s in shapes:
        if s["t"] == "rect":
            box = [s["x"] * scale, s["y"] * scale, (s["x"] + s["w"]) * scale, (s["y"] + s["h"]) * scale]
            d.rounded_rectangle(box, radius=6 * scale, fill=s["fill"], outline=s.get("stroke"), width=scale if s.get("stroke") else 0)
        else:
            f = font(s["size"], bool(s.get("bold")))
            anchor = "ms" if s.get("anchor") == "middle" else "ls"
            d.text((s["x"] * scale, s["y"] * scale), s["text"], fill=s["fill"], font=f, anchor=anchor)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
