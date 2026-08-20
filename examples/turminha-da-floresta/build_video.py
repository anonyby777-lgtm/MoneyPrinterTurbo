#!/usr/bin/env python3
"""Renderiza a cena final de 'A Turminha da Floresta e o Trem das Cores'
a partir dos keyframes + storyboard, com movimento de camera, textos,
narracao, trilha e efeitos sonoros."""
import json
import os
import subprocess
import shlex

FF = "/home/user/bin/ffmpeg"
KF = "/home/user/src_pvc/keyframes"
VO = "/home/user/build/vo"
AU = "/home/user/build/audio"
TX = "/home/user/build/text"
WORK = "/home/user/build/clips"
OUTDIR = "/home/user/output"
FPS = 30
W, H = 1920, 1080

os.makedirs(WORK, exist_ok=True)
os.makedirs(OUTDIR, exist_ok=True)


def run(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr[-3000:])
        raise SystemExit(f"FAIL: {cmd[:200]}")
    return p


# shot_id, image, duration, zoom_start, zoom_end, x_expr_extra, y_expr_extra
SHOTS = [
    ("shot01", "01_group_front_train.jpg", 4.0,   1.00, 1.12, "0", "0"),
    ("shot02", "02_red_tico.jpg",          4.5,   1.04, 1.14, "0", "0"),
    ("shot03", "03_blue_bibi.jpg",         4.5,   1.04, 1.14, "0", "0"),
    ("shot04", "04_yellow_nino.jpg",       4.5,   1.04, 1.14, "0", "0"),
    ("shot05", "05_purple_luma.jpg",       4.5,   1.04, 1.14, "0", "0"),
    ("shot06", "06_celebration_jump.jpg",  4.0,   1.14, 1.02, "0", "0"),
    ("shot07", "07_bibi_camera.jpg",       5.0,   1.16, 1.26, "0", "0"),
    ("shot08", "01_group_front_train.jpg", 3.5,   1.10, 1.14,
     "60*sin(2*PI*on/({F}-1))", "0"),
    ("shot09", "08_wave_goodbye.jpg",      5.0,   1.06, 1.12,
     "70*sin(2*PI*on/({F}-1))", "0"),
    ("shot10", "09_wide_ending.jpg",       7.0,   1.20, 1.00,
     "0", "-120*on/({F}-1)"),
]

SRC_W, SRC_H = 3840, 2160

for sid, img, dur, z0, z1, xoff, yoff in SHOTS:
    frames = int(round(dur * FPS))
    z = f"{z0}+({z1}-{z0})*on/({frames}-1)"
    xo = xoff.replace("{F}", str(frames))
    yo = yoff.replace("{F}", str(frames))
    x = f"(iw-iw/zoom)/2+({xo})"
    y = f"(ih-ih/zoom)/2+({yo})"
    vf = (
        f"scale={SRC_W}:{SRC_H}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={SRC_W}:{SRC_H},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
        f"eq=saturation=1.10:contrast=1.03,format=yuv420p"
    )
    out = f"{WORK}/{sid}.mp4"
    if os.path.exists(out) and os.path.getsize(out) > 10000 :
        print("skip", sid); continue
    run(f'{FF} -y -loglevel error -loop 1 -i "{KF}/{img}" -t {dur} '
        f'-vf "{vf}" -r {FPS} -c:v libx264 -preset medium -crf 17 '
        f'-pix_fmt yuv420p "{out}"')
    print("clip", sid, dur, "s")

# ---- concat com cortes suaves (crossfade curto) ----
with open(f"{WORK}/list.txt", "w") as fh:
    for sid, *_ in SHOTS:
        fh.write(f"file '{WORK}/{sid}.mp4'\n")
run(f'{FF} -y -loglevel error -f concat -safe 0 -i "{WORK}/list.txt" '
    f'-c copy "{WORK}/base.mp4"')
print("concat ok")

