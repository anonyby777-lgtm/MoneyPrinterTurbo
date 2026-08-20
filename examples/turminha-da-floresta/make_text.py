from PIL import Image, ImageDraw, ImageFont
import os

OUT = "/home/user/build/text"
os.makedirs(OUT, exist_ok=True)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H = 1920, 1080


def card(name, text, fill, size=150, y=None, sub=None):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, size)
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=int(size * 0.09))
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (W - tw) // 2 - bbox[0]
    yy = (H - th - 130) if y is None else y
    # soft dark plate for readability
    pad = 42
    plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    pd.rounded_rectangle(
        [x - pad, yy - int(pad * 0.55), x + tw + pad, yy + th + int(pad * 0.8)],
        radius=60, fill=(20, 12, 40, 105))
    img = Image.alpha_composite(img, plate)
    d = ImageDraw.Draw(img)
    d.text((x, yy), text, font=font, fill=fill,
           stroke_width=int(size * 0.09), stroke_fill=(255, 255, 255, 245))
    if sub:
        sfont = ImageFont.truetype(FONT, int(size * 0.42))
        sb = d.textbbox((0, 0), sub, font=sfont, stroke_width=6)
        sx = (W - (sb[2] - sb[0])) // 2 - sb[0]
        d.text((sx, yy + th + 26), sub, font=sfont, fill=(255, 255, 255, 240),
               stroke_width=6, stroke_fill=(40, 25, 70, 220))
    p = f"{OUT}/{name}.png"
    img.save(p)
    print(p)


card("vermelho", "VERMELHO", (233, 43, 47, 255))
card("azul", "AZUL", (44, 122, 226, 255))
card("amarelo", "AMARELO", (247, 190, 27, 255))
card("roxo", "ROXO", (150, 84, 214, 255))
card("pergunta", "Qual é a sua cor favorita?", (255, 255, 255, 255), size=86)
card("muitobem", "MUITO BEM!", (255, 138, 60, 255), size=130)
card("tchau", "TCHAU!", (86, 200, 160, 255), size=140)
