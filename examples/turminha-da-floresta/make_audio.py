import numpy as np, wave, os

SR = 44100
OUT = "/home/user/build/audio"
os.makedirs(OUT, exist_ok=True)


def write(path, data):
    d = np.clip(data, -1, 1)
    pcm = (d * 32767).astype(np.int16)
    if pcm.ndim == 1:
        pcm = np.stack([pcm, pcm], axis=1)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(path, round(len(d) / SR, 2), "s")


def env(n, a=0.01, d=0.1, s=0.7, r=0.2, sus_level=0.6):
    t = np.arange(n) / SR
    total = n / SR
    e = np.ones(n)
    ai = int(a * SR)
    di = int(d * SR)
    ri = int(r * SR)
    if ai:
        e[:ai] = np.linspace(0, 1, ai)
    if di:
        e[ai:ai + di] = np.linspace(1, sus_level, di)
    e[ai + di:n - ri] = sus_level
    if ri:
        e[n - ri:] = np.linspace(sus_level, 0, ri)
    return e


def note(freq, dur, kind="bell", amp=0.3):
    n = int(dur * SR)
    t = np.arange(n) / SR
    if kind == "bell":
        y = (np.sin(2 * np.pi * freq * t) * 1.0
             + np.sin(2 * np.pi * freq * 2 * t) * 0.35
             + np.sin(2 * np.pi * freq * 3.01 * t) * 0.12)
        e = np.exp(-t * 3.2)
    elif kind == "marimba":
        y = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * freq * 4 * t)
        e = np.exp(-t * 6.0)
    elif kind == "pad":
        y = (np.sin(2 * np.pi * freq * t)
             + 0.5 * np.sin(2 * np.pi * freq * 1.005 * t)
             + 0.3 * np.sin(2 * np.pi * freq * 2 * t))
        e = env(n, a=0.25, d=0.2, r=0.5, sus_level=0.75)
    elif kind == "pluck":
        y = np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * freq * 2 * t)
        e = np.exp(-t * 9.0)
    else:
        y = np.sin(2 * np.pi * freq * t)
        e = env(n)
    return amp * y * e


def f(nm):
    names = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
             "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    p = nm[:-1]
    octv = int(nm[-1])
    midi = 12 * (octv + 1) + names[p]
    return 440.0 * 2 ** ((midi - 69) / 12)


def place(buf, sig, at):
    i = int(at * SR)
    j = min(len(buf), i + len(sig))
    if i < len(buf):
        buf[i:j] += sig[:j - i]


TOTAL = 47.5
N = int(TOTAL * SR)

# ---------- BGM: cheerful C major kids tune, 100 bpm ----------
bgm = np.zeros(N)
bpm = 100.0
beat = 60.0 / bpm  # 0.6s

# chord progression per 2 bars (4/4): C - F - G - C ...
prog = ["C", "F", "G", "C", "Am", "F", "G", "C"]
chords = {
    "C": ["C3", "E3", "G3", "C4"],
    "F": ["F3", "A3", "C4", "F4"],
    "G": ["G3", "B3", "D4", "G4"],
    "Am": ["A3", "C4", "E4", "A4"],
}
bar = beat * 4
nbars = int(TOTAL / bar) + 1
for b in range(nbars):
    ch = prog[b % len(prog)]
    t0 = b * bar
    for nm in chords[ch]:
        place(bgm, note(f(nm), bar * 1.05, "pad", amp=0.055), t0)
    # bass pulse
    root = chords[ch][0]
    for k in range(4):
        place(bgm, note(f(root) / 2, beat * 0.9, "pluck", amp=0.10), t0 + k * beat)

# melody: simple, singable, repeating motif
motif = [("C5", 1), ("E5", 1), ("G5", 1), ("E5", 1),
         ("F5", 1), ("A5", 1), ("G5", 2),
         ("G5", 1), ("F5", 1), ("E5", 1), ("D5", 1),
         ("C5", 2), ("E5", 1), ("G5", 1)]
