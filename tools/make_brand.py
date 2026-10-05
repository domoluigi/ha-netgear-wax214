"""Genera le immagini brand/ dell'integrazione (HA 2026.3+): access point da soffitto con onde Wi-Fi.

Disegno originale, nessun marchio. Si disegna a 4x e si riduce per avere bordi morbidi.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "wax214" / "brand"
BLUE = (0, 132, 214, 255)
BODY = (248, 249, 251, 255)
EDGE = (176, 184, 196, 255)
LED = (40, 200, 120, 255)


def draw_icon(size: int) -> Image.Image:
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # onde Wi-Fi: tre archi concentrici sopra l'access point
    cx, cy = s / 2, s * 0.60
    for i, r in enumerate((0.20, 0.31, 0.42)):
        rr = s * r
        w = int(s * 0.055)
        d.arc([cx - rr, cy - rr, cx + rr, cy + rr], start=225, end=315, fill=BLUE, width=w)
    dot = s * 0.045
    d.ellipse([cx - dot, cy - s * 0.10 - dot, cx + dot, cy - s * 0.10 + dot], fill=BLUE)

    # ombra morbida dell'access point
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    box = [s * 0.16, s * 0.56, s * 0.84, s * 0.92]
    sd.rounded_rectangle([box[0], box[1] + s * 0.02, box[2], box[3] + s * 0.02], radius=s * 0.16, fill=(0, 0, 0, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(s * 0.02))
    img = Image.alpha_composite(img, shadow)
    d = ImageDraw.Draw(img)

    # corpo: quadrato molto arrotondato, bianco con bordo grigio (leggibile su sfondo chiaro e scuro)
    d.rounded_rectangle(box, radius=s * 0.16, fill=BODY, outline=EDGE, width=int(s * 0.018))
    # quattro LED in basso, come sul WAX214
    ly = box[3] - s * 0.075
    for k in range(4):
        lx = s * (0.38 + k * 0.08)
        lr = s * 0.016
        d.ellipse([lx - lr, ly - lr, lx + lr, ly + lr], fill=LED if k == 0 else (150, 158, 170, 255))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_icon(256).save(OUT / "icon.png", optimize=True)
    draw_icon(512).save(OUT / "icon@2x.png", optimize=True)
    # il tema scuro chiede dark_icon*: senza, HA mostra "icon not available". Il disegno va bene su entrambi
    draw_icon(256).save(OUT / "dark_icon.png", optimize=True)
    draw_icon(512).save(OUT / "dark_icon@2x.png", optimize=True)
    for f in sorted(OUT.iterdir()):
        with Image.open(f) as im:
            print(f.name, im.size, im.mode, f.stat().st_size, "byte")


if __name__ == "__main__":
    main()
