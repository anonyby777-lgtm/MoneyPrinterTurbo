#!/usr/bin/env python3
"""Movie recap short-video generation for the MoneyPrinterTurbo Movies Skill.

A specialized, self-contained helper that installs MoneyPrinterTurbo (or reuses
an existing installation) and generates a finished, Teusflix-style movie recap
short: Brazilian Portuguese narration, 9:16 portrait, subtitles, and a
hook-first script written by the LLM. It mirrors the contract of the generic
``moneyprinterturbo-video`` skill so agents can reuse the same credential and
result-manifest conventions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ARCHIVE_URL = (
    "https://github.com/harry0703/MoneyPrinterTurbo/archive/refs/heads/main.zip"
)
DEFAULT_ROOT = Path.home() / "MoneyPrinterTurbo"

# Teusflix-style defaults: Brazilian Portuguese narration on a 9:16 short.
DEFAULT_VOICE_NAME = "pt-BR-ThalitaNeural-Female"
DEFAULT_ASPECT = "9:16"
DEFAULT_LANGUAGE = "pt-BR"
DEFAULT_PARAGRAPHS = 1

NEEDS_INPUT_EXIT_CODE = 10
SUPPORTED_SOURCES = {"pexels", "pixabay", "coverr", "local"}
PEXELS_API_KEY_URL = "https://www.pexels.com/api/"
PEXELS_VALIDATION_URL = "https://api.pexels.com/v1/collections?per_page=1"
PEXELS_API_KEY_HELP_URL = (
    "https://help.pexels.com/hc/en-us/articles/"
    "900004904026-How-do-I-get-an-API-key"
)

# Log and manifest namespace, kept separate from the generic video skill.
SKILL_NAMESPACE = "teusflix-movies"

# Recommended providers shared with the generic skill so a user configuring
# MoneyPrinterTurbo once can drive either skill. When an LLM key is missing,
# the helper emits all choices at once to avoid extra turns.
RECOMMENDED_LLM_PROVIDERS = {
    "moonshot": (
        "Kimi / Moonshot AI",
        "https://platform.kimi.com?track_id=track-2f5441d6ffd84c509dd079d78e9db5dc&aff=moneyprinterturbo",
    ),
    "openai": ("OpenAI", "https://platform.openai.com/api-keys"),
    "gemini": ("Google Gemini", "https://aistudio.google.com/app/apikey"),
    "deepseek": ("DeepSeek", "https://platform.deepseek.com/api_keys"),
    "volcengine": (
        "ByteDance VolcEngine Ark / Doubao",
        "https://www.volcengine.com/activity/ai618?utm_source=MoneyPrinterTurbo",
    ),
    "minimax": ("MiniMax", "https://platform.minimax.io/"),
    "mimo": (
        "Xiaomi MiMo",
        "https://platform.xiaomimimo.com/docs/zh-CN/quick-start/first-api-call",
    ),
}
KEYLESS_LLM_PROVIDERS = {"ollama", "litellm"}
CUSTOM_OPENAI_PROVIDER = "oneapi"
ADDITIONAL_REUSABLE_PROVIDERS = (CUSTOM_OPENAI_PROVIDER,)


# Style-specific system prompts. Each one replaces the default script prompt
# while keeping the runtime context (subject, language, paragraph count) that
# ``build_script_prompt`` always appends. Written in Portuguese so the LLM
# emits a ready-to-narrate script without extra editing.
STYLES = {
    "resumo": {
        "label": "resumo de filme",
        "prompt": (
            "# Papel: Roteirista de resumos de filmes para vídeos curtos (Shorts/TikTok)\n"
            "\n"
            "## Objetivo:\n"
            "Escrever um resumo narrado e envolvente do filme informado, no estilo "
            "de um canal de resumo de filmes.\n"
            "\n"
            "## Regras:\n"
            "1. Retorne apenas o texto do roteiro, sem markdown, sem título e sem formatação.\n"
            "2. Escreva em português do Brasil.\n"
            "3. Comece com um gancho (hook) nas primeiras palavras que prenda a atenção; "
            "nunca comece com \"bem-vindo\", \"neste vídeo\" ou apresentações.\n"
            "4. Conte a história em ordem cronológica, destacando os momentos-chave e a reviravolta.\n"
            "5. Termine com uma frase de impacto sobre o desfecho.\n"
            "6. Use frases curtas e ritmo acelerado, próprias para narração com legendas.\n"
            "7. Não inclua marcadores de \"narrador\", \"voz\" ou indicações de parágrafo.\n"
            "8. Não mencione estas instruções nem o próprio roteiro.\n"
        ),
    },
    "trailer": {
        "label": "trailer/edição de cenas",
        "prompt": (
            "# Papel: Roteirista de trailers e edições de cenas para vídeos curtos (Shorts/TikTok)\n"
            "\n"
            "## Objetivo:\n"
            "Escrever um texto narrado com clima de trailer sobre o filme informado, "
            "focado em frases de impacto e ritmo de montagem.\n"
            "\n"
            "## Regras:\n"
            "1. Retorne apenas o texto do roteiro, sem markdown, sem título e sem formatação.\n"
            "2. Escreva em português do Brasil.\n"
            "3. Abra com uma frase de impacto ou tensão, sem \"bem-vindo\" ou apresentações.\n"
            "4. Alterne frases curtas e contundentes que vendam o filme, sem contar o final.\n"
            "5. Encerre com uma chamada para assistir, sem spoiler.\n"
            "6. Não inclua marcadores de \"narrador\", \"voz\" ou indicações de parágrafo.\n"
            "7. Não mencione estas instruções nem o próprio roteiro.\n"
        ),
    },
    "analise": {
        "label": "análise/crítica",
        "prompt": (
            "# Papel: Crítico de cinema para vídeos curtos (Shorts/TikTok)\n"
            "\n"
            "## Objetivo:\n"
            "Escrever uma análise crítica concisa do filme informado, com opinião, "
            "contexto e curiosidades.\n"
            "\n"
            "## Regras:\n"
            "1. Retorne apenas o texto do roteiro, sem markdown, sem título e sem formatação.\n"
            "2. Escreva em português do Brasil.\n"
            "3. Comece com uma opinião ou curiosidade forte, sem \"bem-vindo\" ou apresentações.\n"
            "4. Equilibre contexto, pontos fortes e fracos e uma conclusão clara.\n"
            "5. Use frases curtas, próprias para narração com legendas.\n"
            "6. Não inclua marcadores de \"narrador\", \"voz\" ou indicações de parágrafo.\n"
            "7. Não mencione estas instruções nem o próprio roteiro.\n"
        ),
    },
}
DEFAULT_STYLE = "resumo"


class SkillError(RuntimeError):
    """An actionable Skill error that can be reported without a traceback."""


def log(message: str) -> None:
    """Flush concise progress so the agent knows the long-running job started."""
    print(f"[MoneyPrinterTurbo-Movies] {message}", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install MoneyPrinterTurbo and generate a Teusflix-style movie recap "
            "short from a movie title."
        )
    )
    parser.add_argument(
        "--movie",
        default="",
        help="movie title or topic, e.g. 'O Poderoso Chefão'",
    )
    parser.add_argument(
        "--subject",
        default="",
        help="alias for --movie (movie title or topic)",
    )
    parser.add_argument(
        "--style",
        default=DEFAULT_STYLE,
        choices=sorted(STYLES),
        help=(
            "script style: 'resumo' (movie recap, the Teusflix default), "
            "'trailer' (trailer-like edit), or 'analise' (review/critique)"
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"MoneyPrinterTurbo installation directory (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "cli_args",
        nargs=argparse.REMAINDER,
        help="additional MoneyPrinterTurbo CLI arguments placed after --",
    )
    args = parser.parse_args(argv)
    args.movie = (args.movie or args.subject or "").strip()
    if not args.movie:
        parser.error("--movie (or --subject) cannot be empty")
    if args.cli_args and args.cli_args[0] == "--":
        args.cli_args = args.cli_args[1:]
    return args


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    """Reject ZIP entries that would escape the temporary extraction directory."""
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != destination and destination not in target.parents:
            raise SkillError(f"project archive contains an unsafe path: {member.filename}")
    archive.extractall(destination)


def ensure_project(root: Path) -> None:
    """Reuse an existing project or install it from the official GitHub archive."""
    root = root.expanduser().resolve()
    if (root / "cli.py").is_file() and (root / "config.example.toml").is_file():
        log(f"using existing project: {root}")
        return
    if root.exists() and any(root.iterdir()):
        raise SkillError(f"installation directory exists but is not a valid project: {root}")

    root.parent.mkdir(parents=True, exist_ok=True)
    log(f"first-time installation: downloading the official project to {root}")
    with tempfile.TemporaryDirectory(prefix="mpt-install-") as temp_dir_value:
        temp_dir = Path(temp_dir_value)
        archive_path = temp_dir / "MoneyPrinterTurbo.zip"
        request = urllib.request.Request(
            PROJECT_ARCHIVE_URL,
            headers={"User-Agent": "MoneyPrinterTurbo-Agent-Skill"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            with archive_path.open("wb") as archive_file:
                shutil.copyfileobj(response, archive_file)
        with zipfile.ZipFile(archive_path) as archive:
            _safe_extract(archive, temp_dir)

        candidates = [
            path
            for path in temp_dir.iterdir()
            if path.is_dir() and (path / "cli.py").is_file()
        ]
        if len(candidates) != 1:
            raise SkillError("download completed but no valid MoneyPrinterTurbo project was found")
        if root.exists():
            root.rmdir()
        shutil.move(str(candidates[0]), str(root))
    log("project download completed")


def ensure_config(root: Path) -> Path:
    """Create the initial configuration without overwriting an existing file."""
    config_path = root / "config.toml"
    if not config_path.exists():
        shutil.copy2(root / "config.example.toml", config_path)
        log(f"created configuration file: {config_path}")
    return config_path


def _plain_config_value(text: str, key: str) -> str:
    """Read a simple top-level TOML value without printing its contents."""
    match = re.search(rf"(?m)^{re.escape(key)}\s*=\s*(.*)$", text)
    if not match:
        return ""
    value = match.group(1).split("#", 1)[0].strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def _replace_config_value(text: str, key: str, value: object) -> str:
    """Replace one active field while preserving the configuration layout."""
    pattern = re.compile(rf"(?m)^({re.escape(key)}\s*=\s*).*$")
    if not pattern.search(text):
        raise SkillError(f"configuration field not found in config.toml: {key}")
    encoded = json.dumps(value, ensure_ascii=False)
    return pattern.sub(lambda match: f"{match.group(1)}{encoded}", text, count=1)


def _has_configured_value(value: str) -> bool:
    """Treat empty strings and whitespace-only key arrays as unconfigured."""
    if not value:
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return bool(value.strip())
    if isinstance(parsed, list):
        return any(str(item).strip() for item in parsed)
    return bool(str(parsed).strip())


def _parse_string_list(value: str) -> list[str]:
    """Parse a configured string list while removing blanks and duplicates."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in parsed if str(item).strip()))


