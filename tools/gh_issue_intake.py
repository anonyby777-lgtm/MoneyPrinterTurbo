#!/usr/bin/env python3
"""Baixa vídeos/anexos enviados por uma Issue do GitHub para dentro de um projeto.

Fluxo pensado para quem não quer (ou não pode) subir vídeos pesados por git push:
você arrasta os vídeos no corpo/comentários de uma Issue e este script coleta
todos os anexos e grava na pasta ``videos/`` do projeto, atualizando o
``manifest.json`` e opcionalmente fazendo commit+push.

Só usa a biblioteca padrão do Python (nada de pip install).

Exemplos
--------
    # 1) baixar tudo que foi anexado numa issue
    python3 tools/gh_issue_intake.py https://github.com/USER/REPO/issues/1

    # 2) forma curta + token (necessário para repositório privado)
    GH_TOKEN=ghp_xxx python3 tools/gh_issue_intake.py USER/REPO#1

    # 3) escolher o projeto de destino e já commitar/pushear
    python3 tools/gh_issue_intake.py USER/REPO#1 -p projects/novo-projeto --push

    # 4) listar o que seria baixado, sem gravar nada
    python3 tools/gh_issue_intake.py USER/REPO#1 --dry-run

    # 5) importar um .zip anexado na issue, extraindo os vídeos de dentro
    python3 tools/gh_issue_intake.py USER/REPO#1 --unzip

    # 6) versão automática: dentro de um GitHub Actions Workflow
    python3 tools/gh_issue_intake.py "$ISSUE_URL" --push --json-out /tmp/intake.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = "https://api.github.com"
USER_AGENT = "moneyprinterturbo-intake/1.0"

VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".flv", ".wmv", ".mpg", ".mpeg", ".3gp")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
ARCHIVE_EXTS = (".zip",)

DEFAULT_PROJECT = "projects/novo-projeto"
# O GitHub bloqueia push de arquivos > 100 MB e avisa a partir de 50 MB.
MAX_COMMIT_BYTES = 90 * 1024 * 1024

# Anexos de issue viram URLs assim:
#   https://github.com/user-attachments/assets/<uuid>
#   https://user-images.githubusercontent.com/<id>/<num>/<hash>/<file>.mp4
#   https://private-user-images.githubusercontent.com/...?<assinatura>
ASSET_URL_RE = re.compile(
    r"https?://(?:github\.com/user-attachments/assets/[0-9a-fA-F-]+"
    r"|(?:private-)?user-images\.githubusercontent\.com/[^\s)\"'<>]+)",
    re.IGNORECASE,
)

ISSUE_REF_RE = re.compile(
    r"^(?:(?P<url>https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<num>\d+))"
    r"|(?P<short>(?P<sowner>[^/\s]+)/(?P<srepo>[^#\s]+)#(?P<snum>\d+)))$"
)


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"erro: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def parse_issue_ref(raw: str) -> tuple[str, str, int]:
    """Aceita URL completa de issue ou a forma curta ``owner/repo#123``."""
    match = ISSUE_REF_RE.match(raw.strip())
    if not match:
        die(f"referência de issue inválida: {raw!r} (use a URL da issue ou owner/repo#numero)")
    if match.group("url"):
        return match.group("owner"), match.group("repo"), int(match.group("num"))
    return match.group("sowner"), match.group("srepo"), int(match.group("snum"))


def gh_request(url: str, token: str | None, accept: str = "application/vnd.github+json") -> tuple[bytes, dict]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:  # pragma: no cover - depende de rede
        body = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 404:
            die(f"{url} não encontrado (404). Issue inexistente ou repositório privado sem token.")
        if exc.code in (401, 403):
            die(f"sem permissão para acessar {url} ({exc.code}). Defina GH_TOKEN/GITHUB_TOKEN.")
        die(f"falha HTTP {exc.code} em {url}: {body}")
    except urllib.error.URLError as exc:  # pragma: no cover - depende de rede
        die(f"falha de rede ao acessar {url}: {exc.reason}")
    return b"", {}  # unreachable


