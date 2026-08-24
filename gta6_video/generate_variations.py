#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera 8 variações do vídeo GTA6 (Lucia & Jason) — 1080x1920, sem música,
com narração própria, legendas e títulos por variação. Reusa imagens + Ken Burns
do pipeline original, mas com conteúdo (curiosidades) diferente em cada uma.
"""
import json, os, subprocess, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import imageio_ffmpeg
import pyloudnorm as pyln

ROOT = os.path.dirname(os.path.abspath(__file__))
FF = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 30
W, H = 1080, 1920
SUP_W, SUP_H = 2700, 4800
BUILD = os.path.join(ROOT, "render")
OUT = os.path.join(ROOT, "out")
SR = 44100
os.makedirs(OUT, exist_ok=True)

import variations as VV

# ---------------- helpers ----------------
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-4000:])
        raise SystemExit(f"FFMPEG FALHOU: {' '.join(cmd[:8])}...")

def decode_mono(path, sr=SR):
    raw = subprocess.run([FF, "-i", path, "-f", "s16le", "-ar", str(sr), "-ac", "1", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

def audio_duration(path):
    r = subprocess.run([FF, "-i", path], capture_output=True, text=True)
    for ln in r.stderr.splitlines():
        if "Duration" in ln:
            t = ln.split("Duration:")[1].split(",")[0].strip()
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0

# ---------------- imagem / face ----------------
A = {a["file"]: a for a in json.load(open(os.path.join(BUILD, "images_analysis.json")))}

def face_of(fname, default=(0.5, 0.4), idx=0):
    a = A[os.path.basename(fname)]
    if a.get("faces"):
        f = a["faces"][min(idx, len(a["faces"]) - 1)]
        return (round(min(max(f["x"] + f["w"] / 2, 0.12), 0.88), 3),
                round(min(max(f["y"] + f["h"] / 2 - 0.04, 0.12), 0.88), 3))
    return default

def prep_image(src, dst, fx=0.5, fy=0.42):
    im = Image.open(src).convert("RGB")
    ar = im.width / im.height
    scale = max(SUP_W / im.width, SUP_H / im.height)
    nw, nh = int(im.width * scale + 0.5), int(im.height * scale + 0.5)
    im2 = im.resize((nw, nh), Image.LANCZOS)
    x = int((nw - SUP_W) * fx); y = int((nh - SUP_H) * fy)
    x = max(0, min(nw - SUP_W, x)); y = max(0, min(nh - SUP_H, y))
    im2.crop((x, y, x + SUP_W, y + SUP_H)).save(dst, quality=95)

MOVES = {
    "in":     ("1+0.28*on/{D}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
    "in_slow":("1+0.16*on/{D}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
    "out":    ("1.30-0.30*on/{D}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
    "punch":  ("1+0.55*pow(on/{D},2)", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
    "left":   ("1.24", "(iw-iw/zoom)*on/{D}", "(ih-ih/zoom)/2"),
    "right":  ("1.24", "(iw-iw/zoom)*(1-on/{D})", "(ih-ih/zoom)/2"),
    "up":     ("1.24", "(iw-iw/zoom)/2", "(ih-ih/zoom)*on/{D}"),
    "down":   ("1.24", "(iw-iw/zoom)/2", "(ih-ih/zoom)*(1-on/{D})"),
    "diag":   ("1+0.3*on/{D}", "(iw-iw/zoom)*(1-on/{D})", "(ih-ih/zoom)*on/{D}"),
    "diag2":  ("1+0.3*on/{D}", "(iw-iw/zoom)*on/{D}", "(ih-ih/zoom)*(1-on/{D})"),
}
MOVE_CYCLE = ["in", "punch", "left", "right", "diag", "diag2", "up", "down", "in_slow"]

# ---------------- overlays (texto) ----------------
try:
    import font_roboto
    FDIR = os.path.join(os.path.dirname(font_roboto.__file__), "files")
    F_TITLE = os.path.join(FDIR, "Roboto-Black.ttf")
    F_CAP = os.path.join(FDIR, "Roboto-Black.ttf")
except Exception:
    F_TITLE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    F_CAP = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

BLACK = (10, 10, 12, 255)
WHITE = (255, 255, 255, 255)
YELLOW = (255, 214, 0, 255)
RED = (232, 29, 54, 255)

def parse_markup(s):
    out = []
    for i, part in enumerate(s.split("*")):
        if part:
            out.append((part, i % 2 == 1))
    return out

def draw_marked(d, xy, text, font, fill=WHITE, hi=YELLOW, stroke=0, anchor="la", stroke_fill=BLACK):
    x, y = xy
    pieces = []
    for tok, is_hi in parse_markup(text):
        bbox = d.textbbox((0, 0), tok, font=font, stroke_width=stroke)
        pieces.append((tok, is_hi, bbox[2] - bbox[0]))
    total = sum(p[2] for p in pieces) + d.textlength(" ", font=font) * (len(pieces) - 1)
    if anchor == "ma":
        x -= total / 2
    elif anchor == "ra":
        x -= total
    for tok, is_hi, w in pieces:
        d.text((x, y), tok, font=font, fill=hi if is_hi else fill,
               stroke_width=stroke, stroke_fill=stroke_fill)
        x += w + d.textlength(" ", font=font)
    return total

def render_caption(text, size=62, maxw=980):
    font = ImageFont.truetype(F_CAP, size)
    tmp = Image.new("RGBA", (10, 10)); d = ImageDraw.Draw(tmp)
    while size > 30:
        bbox = d.textbbox((0, 0), text.replace("*", ""), font=font, stroke_width=7)
        if bbox[2] - bbox[0] <= maxw:
            break
        size -= 3
        font = ImageFont.truetype(F_CAP, size)
    asc, desc = font.getmetrics()
    hgt = asc + desc + 22
    img = Image.new("RGBA", (1080, hgt), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); ds = ImageDraw.Draw(sh)
    draw_marked(ds, (536, 9), text, font, stroke=8, anchor="ma", fill=(0, 0, 0, 160), hi=(0, 0, 0, 160))
    sh = sh.filter(ImageFilter.GaussianBlur(6))
    draw_marked(d, (540, 13), text, font, stroke=8, anchor="ma")
    img = Image.alpha_composite(sh, img)
    return img

def render_title(text, maxw=1000):
    size = 84
    font = ImageFont.truetype(F_TITLE, size)
    tmp = Image.new("RGBA", (10, 10)); d = ImageDraw.Draw(tmp)
    while size > 36:
        bbox = d.textbbox((0, 0), text, font=font, stroke_width=9)
        if bbox[2] - bbox[0] <= maxw:
            break
        size -= 4
        font = ImageFont.truetype(F_TITLE, size)
    asc, desc = font.getmetrics()
    hgt = asc + desc + 26
    img = Image.new("RGBA", (1080, hgt), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); ds = ImageDraw.Draw(sh)
    draw_marked(ds, (536, 10), text, font, stroke=10, anchor="ma", fill=(0, 0, 0, 190), hi=(0, 0, 0, 190))
    sh = sh.filter(ImageFilter.GaussianBlur(7))
    draw_marked(d, (540, 14), text, font, stroke=9, anchor="ma")
    img = Image.alpha_composite(sh, img)
    bar = Image.new("RGBA", (1080, 14), (0, 0, 0, 0)); bd = ImageDraw.Draw(bar)
    bd.rectangle([140, 4, 940, 10], fill=RED)
    out = Image.new("RGBA", (1080, hgt + 14), (0, 0, 0, 0))
    out.paste(img, (0, 0), img); out.paste(bar, (0, hgt), bar)
    return out

def render_cta(line1, line2="COMENTA!"):
    img = Image.new("RGBA", (1080, 560), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # faixa superior com line1
    f1 = ImageFont.truetype(F_TITLE, 78)
    tmp = Image.new("RGBA", (10, 10)); dd = ImageDraw.Draw(tmp)
    while f1.size > 40:
        bb = dd.textbbox((0, 0), line1, font=f1, stroke_width=8)
        if bb[2] - bb[0] <= 960:
            break
        f1 = ImageFont.truetype(F_TITLE, f1.size - 4)
    tw = dd.textbbox((0, 0), line1, font=f1, stroke_width=8)[2]
    d.rounded_rectangle([60, 40, 1020, 300], 26, fill=(8, 8, 14, 170))
    d.text((540 - tw / 2, 86), line1, font=f1, fill=WHITE, stroke_width=8, stroke_fill=BLACK)
    # botão COMENTA!
    f2 = ImageFont.truetype(F_TITLE, 104)
    bb = d.textbbox((0, 0), line2, font=f2, stroke_width=9)
    tw2 = bb[2] - bb[0]; th2 = bb[3] - bb[1]
    bx0 = 540 - tw2 / 2 - 44; bx1 = 540 + tw2 / 2 + 44
    d.rounded_rectangle([bx0, 350, bx1, 350 + th2 + 76], 22, fill=RED, outline=(255, 255, 255, 230), width=5)
    d.text((540 - tw2 / 2, 350 + 34), line2, font=f2, fill=WHITE, stroke_width=9, stroke_fill=(120, 8, 26, 255))
    return img

# ---------------- SFX leves (sem música) ----------------
rng = np.random.default_rng(77)

def highpass_fft(x, cutoff):
    X = np.fft.rfft(x); freqs = np.fft.rfftfreq(len(x), 1 / SR)
    gain = 1.0 / (1.0 + (cutoff / np.maximum(freqs, 1)) ** 4)
    return np.fft.irfft(X * gain, len(x)).astype(np.float32)

def lowpass_fft(x, cutoff):
    X = np.fft.rfft(x); freqs = np.fft.rfftfreq(len(x), 1 / SR)
    gain = 1.0 / (1.0 + (freqs / max(cutoff, 20)) ** 4)
    return np.fft.irfft(X * gain, len(x)).astype(np.float32)

def sfx_whoosh(dur=0.5):
    n = int(dur * SR); t = np.arange(n) / SR
    noise = rng.standard_normal(n).astype(np.float32)
    hiss = highpass_fft(noise, 1300); air = lowpass_fft(noise, 900)
    e = np.sin(np.pi * np.minimum(t / dur, 1.0)) ** 2.2
    return np.tanh((0.65 * hiss + 0.5 * air) * e * 1.6) * 0.6

def sfx_impact(f0=58.0, f1=36.0, dur=0.9):
    n = int(dur * SR); t = np.arange(n) / SR
    f = f0 + (f1 - f0) * (1 - np.exp(-t / 0.08))
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t / 0.22)
    click = highpass_fft(rng.standard_normal(int(0.012 * SR)), 3000) * 0.5 * np.exp(-np.arange(int(0.012 * SR)) / (0.004 * SR))
    out = body.copy(); out[:len(click)] += click
    return np.tanh(out * 1.4) * 0.85

def sfx_subdrop(dur=1.4):
    n = int(dur * SR); t = np.arange(n) / SR
    f = 130 * np.exp(-t / 0.28) + 28
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t / 0.5) * 0.85

def find_silences(sig, thr=0.012, min_gap=0.16):
    win = int(0.02 * SR)
    env = np.convolve(np.abs(sig), np.ones(win) / win, mode="same")
    sil = env < thr
    iv = []; i = 0
    while i < len(sil):
        if sil[i]:
            j = i
            while j < len(sil) and sil[j]:
                j += 1
            if (j - i) / SR >= min_gap:
                iv.append(((i) / SR, (j) / SR))
            i = j
        else:
            i += 1
    return iv

def snap(t, silences, radius=0.6):
    best = t; bd = radius
    for (a, b) in silences:
        c = (a + b) / 2
        if abs(c - t) < bd:
            bd = abs(c - t); best = c
    return best

# ---------------- geração por variação ----------------
def build_variation(v, idx):
    slug = v["slug"]
    var_dir = os.path.join(BUILD, "var", slug)
    narr_path = os.path.join(var_dir, "narr.mp3")
    work = os.path.join(var_dir, "work")
    os.makedirs(work, exist_ok=True)

    segs = v["segments"]
    D = audio_duration(narr_path)
    print(f"\n=== [{idx+1}/8] {slug} — narração {D:.2f}s ===")

    # ---- janelas por segmento (proporcional a chars) + snap a silêncios ----
    sig = decode_mono(narr_path)
    sil = find_silences(sig)
    chars = [len(s["narration"].strip()) for s in segs]
    tot = sum(chars)
    bounds = [0.0]
    acc = 0.0
    for c in chars[:-1]:
        acc += c
        bounds.append(acc / tot * D)
    bounds.append(D)
    # snap nos limites internos
    for i in range(1, len(bounds) - 1):
        bounds[i] = snap(bounds[i], sil)
    # reordenar monotonicamente
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = bounds[i - 1] + 0.25
    windows = [(bounds[i], bounds[i + 1]) for i in range(len(segs))]
    for (a, b), s in zip(windows, segs):
        print(f"  {a:6.2f}-{b:6.2f}  {s['kind']:5s} {s.get('title','')[:40]}")

    TAIL = 1.6
    total = D + TAIL

    # ---- shots (imagens + ken burns) ----
    shots = []
    for wi, (seg, (t0, t1)) in enumerate(zip(segs, windows)):
        img = VV.IMG[seg["image"]]
        n = max(1, round((t1 - t0) / 4.5))
        for k in range(n):
            a = t0 + (t1 - t0) * k / n
            b = t0 + (t1 - t0) * (k + 1) / n
            if b - a < 0.4:
                continue
            move = MOVE_CYCLE[(wi + k) % len(MOVE_CYCLE)]
            shots.append(dict(img=img, t0=a, t1=b, move=move,
                              fx=face_of(img)[0], fy=face_of(img)[1]))

    # render clips + concat
    prepdir = os.path.join(work, "prep"); clipdir = os.path.join(work, "clips")
    os.makedirs(prepdir, exist_ok=True); os.makedirs(clipdir, exist_ok=True)
    clips = []
    for i, sh in enumerate(shots):
        dur = sh["t1"] - sh["t0"]
        frames = max(2, round(dur * FPS))
        prep = os.path.join(prepdir, f"p{i:02d}.jpg")
        prep_image(os.path.join(ROOT, sh["img"]), prep, fx=sh["fx"], fy=sh["fy"])
        z, x, y = MOVES[sh["move"]]
        z, x, y = z.format(D=frames), x.format(D=frames), y.format(D=frames)
        vf = (f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},format=yuv420p")
        out = os.path.join(clipdir, f"c{i:02d}.mp4")
        run([FF, "-y", "-loop", "1", "-i", prep, "-vf", vf,
             "-t", f"{frames/FPS:.4f}", "-r", str(FPS),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", out])
        clips.append(out)
    lst = os.path.join(work, "concat.txt")
    with open(lst, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    base = os.path.join(work, "base.mp4")
    run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", base])

    # ---- overlays ----
    ovdir = os.path.join(work, "overlays"); os.makedirs(ovdir, exist_ok=True)
    manifest = []
    for si, (seg, (t0, t1)) in enumerate(zip(segs, windows)):
        if seg["kind"] == "hook":
            # título do hook
            fn = f"tt_{si:02d}.png"
            render_title(v["title_hook"]).save(os.path.join(ovdir, fn))
            manifest.append(dict(file=fn, t0=round(t0 + 0.15, 2),
                                 t1=round(min(t0 + 4.6, t1 - 0.1), 2), y=250, kind="title"))
        elif seg["kind"] == "fact":
            fn = f"tt_{si:02d}.png"
            render_title(seg["title"]).save(os.path.join(ovdir, fn))
            manifest.append(dict(file=fn, t0=round(t0 + 0.05, 2),
                                 t1=round(min(t0 + 2.6, t1 - 0.1), 2), y=250, kind="title"))
        # legendas (todas as falas)
        cchunks = seg["captions"]
        cchars = [len(c.replace("*", "")) for c in cchunks]
        ctot = sum(cchars)
        ct = t0
        for j, ch in enumerate(cchunks):
            dt = (t1 - t0) * cchars[j] / ctot
            fn = f"cap_{si:02d}_{j:02d}.png"
            render_caption(ch).save(os.path.join(ovdir, fn))
            manifest.append(dict(file=fn, t0=round(ct, 2),
                                 t1=round(min(ct + dt - 0.03, t1 - 0.02), 2), y=1480, kind="cap"))
            ct += dt
        if seg["kind"] == "cta":
            fn = "cta.png"
            render_cta(v["cta"][0], v["cta"][1]).save(os.path.join(ovdir, fn))
            manifest.append(dict(file=fn, t0=round(t0, 2), t1=round(total, 2), y=640, kind="cta"))

    # ---- áudio: narração + sfx leve (SEM música) ----
    N = int(total * SR)
    def trim_silence(x, thr=0.008, keep_head=0.05, keep_tail=0.15):
        idx = np.where(np.abs(x) > thr)[0]
        if len(idx) == 0:
            return x
        a = max(0, idx[0] - int(keep_head * SR))
        b = min(len(x), idx[-1] + int(keep_tail * SR))
        return x[a:b]

    vo = trim_silence(sig)
    vo_track = np.zeros(N, dtype=np.float32)
    vo_track[:len(vo)] += vo * 1.0

    sfx = np.zeros(N, dtype=np.float32)
    def place(track, s, t, g=1.0):
        i = int(t * SR); j = min(N, i + len(s))
        if i >= N:
            return
        track[i:j] += s[:j - i] * g

    place(sfx, sfx_impact(70, 40, 1.0), 0.0, 0.55)
    for (a, b), seg in zip(windows[1:], segs[1:]):
        place(sfx, sfx_whoosh(0.5), a - 0.12, 0.32)
    # CTA
    cta_t = windows[-1][0]
    place(sfx, sfx_subdrop(1.4), cta_t, 0.55)
    place(sfx, sfx_impact(58, 30, 1.4), cta_t, 0.55)

    mix = vo_track * 1.1 + sfx * 0.9
    mix = np.tanh(mix * 1.1)
    st = np.stack([mix, mix], axis=1)
    try:
        meter = pyln.Meter(SR)
        loud = meter.integrated_loudness(st)
        st = pyln.normalize.loudness(st, loud, -15.0)
    except Exception as e:
        print("loudnorm fallback:", e)
    peak = np.abs(st).max()
    if peak > 0.87:
        st = st * (0.87 / peak)
    st = st[:N]
    pcm = (np.clip(st, -1, 1) * 32767).astype(np.int16)
    import wave
    audio_out = os.path.join(work, "final_audio.wav")
    with wave.open(audio_out, "wb") as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())

    # ---- final: overlays + grade + audio ----
    inputs = ["-i", base]
    fparts = []; cur = "[0:v]"
    for k, e in enumerate(manifest):
        inputs += ["-loop", "1", "-t", f"{max(e['t1']-e['t0'], 0.05):.3f}", "-i", os.path.join(ovdir, e["file"])]
        fparts.append(f"[{k+1}:v]format=rgba,setpts=PTS-STARTPTS+{e['t0']}/TB[o{k}]")
        nxt = f"[v{k}]"
        fparts.append(f"{cur}[o{k}]overlay=x=0:y={e['y']}:enable='between(t,{e['t0']},{e['t1']})':eof_action=pass{nxt}")
        cur = nxt
    flashes = [("0.00", 0.45, 0.06)] + [(f"{round(windows[i][0], 2)}", 0.18, 0.06) for i in range(1, len(windows))]
    fx = ("eq=contrast=1.05:saturation=1.14:brightness=0.01,"
          "vignette=angle=PI/4.6,"
          "noise=alls=5:allf=t+u,"
          "unsharp=5:5:0.35:5:5:0.0")
    for (t0, a, dd) in flashes:
        fx += f",drawbox=t=fill:color=white@{a}:x=0:y=0:w={W}:h={H}:enable='between(t,{t0},{float(t0)+dd})'"
    fparts.append(f"{cur}{fx}[vout]")
    fc = ";".join(fparts)
    final = os.path.join(OUT, f"GTA6_var_{idx+1:02d}_{slug}.mp4")
    run([FF, "-y", *inputs, "-i", audio_out,
         "-filter_complex", fc, "-map", "[vout]", "-map", f"{len(manifest)+1}:a",
         "-t", f"{total:.3f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
         "-movflags", "+faststart", final])
    print(f"  OK -> {final} ({os.path.getsize(final)//1024} KB, {total:.2f}s)")
    return final

def main():
    slugs = sys.argv[1:]
    for idx, v in enumerate(VV.VARIATIONS):
        if slugs and v["slug"] not in slugs:
            continue
        try:
            build_variation(v, idx)
        except SystemExit:
            raise
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"!! FALHOU {v['slug']}: {e}")

if __name__ == "__main__":
    main()