def apply_environment_config(config_path: Path) -> None:
    """Write supplied credentials while logging field names only."""
    provider = os.environ.get("MPT_LLM_PROVIDER", "").strip().lower()
    if provider == "openai_compatible":
        provider = CUSTOM_OPENAI_PROVIDER
    llm_key = os.environ.get("MPT_LLM_API_KEY", "").strip()
    base_url = os.environ.get("MPT_LLM_BASE_URL", "").strip()
    model_name = os.environ.get("MPT_LLM_MODEL_NAME", "").strip()
    pexels_key = os.environ.get("MPT_PEXELS_API_KEY", "").strip()
    if not any((provider, llm_key, base_url, model_name, pexels_key)):
        return

    text = config_path.read_text(encoding="utf-8")
    current_provider = _plain_config_value(text, "llm_provider") or "moonshot"
    provider = provider or current_provider
    changes: list[str] = []
    if os.environ.get("MPT_LLM_PROVIDER", "").strip():
        text = _replace_config_value(text, "llm_provider", provider)
        changes.append("llm_provider")
    if llm_key:
        text = _replace_config_value(text, f"{provider}_api_key", llm_key)
        changes.append(f"{provider}_api_key")
    if base_url:
        text = _replace_config_value(text, f"{provider}_base_url", base_url)
        changes.append(f"{provider}_base_url")
    if model_name:
        text = _replace_config_value(text, f"{provider}_model_name", model_name)
        changes.append(f"{provider}_model_name")
    if pexels_key:
        text = _replace_config_value(text, "pexels_api_keys", [pexels_key])
        changes.append("pexels_api_keys")
    config_path.write_text(text, encoding="utf-8")
    log("updated configuration fields: " + ", ".join(changes))