# ---- overlays de texto ----
TEXTS = [
    ("vermelho.png", 4.6, 8.4),
    ("azul.png", 9.1, 12.9),
    ("amarelo.png", 13.6, 17.4),
    ("roxo.png", 18.1, 21.9),
    ("muitobem.png", 22.3, 25.8),
    ("pergunta.png", 26.4, 30.9),
    ("tchau.png", 34.8, 39.3),
]
import json as _json
POS = _json.load(open(f"{TX}/pos.json"))
inputs = f'-i "{WORK}/base.mp4" '
filt = []
last = "[0:v]"
for i, (png, t0, t1) in enumerate(TEXTS):
    inputs += f'-loop 1 -framerate {FPS} -t 47 -i "{TX}/{png}" '
    idx = i + 1
    fin, fout = 0.35, 0.35
    filt.append(
        f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS+{t0}/TB,"
        f"fade=t=in:st={t0}:d={fin}:alpha=1,"
        f"fade=t=out:st={t1 - fout}:d={fout}:alpha=1[t{idx}]")
    px, py = POS[png]
    filt.append(
        f"{last}[t{idx}]overlay={px}:{py}:enable='between(t,{t0},{t1})'[v{idx}]")
    last = f"[v{idx}]"
filt.append(f"{last}fade=t=in:st=0:d=0.8,fade=t=out:st=45.6:d=0.9[vout]")
fc = ";".join(filt)
run(f'{FF} -y -loglevel error {inputs} -filter_complex "{fc}" -map "[vout]" '
    f'-c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -r {FPS} '
    f'"{WORK}/video_nosound.mp4"')
print("overlays ok")

# ---- mixagem de audio ----
# (arquivo, inicio_s, ganho_db)
AUDIO = [
    (f"{AU}/bgm.wav", 0.0, -1.0),
    (f"{VO}/01_luma_vamos_lembrar.mp3", 0.5, 3.0),
    (f"{AU}/sfx_sparkle.wav", 4.1, -7.0),
    (f"{VO}/02_tico_vermelho.mp3", 4.7, 3.0),
    (f"{AU}/sfx_sparkle.wav", 8.6, -7.0),
    (f"{VO}/03_bibi_azul.mp3", 9.2, 3.0),
    (f"{AU}/sfx_sparkle.wav", 13.1, -7.0),
    (f"{VO}/04_nino_amarelo.mp3", 13.7, 3.0),
    (f"{AU}/sfx_sparkle.wav", 17.6, -7.0),
    (f"{VO}/05_luma_roxo.mp3", 18.2, 3.0),
    (f"{AU}/sfx_confetti.wav", 22.0, -6.0),
    (f"{VO}/08a_tico_muito_bem.mp3", 22.4, 2.0),
    (f"{VO}/08b_bibi_muito_bem.mp3", 22.45, 1.0),
    (f"{VO}/06_bibi_cor_favorita.mp3", 26.5, 3.0),
    (f"{AU}/sfx_sparkle.wav", 29.2, -10.0),
    (f"{VO}/07_nino_todas.mp3", 31.3, 3.0),
    (f"{VO}/09_todos_tchau.mp3", 34.9, 3.0),
    (f"{AU}/sfx_whistle.wav", 36.5, -8.0),
    (f"{AU}/sfx_chuff.wav", 40.0, -12.0),
]
ain = " ".join(f'-i "{f}"' for f, _, _ in AUDIO)
af = []
labels = []
for i, (f, at, g) in enumerate(AUDIO):
    lab = f"a{i}"
    af.append(f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:"
              f"channel_layouts=stereo,volume={g}dB,"
              f"adelay={int(at*1000)}|{int(at*1000)}[{lab}]")
    labels.append(f"[{lab}]")
af.append("".join(labels) + f"amix=inputs={len(AUDIO)}:normalize=0:"
          f"dropout_transition=0,alimiter=limit=0.95,"
          f"atrim=0:46.5,afade=t=out:st=45.6:d=0.9[aout]")
run(f'{FF} -y -loglevel error {ain} -filter_complex "{";".join(af)}" '
    f'-map "[aout]" -c:a pcm_s16le "{WORK}/mix.wav"')
print("mix ok")

final = f"{OUTDIR}/turminha_da_floresta_cena_final_16x9.mp4"
run(f'{FF} -y -loglevel error -i "{WORK}/video_nosound.mp4" -i "{WORK}/mix.wav" '
    f'-map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest '
    f'-movflags +faststart "{final}"')
print("FINAL:", final)