def collect_texts(owner: str, repo: str, number: int, token: str | None) -> list[dict]:
    """Retorna [{'where', 'author', 'created_at', 'body'}] da issue e dos comentários."""
    base = f"{API_ROOT}/repos/{owner}/{repo}/issues/{number}"
    body_raw, _ = gh_request(base, token)
    issue = json.loads(body_raw)
    if "pull_request" in issue:
        log("aviso: a referência aponta para um pull request; seguindo mesmo assim.")
    entries = [
        {
            "where": f"#{number} (corpo)",
            "author": (issue.get("user") or {}).get("login", "?"),
            "created_at": issue.get("created_at", ""),
            "body": issue.get("body") or "",
        }
    ]
    comments_url = f"{base}/comments?per_page=100"
    page = 1
    while comments_url:
        raw, headers = gh_request(comments_url, token)
        for comment in json.loads(raw):
            entries.append(
                {
                    "where": f"#{number} (comentário)",
                    "author": (comment.get("user") or {}).get("login", "?"),
                    "created_at": comment.get("created_at", ""),
                    "body": comment.get("body") or "",
                }
            )
        comments_url = None
        link = headers.get("Link") or headers.get("link") or ""
        for part in link.split(","):
            if 'rel="next"' in part:
                comments_url = part[part.index("<") + 1 : part.index(">")]
        page += 1
        if page > 20:  # proteção contra loop infinito
            break
    return entries


def extract_assets(entries: list[dict]) -> list[dict]:
    """Extrai URLs de anexo preservando ordem e eliminando duplicatas."""
    seen: set[str] = set()
    assets: list[dict] = []
    for entry in entries:
        for url in ASSET_URL_RE.findall(entry["body"]):
            key = url.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            assets.append({**entry, "url": url})
    return assets


def looks_like_video(url: str, content_type: str, filename_hint: str) -> bool:
    name = (filename_hint or os.path.basename(urllib.parse.urlparse(url).path)).lower()
    if name.endswith(VIDEO_EXTS):
        return True
    if content_type.startswith("video/"):
        return True
    return False


def safe_filename(raw: str, fallback: str) -> str:
    name = os.path.basename(raw or "").strip()
    name = urllib.parse.unquote(name)
    name = re.sub(r"[^\w.\-]+", "-", name, flags=re.UNICODE).strip("-.")
    name = re.sub(r"-{2,}", "-", name)
    return name[:120] or fallback


def content_disposition_filename(headers: dict) -> str:
    header = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header, re.IGNORECASE)
    return urllib.parse.unquote(match.group(1)) if match else ""


