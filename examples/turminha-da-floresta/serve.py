#!/usr/bin/env python3
"""Servidor simples com suporte a Range (necessario para <video> no
iOS/Safari e Chrome mobile) para assistir/baixar os videos gerados."""
import os
import re
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(ROOT, "video")
PORT = int(os.environ.get("PORT", "8000"))

VIDEOS = [
    ("turminha_da_floresta_cena_final_16x9.mp4",
     "Versao horizontal 16:9", "1920x1080 &middot; 46,5s &middot; YouTube/TV"),
    ("turminha_da_floresta_cena_final_9x16.mp4",
     "Versao vertical 9:16", "1080x1920 &middot; 46,5s &middot; Shorts/Reels/TikTok"),
]


def human(n):
    return f"{n / 1024 / 1024:.1f} MB"


def page():
    cards = []
    for fname, title, meta in VIDEOS:
        path = os.path.join(VIDEO_DIR, fname)
        if not os.path.exists(path):
            continue
        size = human(os.path.getsize(path))
        cards.append(f"""
      <section class="card">
        <h2>{title}</h2>
        <p class="meta">{meta} &middot; {size}</p>
        <video controls preload="metadata" playsinline
               poster="/poster/{fname}.jpg">
          <source src="/video/{fname}" type="video/mp4">
        </video>
        <a class="dl" href="/video/{fname}" download>Baixar este video</a>
      </section>""")
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>A Turminha da Floresta - Cena Final</title>
<style>
  *{{box-sizing:border-box}}
  body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:linear-gradient(170deg,#2b1b47 0%,#43265f 45%,#6b3a6e 100%);
       color:#fff;min-height:100vh;padding:20px 16px 48px}}
  header{{text-align:center;margin:8px 0 26px}}
  h1{{font-size:1.45rem;line-height:1.25;margin:0 0 6px;
      background:linear-gradient(90deg,#ffb347,#ff7ac6,#7ad7ff);
      -webkit-background-clip:text;background-clip:text;color:transparent}}
  header p{{margin:0;opacity:.75;font-size:.9rem}}
  .card{{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);
        border-radius:18px;padding:16px;margin:0 auto 22px;max-width:760px;
        backdrop-filter:blur(6px)}}
  h2{{font-size:1.05rem;margin:0 0 4px}}
  .meta{{margin:0 0 12px;font-size:.82rem;opacity:.7}}
  video{{width:100%;border-radius:12px;background:#000;display:block}}
  .dl{{display:block;text-align:center;margin-top:12px;padding:13px;
      border-radius:12px;text-decoration:none;font-weight:700;color:#2b1b47;
      background:linear-gradient(90deg,#ffd07a,#ff9ad0)}}
  .dl:active{{opacity:.75}}
  footer{{text-align:center;font-size:.78rem;opacity:.6;max-width:760px;
         margin:6px auto 0;line-height:1.5}}
</style>
</head>
<body>
  <header>
    <h1>A Turminha da Floresta<br>e o Trem das Cores</h1>
    <p>Cena Final &middot; O Festival das Cores</p>
  </header>
  {''.join(cards)}
  <footer>Toque no play para assistir, ou use o botao para salvar no celular.</footer>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def _send_html(self, body):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, path, head_only=False):
        if not os.path.isfile(path):
            self.send_error(404, "Not found")
            return
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
            if m:
                s, e = m.group(1), m.group(2)
                if s:
                    start = int(s)
                    if e:
                        end = min(int(e), size - 1)
                else:  # suffix range
                    start = max(0, size - int(e))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    def _route(self, head_only=False):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            if head_only:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
            else:
                self._send_html(page())
            return
        if p.startswith("/video/"):
            name = os.path.basename(p)
            self._serve_file(os.path.join(VIDEO_DIR, name), head_only)
            return
        if p.startswith("/poster/"):
            name = os.path.basename(p)
            self._serve_file(os.path.join(ROOT, "posters", name), head_only)
            return
        self.send_error(404, "Not found")

    def do_GET(self):
        self._route(False)

    def do_HEAD(self):
        self._route(True)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Servindo em http://0.0.0.0:{PORT}")
    srv.serve_forever()