def _provider_is_ready(text: str, provider: str) -> bool:
    """Return whether a provider has enough configuration to generate."""
    if provider in KEYLESS_LLM_PROVIDERS:
        return True
    if not _has_configured_value(
        _plain_config_value(text, f"{provider}_api_key")
    ):
        return False
    if provider == CUSTOM_OPENAI_PROVIDER:
        return all(
            _has_configured_value(_plain_config_value(text, f"{provider}_{suffix}"))
            for suffix in ("base_url", "model_name")
        )
    return True


def reuse_existing_llm_provider(config_path: Path) -> str:
    """Reuse existing LLM credentials before asking the user for another key."""
    text = config_path.read_text(encoding="utf-8")
    current_provider = _plain_config_value(text, "llm_provider") or "moonshot"
    if _provider_is_ready(text, current_provider):
        return current_provider

    reusable_providers = (
        *RECOMMENDED_LLM_PROVIDERS,
        *ADDITIONAL_REUSABLE_PROVIDERS,
    )
    for provider in reusable_providers:
        if _provider_is_ready(text, provider):
            text = _replace_config_value(text, "llm_provider", provider)
            config_path.write_text(text, encoding="utf-8")
            log(f"reusing configured LLM provider: {provider}")
            return provider
    return current_provider


def selected_video_source(cli_args: list[str]) -> str:
    """Read the effective material source from forwarded CLI arguments."""
    for index, item in enumerate(cli_args):
        if item == "--video-source" and index + 1 < len(cli_args):
            return cli_args[index + 1].strip().lower()
        if item.startswith("--video-source="):
            return item.split("=", 1)[1].strip().lower()
    return "pexels"