def download(url: str, token: str | None) -> tuple[bytes, dict]:
    headers = {
        "User-Agent": USER_AGENT,
        # user-attachments/assets responde com o binário seguindo redirect.
        "Accept": "*/*",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (403, 404, 410):
                break
            time.sleep(2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
            last_exc = exc
            if _is_blocked_egress(exc):
                break
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"não foi possível baixar {url}: {last_exc}{_egress_hint(last_exc)}")


BLOCKED_EGRESS_MARKERS = (
    "tls/ssl connection has been closed",
    "ssl_error_syscall",
    "connection reset by peer",
    "certificate verify failed",
)


def _is_blocked_egress(exc: Exception) -> bool:
    """Detecta rede com egress filtrado (ex.: sandbox) no meio do download.

    Os anexos de issue ficam em ``github-production-user-asset-*.s3.amazonaws.com``;
    ambientes que só liberam ``github.com``/``api.github.com`` fecham a conexão TLS
    nesse redirect, e insistir no retry só queima tempo.
    """
    text = str(exc).lower()
    if any(marker in text for marker in BLOCKED_EGRESS_MARKERS):
        return True
    reason = getattr(exc, "reason", None)
    return reason is not None and any(marker in str(reason).lower() for marker in BLOCKED_EGRESS_MARKERS)


def _egress_hint(exc: Exception | None) -> str:
    if exc is not None and _is_blocked_egress(exc):
        return (
            " — a conexão foi derrubada no redirect para o storage do GitHub "
            "(github-production-user-asset-*.s3.amazonaws.com). Isso é típico de rede/sandbox "
            "com egress filtrado: rode este script na sua máquina ou deixe o GitHub Actions "
            "fazer o download (intake/video-intake.yml)."
        )
    return ""


def unique_path(directory: Path, filename: str) -> Path:
    target = directory / filename
    if not target.exists():
        return target
    stem, suffix = os.path.splitext(filename)
    for index in range(2, 1000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}-{int(time.time())}{suffix}"


def load_manifest(project_dir: Path) -> dict:
    manifest_path = project_dir / "manifest.json"
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log(f"aviso: {manifest_path} inválido; criando um novo.")
    return {"project": project_dir.name, "created": _now(), "videos": []}


def save_manifest(project_dir: Path, manifest: dict) -> None:
    manifest["updated"] = _now()
    (project_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def unzip_into(data: bytes, videos_dir: Path, manifest: dict, source_url: str) -> list[dict]:
    added: list[dict] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        log("  aviso: .zip corrompido ou não é um zip; ignorado.")
        return added
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = os.path.basename(info.filename)
        if not name.lower().endswith(VIDEO_EXTS + IMAGE_EXTS):
            continue
        payload = archive.read(info)
        target = unique_path(videos_dir, safe_filename(name, "video.mp4"))
        target.write_bytes(payload)
        added.append(_record(target, payload, source_url, f"zip:{name}"))
    return added


def _record(target: Path, payload: bytes, source_url: str, note: str) -> dict:
    return {
        "file": target.name,
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "source": source_url,
        "note": note,
        "added_at": _now(),
        "committable": len(payload) <= MAX_COMMIT_BYTES,
    }


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or " ".join(args))
    return result.stdout.strip()


def write_summary(path: str, summary: dict) -> None:
    """Grava o resumo da execução em JSON (usado pelo GitHub Actions)."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"resumo JSON: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Coleta vídeos anexados em uma Issue do GitHub e salva no projeto.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Exemplos")[-1],
    )
    parser.add_argument("issue", help="URL da issue ou owner/repo#numero")
    parser.add_argument(
        "-p", "--project", default=DEFAULT_PROJECT,
        help=f"pasta do projeto de destino (padrão: {DEFAULT_PROJECT})",
    )
    parser.add_argument(
        "--kind", choices=("video", "all"), default="video",
        help="baixa só vídeos (padrão) ou qualquer anexo",
    )
    parser.add_argument("--unzip", action="store_true", help="extrai vídeos de .zip anexados")
    parser.add_argument("--dry-run", action="store_true", help="lista o que baixaria, sem gravar")
    parser.add_argument("--push", action="store_true", help="commit + push após baixar (branch atual)")
    parser.add_argument(
        "--json-out", metavar="ARQUIVO",
        help="grava um resumo JSON da execução (útil para GitHub Actions resumir na issue)",
    )
    parser.add_argument(
        "--token", default=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"),
        help="token do GitHub (obrigatório para repo privado; também via GH_TOKEN)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    project_dir = (repo_root / args.project).resolve()
    videos_dir = project_dir / "videos"
    intake_dir = project_dir / "intake"

    owner, repo, number = parse_issue_ref(args.issue)
    log(f"issue: {owner}/{repo}#{number}")

    entries = collect_texts(owner, repo, number, args.token)
    assets = extract_assets(entries)
    if not assets:
        log("nenhum anexo encontrado na issue ou nos comentários.")
        log("dica: arraste o vídeo para dentro da caixa de texto da issue e clique em Comment.")
        if args.json_out:
            write_summary(args.json_out, {
                "issue": f"{owner}/{repo}#{number}",
                "issue_url": f"https://github.com/{owner}/{repo}/issues/{number}",
                "project": str(project_dir.relative_to(repo_root)),
                "assets_found": 0,
                "saved": [],
                "skipped": [],
                "oversize": [],
                "push": "não solicitado",
                "finished_at": _now(),
            })
        return

    log(f"{len(assets)} anexo(s) encontrado(s):")
    for asset in assets:
        log(f"  - [{asset['where']} por {asset['author']}] {asset['url']}")

    if args.dry_run:
        log("dry-run: nada foi gravado.")
        if args.json_out:
            write_summary(args.json_out, {
                "issue": f"{owner}/{repo}#{number}",
                "issue_url": f"https://github.com/{owner}/{repo}/issues/{number}",
                "project": str(project_dir.relative_to(repo_root)),
                "assets_found": len(assets),
                "assets": [a["url"] for a in assets],
                "saved": [],
                "skipped": [],
                "oversize": [],
                "push": "dry-run",
                "finished_at": _now(),
            })
        return

    videos_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "README.md").exists() or intake_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(project_dir)
    known = {item.get("sha256") for item in manifest.get("videos", [])}
    saved: list[dict] = []
    skipped: list[str] = []

    for asset in assets:
        url = asset["url"]
        try:
            data, headers = download(url, args.token)
        except RuntimeError as exc:
            skipped.append(f"{url} ({exc})")
            continue

        content_type = (headers.get("Content-Type") or headers.get("content-type") or "").split(";")[0].strip()
        hint = content_disposition_filename(headers)
        digest = sha256_bytes(data)
        if digest in known:
            skipped.append(f"{url} (duplicado, já está no projeto)")
            continue

        is_archive = hint.lower().endswith(ARCHIVE_EXTS) or content_type in (
            "application/zip",
            "application/x-zip-compressed",
        )
        if is_archive and args.unzip:
            extracted = unzip_into(data, videos_dir, manifest, url)
            if extracted:
                saved.extend(extracted)
                known.update(item["sha256"] for item in extracted)
                log(f"  zip {url}: {len(extracted)} vídeo(s) extraído(s)")
                continue

        if args.kind == "video" and not looks_like_video(url, content_type, hint):
            skipped.append(f"{url} (não parece vídeo: {content_type or 'tipo desconhecido'}; use --kind all)")
            continue

        fallback = f"video-{len(saved) + 1}.mp4"
        name = safe_filename(hint or os.path.basename(urllib.parse.urlparse(url).path), fallback)
        if "." not in name:
            name += ".mp4"
        target = unique_path(videos_dir, name)
        target.write_bytes(data)
        record = _record(target, data, url, f"issue {owner}/{repo}#{number}")
        saved.append(record)
        known.add(digest)
        size_mb = len(data) / (1024 * 1024)
        log(f"  salvo: {target.relative_to(repo_root)} ({size_mb:.1f} MB)")

    if saved:
        manifest.setdefault("videos", []).extend(saved)
        save_manifest(project_dir, manifest)

    log("")
    log(f"concluído: {len(saved)} arquivo(s) salvo(s), {len(skipped)} ignorado(s).")
    for item in skipped:
        log(f"  ignorado: {item}")

    oversize = [item["file"] for item in saved if not item.get("committable", True)]
    if oversize:
        log("")
        log(f"atenção: {len(oversize)} arquivo(s) acima de {MAX_COMMIT_BYTES // (1024 * 1024)} MB "
            "(o GitHub recusa push > 100 MB): " + ", ".join(oversize))
        log("use Git LFS, um Release, ou reduza o vídeo antes de commitar.")

    push_result = "não solicitado"
    if args.push and saved:
        push_result = "falhou"
        try:
            branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root)
            committable = [item for item in saved if item.get("committable", True)]
            if not committable:
                push_result = "nada commitável (todos acima do limite do git)"
                log(push_result + "; push ignorado.")
            else:
                for item in committable:
                    # -f porque projects/*/videos/.gitignore mantém os vídeos fora do
                    # histórico por padrão; com --push o usuário pediu para versionar.
                    git("add", "-f", "--", str(videos_dir / item["file"]), cwd=repo_root)
                git("add", "-f", "--", str(project_dir / "manifest.json"), cwd=repo_root)
                message = (
                    f"chore({project_dir.name}): importa {len(committable)} vídeo(s) de "
                    f"{owner}/{repo}#{number}"
                )
                git("commit", "-m", message, cwd=repo_root)
                git("push", "origin", f"HEAD:{branch}", cwd=repo_root)
                push_result = f"enviado para '{branch}'"
                log(f"push feito em '{branch}'.")
        except RuntimeError as exc:
            push_result = f"falhou: {exc}"
            log(f"aviso: commit/push falhou ({exc}). Os arquivos continuam em {videos_dir}")

    if args.json_out:
        write_summary(args.json_out, {
            "issue": f"{owner}/{repo}#{number}",
            "issue_url": f"https://github.com/{owner}/{repo}/issues/{number}",
            "project": str(project_dir.relative_to(repo_root)),
            "assets_found": len(assets),
            "saved": saved,
            "skipped": skipped,
            "oversize": oversize,
            "push": push_result,
            "finished_at": _now(),
        })


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:  # pragma: no cover
        die("interrompido pelo usuário.", 130)
