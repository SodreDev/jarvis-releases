"""
Gera jarvis_icon.ico — arc reactor / HUD style, tamanhos 16..256 px.
Execute: python _gen_icon.py
"""
import math
from PIL import Image, ImageDraw, ImageFilter

def _make_frame(size: int) -> Image.Image:
    S = size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx, cy = S / 2, S / 2
    R = S / 2 - 1

    # ── Fundo circular (gradiente simulado com camadas) ───────────────────────
    for i in range(int(R), 0, -1):
        t = i / R
        r = int(4  + t * 4)
        g = int(12 + t * 20)
        b = int(28 + t * 40)
        a = 255
        d.ellipse([cx - i, cy - i, cx + i, cy + i], fill=(r, g, b, a))

    # ── Borda exterior brilhante ───────────────────────────────────────────────
    border_w = max(1, int(S * 0.025))
    d.ellipse([cx - R, cy - R, cx + R, cy + R],
              outline=(0, 210, 255, 230), width=border_w)

    # ── Anéis concêntricos (arc reactor) ─────────────────────────────────────
    ring_radii = [0.75, 0.55, 0.36]
    ring_alpha = [180, 160, 200]
    ring_w     = [max(1, int(S * 0.018)), max(1, int(S * 0.016)), max(1, int(S * 0.020))]
    for radius_f, alpha, rw in zip(ring_radii, ring_alpha, ring_w):
        rr = R * radius_f
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(0, 200, 255, alpha), width=rw)

    # ── Linhas radiais (segmentos HUD) ────────────────────────────────────────
    n_lines = 6
    outer_r = R * 0.73
    inner_r = R * 0.38
    line_w  = max(1, int(S * 0.012))
    for i in range(n_lines):
        angle = math.radians(i * (360 / n_lines) - 15)
        x0 = cx + inner_r * math.cos(angle)
        y0 = cy + inner_r * math.sin(angle)
        x1 = cx + outer_r * math.cos(angle)
        y1 = cy + outer_r * math.sin(angle)
        d.line([x0, y0, x1, y1], fill=(0, 220, 255, 160), width=line_w)

    # ── Núcleo central (triângulo + círculo) ──────────────────────────────────
    core_r = R * 0.22
    # Triângulo invertido estilo ARC
    tri_pts = []
    for i in range(3):
        angle = math.radians(90 + i * 120)  # ponta pra baixo (invertido)
        tx = cx + core_r * 0.9 * math.cos(angle)
        ty = cy + core_r * 0.9 * math.sin(angle)
        tri_pts.append((tx, ty))
    d.polygon(tri_pts, fill=(0, 180, 255, 210), outline=(0, 230, 255, 255))

    # Círculo interno (glow core)
    inner_core = core_r * 0.42
    # Glow: múltiplas camadas semitransparentes
    for glow in range(5, 0, -1):
        gr = inner_core + glow * (S * 0.008)
        ga = int(60 + glow * 10)
        d.ellipse([cx - gr, cy - gr, cx + gr, cy + gr],
                  fill=(100, 220, 255, ga))
    d.ellipse([cx - inner_core, cy - inner_core,
               cx + inner_core, cy + inner_core],
              fill=(200, 245, 255, 255))

    # ── Glow exterior suave ────────────────────────────────────────────────────
    glow_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    for glow in range(6, 0, -1):
        gr = R - border_w + glow * (S * 0.01)
        ga = int(20 + glow * 5)
        gd.ellipse([cx - gr, cy - gr, cx + gr, cy + gr],
                   outline=(0, 180, 255, ga), width=max(2, border_w + 1))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=max(1, S // 40)))
    img = Image.alpha_composite(img, glow_layer)

    return img


def generate(out_path: str = "jarvis_icon.ico"):
    sizes = [256, 128, 64, 48, 32, 16]
    frames = [_make_frame(s) for s in sizes]
    # PIL salva .ico com múltiplos tamanhos
    frames[0].save(
        out_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"[OK] Ícone gerado: {out_path}  ({len(sizes)} tamanhos: {sizes})")


if __name__ == "__main__":
    generate()