def has_cli_option(cli_args: list[str], option: str) -> bool:
    """Return whether forwarded arguments explicitly set a CLI option."""
    return any(item == option or item.startswith(f"{option}=") for item in cli_args)


def missing_config(config_path: Path, cli_args: list[str]) -> tuple[str, list[str]]:
    """Return the active provider and only the fields required by this run."""
    text = config_path.read_text(encoding="utf-8")
    provider = _plain_config_value(text, "llm_provider") or "moonshot"
    missing: list[str] = []
    if provider not in KEYLESS_LLM_PROVIDERS and not _has_configured_value(
        _plain_config_value(text, f"{provider}_api_key")
    ):
        missing.append(f"{provider}_api_key")
    if provider == CUSTOM_OPENAI_PROVIDER:
        for suffix in ("base_url", "model_name"):
            field = f"{provider}_{suffix}"
            if not _has_configured_value(_plain_config_value(text, field)):
                missing.append(field)

    source = selected_video_source(cli_args)
    if source not in SUPPORTED_SOURCES:
        raise SkillError(f"unsupported video source: {source}")
    if source != "local":
        value = _plain_config_value(text, f"{source}_api_keys")
        if not _has_configured_value(value):
            missing.append(f"{source}_api_keys")
    return provider, missing


def report_missing_config(provider: str, missing: list[str]) -> int:
    """Tell the agent exactly which credentials must be requested."""
    print("MPT_NEEDS_INPUT")
    print(f"LLM_PROVIDER={provider}")
    for field in missing:
        print(f"MISSING={field}")
    if any(field.endswith("_api_key") for field in missing):
        print("LLM_PROVIDER_OPTIONS_BEGIN")
        for provider_id, (label, url) in RECOMMENDED_LLM_PROVIDERS.items():
            print(f"LLM_PROVIDER_OPTION={provider_id}|{label}|{url}")
        print(
            "LLM_PROVIDER_OPTION=oneapi|Other OpenAI-compatible provider|"
            "requires an API key, API base URL, and model name"
        )
        print("LLM_PROVIDER_OPTIONS_END")
    if any(field.startswith(f"{CUSTOM_OPENAI_PROVIDER}_") for field in missing):
        print(
            "OPENAI_COMPATIBLE_REQUIRED="
            "API key, API base URL, model name"
        )
    if "pexels_api_keys" in missing:
        print(f"PEXELS_API_KEY_URL={PEXELS_API_KEY_URL}")
        print(f"PEXELS_API_KEY_HELP_URL={PEXELS_API_KEY_HELP_URL}")
    print("Request only the listed values, set the environment variables, and rerun the same command.")
    return NEEDS_INPUT_EXIT_CODE