t = 0.0
while t < TOTAL:
    for nm, dur in motif:
        if t >= TOTAL:
            break
        place(bgm, note(f(nm), dur * beat * 0.95, "marimba", amp=0.085), t)
        t += dur * beat

# gentle sparkle arpeggios on top every 2 bars
t = 0.0
while t < TOTAL:
    for k, nm in enumerate(["C6", "E6", "G6"]):
        place(bgm, note(f(nm), 0.8, "bell", amp=0.035), t + k * 0.12)
    t += bar * 2

# swell at the finale (39.5 -> 46.5)
tt = np.arange(N) / SR
swell = np.ones(N)
mask = tt >= 39.5
swell[mask] = 1.0 + 0.45 * np.clip((tt[mask] - 39.5) / 5.0, 0, 1)
bgm *= swell

# final chord
for nm in ["C4", "E4", "G4", "C5"]:
    place(bgm, note(f(nm), 3.0, "bell", amp=0.14), 43.6)

# fade in / out
fi = int(1.2 * SR)
bgm[:fi] *= np.linspace(0, 1, fi)
fo_start = int(45.5 * SR)
bgm[fo_start:] *= np.linspace(1, 0, N - fo_start)

write(f"{OUT}/bgm.wav", bgm * 0.9)

# ---------- SFX ----------
# sparkle chime (rising bells)
n = int(1.1 * SR)
sp = np.zeros(n)
for k, nm in enumerate(["C6", "E6", "G6", "C7"]):
    place(sp, note(f(nm), 0.9, "bell", amp=0.30 - k * 0.04), k * 0.06)
write(f"{OUT}/sfx_sparkle.wav", sp)

# train whistle PII! PII!
def whistle(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    base = 880.0
    y = np.zeros(n)
    for mult, a in [(1, 0.5), (1.5, 0.32), (2.02, 0.2), (3.0, 0.1)]:
        vib = 1 + 0.012 * np.sin(2 * np.pi * 6.5 * t)
        y += a * np.sin(2 * np.pi * base * mult * vib * t)
    breath = 0.06 * np.random.RandomState(3).normal(0, 1, n)
    y = y + breath
    e = env(n, a=0.05, d=0.08, r=0.22, sus_level=0.85)
    return 0.32 * y * e

wl = np.zeros(int(2.0 * SR))
place(wl, whistle(0.55), 0.0)
place(wl, whistle(0.7), 0.75)
write(f"{OUT}/sfx_whistle.wav", wl)

# confetti / celebration pop burst
rs = np.random.RandomState(7)
n = int(1.6 * SR)
cf = np.zeros(n)
for k in range(14):
    at = rs.uniform(0, 0.9)
    fr = rs.uniform(600, 1800)
    cf_n = int(0.18 * SR)
    tt2 = np.arange(cf_n) / SR
    pop = 0.18 * np.sin(2 * np.pi * fr * tt2) * np.exp(-tt2 * 28)
    place(cf, pop, at)
for k, nm in enumerate(["G5", "C6", "E6", "G6"]):
    place(cf, note(f(nm), 1.0, "bell", amp=0.16), k * 0.07)
write(f"{OUT}/sfx_confetti.wav", cf)

# soft chuff / steam for the departure
n = int(6.0 * SR)
rs = np.random.RandomState(11)
steam = rs.normal(0, 1, n)
# simple lowpass
b = np.ones(60) / 60
steam = np.convolve(steam, b, mode="same")
ch = np.zeros(n)
t0 = 0.0
k = 0
while t0 < 5.4:
    seg = int(0.25 * SR)
    tt3 = np.arange(seg) / SR
    puff = np.convolve(rs.normal(0, 1, seg), np.ones(40) / 40, mode="same")
    puff *= np.exp(-tt3 * 12)
    place(ch, 0.22 * puff, t0)
    t0 += 0.62 + k * 0.02
    k += 1
write(f"{OUT}/sfx_chuff.wav", ch)
print("audio ok")
