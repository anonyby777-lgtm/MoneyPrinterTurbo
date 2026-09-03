#!/usr/bin/env python3
"""Reconstrói o alpha da logo NUAKY7FX e regrava todos os vídeos com a nova marca.

A imagem `nuaky7fx_watermark.png` veio "achada" sobre um fundo claro quadriculado
(sem canal alpha útil: alpha=255 em tudo). Este script:

1. estima o fundo quadriculado com filtro de mediana (os traços da logo são mais
   finos que o kernel, então a mediana local approxima o fundo);
2. marca como tinta tudo que difere do fundo (sombra + glifos sobre quadrados
   cinza);
3. fecha morfologicamente os buracos restantes (glifo branco sobre quadrado
   branco é indistinguível — mas a zona ambígua é quase branca como a própria
   logo, então o fechamento não suja o resultado);
4. salva `brand/nuaky7fx_watermark_alpha.png` (RGBA de verdade);
5. para cada vídeo configurado: remove a marca antiga queimada (delogo com
   janela temporal, quando existir) e sobrepõe a nova logo no rodapé central;
6. grava em `projects/novo-projeto/videos_rebrand/` (H.264 crf 18, áudio copiado).

Uso:  python3 tools/rebrand_videos.py            # processa tudo
      python3 tools/rebrand_videos.py --only 14CC0727
      python3 tools/rebrand_videos.py --only-logo   # só reconstrói o PNG
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

FF = None  # resolvido em runtime (imageio-ffmpeg) ou ffmpeg do sistema


def find_ffmpeg() -> str:
    import shutil

    for cand in (
        "/tmp/ffenv/lib/python3.11/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2",
        shutil.which("ffmpeg"),
    ):
        if cand and Path(cand).exists():
            return cand
    raise SystemExit("ffmpeg não encontrado")


REPO = Path(__file__).resolve().parent.parent
LOGO_SRC = REPO / "nuaky7fx_font_gothic_clean.png"
LOGO_OUT = REPO / "projects" / "novo-projeto" / "brand" / "nuaky7fx_logo_alpha.png"
OUT_DIR = REPO / "projects" / "novo-projeto" / "videos_rebrand"

# Por vídeo: caixa da marca ANTIGA (delogo) + janela temporal, e geometria da nova.
# w = largura da nova logo em px; y_base = borda inferior do conteúdo (letterbox).
VIDEOS = {
    "14CC0727-9363-4294-B578-CEEE4E6C377F": {
        "old_mark": {"x": 452, "y": 602, "w": 386, "h": 36, "t0": 0.6, "t1": 19.5},
        "logo_w": 380,
        "y_base": 640,
        "note": "tinha '© 2026 Silent Cine. All Rights Reserved.' no rodapé",
    },
    "25B50E41-D64E-462F-97CC-F2D8C880E9B6": {
        "old_mark": None,
        "logo_w": 280,
        "y_base": 836,  # fim da área de conteúdo (letterbox 444..836)
        "note": "sem marca antiga detectada",
    },
    "B2DF9793-859B-43C7-B906-D2CE5E337AC9": {
        "old_mark": None,
        "logo_w": 280,
        "y_base": 1038,  # conteúdo 242..1038
        "note": "sem marca antiga detectada",
    },
    "FEA25167-3C0C-482D-A855-C6BEDA6B5D7F": {
        "old_mark": None,
        "logo_w": 320,
        "y_base": 718,
        "note": "sem marca antiga detectada",
    },
    "C534F059-6791-4FBA-BE24-79E5FC0DA2A6": {
        "old_mark": None,
        "logo_w": 430,
        "y_base": 800,
        "note": "sem marca antiga detectada",
    },
}


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe(path: Path) -> tuple[int, int, float]:
    out = run([FF, "-hide_banner", "-i", str(path)]).stderr
    line = [l for l in out.splitlines() if "Stream #0:0" in l][0]
    import re

    w, h = map(int, re.search(r"(\d{3,5})x(\d{3,5})", line).groups())
    dur_txt = out.split("Duration:")[1].split(",")[0].strip()
    if dur_txt == "N/A":  # imagem única
        return w, h, 0.0
    hh, mm, ss = dur_txt.split(":")
    return w, h, int(hh) * 3600 + int(mm) * 60 + float(ss)


def read_rgba(path: Path) -> np.ndarray:
    w, h, _ = probe(path)
    r = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-i", str(path),
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(h, w, 4)


def write_rgba(path: Path, arr: np.ndarray) -> None:
    h, w, _ = arr.shape
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FF, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-i", "-",
         str(path)],
        input=arr.tobytes(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )


def build_logo_alpha() -> Path:
    """Gera a versão com alpha real da NOVA logo (gótica, escolhida pelo usuário).

    `nuaky7fx_font_gothic_clean.png` é texto branco (com glow suave) sobre fundo
    preto puro, então o alpha sai direto da luminância — recorte perfeito, sem
    halo de fundo. O PNG `nuaky7fx_watermark.png` (variante fina) veio achatado
    sobre um quadriculado falso e não é usável como overlay; ficou só como
    referência em `brand/`.
    """
    rgba = read_rgba(LOGO_SRC)
    lum = rgba[:, :, :3].mean(axis=2)
    alpha = np.clip(lum / 255.0, 0, 1) ** 0.9  # leve gamma para preservar o glow
    ys, xs = np.where(alpha > 0.04)
    pad = 8
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + 1 + pad, lum.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + 1 + pad, lum.shape[1])
    rgb = rgba[y0:y1, x0:x1, :3].copy()
    rgb[lum[y0:y1, x0:x1] > 200] = [255, 255, 255]  # uniformiza o branco
    out = np.dstack([rgb, (alpha[y0:y1, x0:x1] * 255).astype(np.uint8)])
    write_rgba(LOGO_OUT, out)
    print(f"logo com alpha: {LOGO_OUT.relative_to(REPO)} ({x1 - x0}x{y1 - y0})")
    return LOGO_OUT


def rebrand(stem: str, cfg: dict, logo: Path) -> dict:
    src = next(REPO.glob(f"{stem}*.mp4"))
    w, h, dur = probe(src)
    lw = cfg["logo_w"]
    x = (w - lw) // 2
    base = "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2[base]"
    if cfg["old_mark"]:
        m = cfg["old_mark"]
        base = (
            f"[0:v]delogo=x={m['x']}:y={m['y']}:w={m['w']}:h={m['h']}"
            f":enable='between(t,{m['t0']},{m['t1']})'[dv];"
            f"[dv]scale=trunc(iw/2)*2:trunc(ih/2)*2[base]"
        )
    fc = (
        f"{base};[1:v]scale={lw}:-2[lg];"
        f"[base][lg]overlay=x={x}:y={cfg['y_base']}-10-h[vout]"
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / f"{stem}_nuaky7fx.mp4"
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(src), "-i", str(logo),
           "-filter_complex", fc,
           "-map", "[vout]", "-map", "0:a?",
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", "-c:a", "copy", str(dst)]
    r = run(cmd)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise SystemExit(f"falha ao processar {stem}")
    size = dst.stat().st_size
    print(f"ok: {dst.relative_to(REPO)} ({size / 1048576:.1f} MB, {dur:.1f}s)")
    return {"file": dst.name, "source": src.name, "bytes": size,
            "old_mark_removed": bool(cfg["old_mark"]), "note": cfg["note"],
            "logo": str(logo.relative_to(REPO)), "added_at": _now()}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    global FF
    FF = find_ffmpeg()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="processa só o vídeo cujo stem começa com este prefixo")
    ap.add_argument("--only-logo", action="store_true", help="só reconstrói o PNG com alpha")
    args = ap.parse_args()

    logo = build_logo_alpha()
    if args.only_logo:
        return

    manifest_path = REPO / "projects" / "novo-projeto" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    done = []
    for stem, cfg in VIDEOS.items():
        if args.only and not stem.startswith(args.only):
            continue
        done.append(rebrand(stem, cfg, logo))
    manifest["rebrand"] = {
        "logo": str(logo.relative_to(REPO)),
        "output_dir": "projects/novo-projeto/videos_rebrand",
        "encoder": "libx264 crf 18, audio copy",
        "updated_at": _now(),
        "videos": done,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest atualizado: {len(done)} vídeo(s)")


if __name__ == "__main__":
    main()