def report_invalid_pexels_config() -> int:
    """Request only a new Pexels key when every configured key is rejected."""
    print("MPT_NEEDS_INPUT")
    print("INVALID=pexels_api_keys")
    print(f"PEXELS_API_KEY_URL={PEXELS_API_KEY_URL}")
    print(f"PEXELS_API_KEY_HELP_URL={PEXELS_API_KEY_HELP_URL}")
    print("All configured Pexels API keys were rejected or are unavailable. Provide a new key.")
    return NEEDS_INPUT_EXIT_CODE


def _validate_pexels_key(api_key: str) -> str:
    """Return ``valid``, ``rejected``, or ``unknown`` for a Pexels key."""
    request = urllib.request.Request(
        PEXELS_VALIDATION_URL,
        headers={
            "Authorization": api_key,
            "User-Agent": "MoneyPrinterTurbo-Agent-Skill",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return "valid" if 200 <= response.status < 300 else "unknown"
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 429}:
            return "rejected"
        return "unknown"
    except (TimeoutError, urllib.error.URLError):
        return "unknown"


def validate_pexels_config(config_path: Path, cli_args: list[str]) -> bool:
    """Validate all Pexels keys used by the default material source."""
    if selected_video_source(cli_args) != "pexels":
        return True

    text = config_path.read_text(encoding="utf-8")
    keys = _parse_string_list(_plain_config_value(text, "pexels_api_keys"))
    if not keys:
        return False

    valid_keys: list[str] = []
    rejected_count = 0
    unknown_count = 0
    for api_key in keys:
        status = _validate_pexels_key(api_key)
        if status == "valid":
            valid_keys.append(api_key)
        elif status == "rejected":
            rejected_count += 1
        else:
            unknown_count += 1

    if valid_keys:
        if valid_keys != keys:
            text = _replace_config_value(text, "pexels_api_keys", valid_keys)
            config_path.write_text(text, encoding="utf-8")
        log(
            "Pexels key validation completed: "
            f"valid={len(valid_keys)}, rejected={rejected_count}, "
            f"unknown={unknown_count}"
        )
        return True
    if unknown_count:
        log("Pexels keys could not be verified due to a network or service error; keeping the existing configuration")
        return True

    log(f"Pexels key validation failed: all {rejected_count} configured keys are unusable")
    return False


def result_manifest_path(root: Path) -> Path:
    return root / ".agent-logs" / SKILL_NAMESPACE / "latest-result.json"


def write_result_manifest(root: Path, payload: dict[str, object]) -> Path:
    """Atomically write the stable result file for agents that cannot wait."""
    result_path = result_manifest_path(root)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    unique_suffix = str(uuid.uuid4()).replace("-", "")
    temp_path = result_path.with_name(
        f".{result_path.name}.{os.getpid()}.{unique_suffix}.tmp"
    )
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp_path.replace(result_path)
    return result_path.resolve()


def run_checked(command: list[str], *, cwd: Path) -> None:
    """Run dependency sync quietly and show only the last 30 lines on failure."""
    log("installing or verifying project dependencies with uv")
    result = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        output_tail = (result.stdout or "").splitlines()[-30:]
        if output_tail:
            print("\n".join(output_tail), file=sys.stderr)
        raise SkillError(f"dependency installation failed with exit code {result.returncode}")


def build_cli_defaults(cli_args: list[str], style: str) -> list[str]:
    """Return Teusflix-style CLI defaults that the user has not overridden."""
    if style not in STYLES:
        raise SkillError(f"unknown style: {style}")
    defaults: list[str] = []
    if not has_cli_option(cli_args, "--video-aspect"):
        defaults += ["--video-aspect", DEFAULT_ASPECT]
    if not has_cli_option(cli_args, "--video-language"):
        defaults += ["--video-language", DEFAULT_LANGUAGE]
    if not has_cli_option(cli_args, "--paragraph-number"):
        defaults += ["--paragraph-number", str(DEFAULT_PARAGRAPHS)]
    if not has_cli_option(cli_args, "--custom-system-prompt"):
        defaults += ["--custom-system-prompt", STYLES[style]["prompt"]]
    if not has_cli_option(cli_args, "--voice-name"):
        defaults += ["--voice-name", DEFAULT_VOICE_NAME]
    return defaults


def generate_video(
    root: Path,
    movie: str,
    style: str,
    cli_args: list[str],
) -> tuple[list[Path], Path, Path, Path]:
    """Run one traceable CLI task and return only its final video files."""
    uv = shutil.which("uv")
    if not uv:
        raise SkillError("uv was not found; reopen the terminal or add uv to PATH")
    run_checked([uv, "sync", "--frozen"], cwd=root)

    task_id = str(uuid.uuid4())
    task_dir = root / "storage" / "tasks" / task_id
    log_dir = root / ".agent-logs" / SKILL_NAMESPACE
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run-{task_id}.log"
    write_result_manifest(
        root,
        {
            "status": "running",
            "subject": movie,
            "style": style,
            "task_id": task_id,
            "task_dir": str(task_dir.resolve()),
            "log_file": str(log_path.resolve()),
            "video_files": [],
        },
    )
    defaults = build_cli_defaults(cli_args, style)
    command = [
        uv,
        "run",
        "python",
        "cli.py",
        *defaults,
        *cli_args,
        "--video-subject",
        movie,
        "--task-id",
        task_id,
        # A Skill request must produce a finished video. Force the final stage
        # so forwarded options cannot stop at script, audio, or materials.
        "--stop-at",
        "video",
    ]
    log(f"starting movie short generation, style={style}, task ID: {task_id}")
    log(f"full generation log: {log_path}")
    with log_path.open("w", encoding="utf-8") as log_file:
        result = subprocess.run(
            command,
            cwd=root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        if tail:
            print("\n".join(tail), file=sys.stderr)
        error = (
            f"movie short generation failed with exit code {result.returncode}; "
            f"log: {log_path}"
        )
        write_result_manifest(
            root,
            {
                "status": "failed",
                "subject": movie,
                "style": style,
                "task_id": task_id,
                "task_dir": str(task_dir.resolve()),
                "log_file": str(log_path.resolve()),
                "video_files": [],
                "error": error,
            },
        )
        raise SkillError(error)

    videos = sorted(
        path.resolve()
        for path in task_dir.glob("final-*.mp4")
        if path.is_file() and path.stat().st_size > 0
    )
    if not videos:
        error = f"generation completed without a valid final MP4; log: {log_path}"
        write_result_manifest(
            root,
            {
                "status": "failed",
                "subject": movie,
                "style": style,
                "task_id": task_id,
                "task_dir": str(task_dir.resolve()),
                "log_file": str(log_path.resolve()),
                "video_files": [],
                "error": error,
            },
        )
        raise SkillError(error)
    result_path = write_result_manifest(
        root,
        {
            "status": "completed",
            "subject": movie,
            "style": style,
            "task_id": task_id,
            "task_dir": str(task_dir.resolve()),
            "log_file": str(log_path.resolve()),
            "video_files": [str(video) for video in videos],
        },
    )
    return videos, task_dir.resolve(), log_path.resolve(), result_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        ensure_project(root)
        config_path = ensure_config(root)
        apply_environment_config(config_path)
        reuse_existing_llm_provider(config_path)
        provider, missing = missing_config(config_path, args.cli_args)
        if missing:
            write_result_manifest(
                root,
                {
                    "status": "needs_input",
                    "subject": args.movie,
                    "style": args.style,
                    "missing": missing,
                },
            )
            return report_missing_config(provider, missing)
        if not validate_pexels_config(config_path, args.cli_args):
            write_result_manifest(
                root,
                {
                    "status": "needs_input",
                    "subject": args.movie,
                    "style": args.style,
                    "invalid": ["pexels_api_keys"],
                },
            )
            return report_invalid_pexels_config()
        videos, task_dir, log_path, result_path = generate_video(
            root, args.movie, args.style, args.cli_args
        )
    except (OSError, SkillError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        print(f"MPT_ERROR={exc}", file=sys.stderr)
        return 1

    print("MPT_RESULT")
    for video in videos:
        print(f"VIDEO_FILE={video}")
    print(f"TASK_DIR={task_dir}")
    print(f"LOG_FILE={log_path}")
    print(f"RESULT_FILE={result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
