import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SKILL_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "docs"
    / "skill"
    / "teusflix-movies"
    / "movies_agent.py"
)
SKILL_DOCUMENT = SKILL_SCRIPT.with_name("SKILL.md")
SPEC = importlib.util.spec_from_file_location("movies_agent_skill", SKILL_SCRIPT)
movies_agent = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(movies_agent)


MINIMAL_CONFIG = """\
llm_provider = "moonshot"
moonshot_api_key = ""
deepseek_api_key = ""
pexels_api_keys = []
pixabay_api_keys = []
coverr_api_keys = []
oneapi_api_key = ""
oneapi_base_url = ""
oneapi_model_name = ""
"""


class TestMoviesAgentSkill(unittest.TestCase):
    def create_project(self, root: Path) -> None:
        """创建足够完成安装和配置检查的最小项目结构。"""
        root.mkdir()
        (root / "cli.py").write_text("", encoding="utf-8")
        (root / "config.example.toml").write_text(
            MINIMAL_CONFIG, encoding="utf-8"
        )

    class FakeHttpResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    def test_skill_runs_helper_from_its_working_directory(self):
        text = SKILL_DOCUMENT.read_text(encoding="utf-8")
        self.assertIn(
            "uv run --no-project --python 3.11 python movies_agent.py --movie",
            text,
        )
        self.assertIn("pt-BR-ThalitaNeural-Female", text)
        self.assertIn("9:16", text)

    def test_movie_and_subject_are_interchangeable_aliases(self):
        args = movies_agent.parse_args(["--movie", "O Poderoso Chefão"])
        self.assertEqual(args.movie, "O Poderoso Chefão")
        args = movies_agent.parse_args(["--subject", "Matrix"])
        self.assertEqual(args.movie, "Matrix")

    def test_movie_is_required(self):
        with self.assertRaises(SystemExit):
            movies_agent.parse_args([])

    def test_defaults_are_teusflix_style(self):
        defaults = movies_agent.build_cli_defaults([], "resumo")
        self.assertIn("--video-aspect", defaults)
        self.assertIn("9:16", defaults)
        self.assertIn("--video-language", defaults)
        self.assertIn("pt-BR", defaults)
        self.assertIn("--voice-name", defaults)
        self.assertIn("pt-BR-ThalitaNeural-Female", defaults)
        self.assertIn("--paragraph-number", defaults)
        self.assertIn("1", defaults)
        self.assertIn("--custom-system-prompt", defaults)
        prompt = defaults[defaults.index("--custom-system-prompt") + 1]
        self.assertIn("resumo", prompt)
        self.assertIn("português do Brasil", prompt)

    def test_user_overrides_are_not_clobbered(self):
        cli_args = [
            "--video-aspect",
            "16:9",
            "--video-language",
            "pt-PT",
            "--voice-name",
            "pt-PT-FernandaNeural-Female",
            "--paragraph-number",
            "2",
            "--custom-system-prompt",
            "custom prompt",
        ]
        defaults = movies_agent.build_cli_defaults(cli_args, "resumo")
        self.assertNotIn("--video-aspect", defaults)
        self.assertNotIn("--video-language", defaults)
        self.assertNotIn("--voice-name", defaults)
        self.assertNotIn("--paragraph-number", defaults)
        self.assertNotIn("--custom-system-prompt", defaults)

    def test_each_style_has_a_distinct_prompt(self):
        prompts = {
            style: movies_agent.STYLES[style]["prompt"]
            for style in movies_agent.STYLES
        }
        self.assertIn("resumo", prompts)
        self.assertIn("trailer", prompts)
        self.assertIn("analise", prompts)
        self.assertEqual(len(prompts), 3)
        self.assertEqual(len(set(prompts.values())), 3)
        for style, prompt in prompts.items():
            self.assertIn("português do Brasil", prompt)

    def test_unknown_style_is_rejected(self):
        with self.assertRaises(movies_agent.SkillError):
            movies_agent.build_cli_defaults([], "nao-existe")

    def test_manifest_uses_dedicated_namespace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            movies_agent.write_result_manifest(
                root, {"status": "completed"}
            )
            path = root / ".agent-logs" / "teusflix-movies" / "latest-result.json"
            self.assertTrue(path.is_file())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "completed")
            self.assertIn("updated_at", data)

    def test_generation_injects_style_and_pt_br_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_id = "12345678-1234-1234-1234-123456789abc"

            def finish_cli(command, **kwargs):
                task_dir = root / "storage" / "tasks" / task_id
                task_dir.mkdir(parents=True)
                (task_dir / "final-1.mp4").write_bytes(b"video")
                return SimpleNamespace(returncode=0)

            with (
                patch.object(movies_agent.shutil, "which", return_value="uv"),
                patch.object(movies_agent, "run_checked"),
                patch.object(movies_agent.uuid, "uuid4", return_value=task_id),
                patch.object(
                    movies_agent.subprocess, "run", side_effect=finish_cli
                ) as run_mock,
            ):
                videos, task_dir, log_path, result_path = movies_agent.generate_video(
                    root, "O Poderoso Chefão", "resumo", []
                )

            self.assertEqual(videos, [(task_dir / "final-1.mp4").resolve()])
            command = run_mock.call_args.args[0]
            self.assertIn("--video-aspect", command)
            self.assertIn("9:16", command)
            self.assertIn("pt-BR", command)
            self.assertIn("pt-BR-ThalitaNeural-Female", command)
            self.assertIn("--stop-at", command)
            self.assertEqual(command[-2:], ["--stop-at", "video"])
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["subject"], "O Poderoso Chefão")
            self.assertEqual(result["style"], "resumo")

    def test_generation_failure_prints_original_error_and_writes_failed_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_id = "12345678-1234-1234-1234-123456789abc"
            model_error = "provider error: model is unavailable for this account"
            stderr = io.StringIO()

            def reject_model(command, **kwargs):
                kwargs["stdout"].write(model_error + "\n")
                return SimpleNamespace(returncode=1)

            with (
                patch.object(movies_agent.shutil, "which", return_value="uv"),
                patch.object(movies_agent, "run_checked"),
                patch.object(movies_agent.uuid, "uuid4", return_value=task_id),
                patch.object(movies_agent.subprocess, "run", side_effect=reject_model),
                redirect_stderr(stderr),
                self.assertRaises(movies_agent.SkillError),
            ):
                movies_agent.generate_video(root, "Matrix", "resumo", [])

            self.assertIn(model_error, stderr.getvalue())
            result = json.loads(
                movies_agent.result_manifest_path(root).read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "failed")

    def test_missing_llm_key_reports_needs_input_without_pexels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                MINIMAL_CONFIG.replace(
                    "pexels_api_keys = []", 'pexels_api_keys = ["key"]'
                ),
                encoding="utf-8",
            )
            provider, missing = movies_agent.missing_config(config_path, [])
            self.assertEqual(provider, "moonshot")
            self.assertEqual(missing, ["moonshot_api_key"])

            output = io.StringIO()
            with redirect_stdout(output):
                code = movies_agent.report_missing_config(provider, missing)
            self.assertEqual(code, movies_agent.NEEDS_INPUT_EXIT_CODE)
            self.assertIn("LLM_PROVIDER_OPTIONS_BEGIN", output.getvalue())
            self.assertNotIn("PEXELS_API_KEY_URL", output.getvalue())

    def test_only_missing_pexels_key_does_not_ask_for_llm_again(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = movies_agent.report_missing_config(
                "moonshot", ["pexels_api_keys"]
            )
        text = output.getvalue()
        self.assertEqual(code, movies_agent.NEEDS_INPUT_EXIT_CODE)
        self.assertIn(f"PEXELS_API_KEY_URL={movies_agent.PEXELS_API_KEY_URL}", text)
        self.assertNotIn("LLM_PROVIDER_OPTIONS_BEGIN", text)

    def test_provided_script_skips_llm_only_defaults(self):
        defaults = movies_agent.build_cli_defaults(
            [], "resumo", provided_script="Roteiro pronto em pt-BR."
        )
        self.assertIn("--video-aspect", defaults)
        self.assertIn("9:16", defaults)
        self.assertIn("--voice-name", defaults)
        self.assertNotIn("--video-language", defaults)
        self.assertNotIn("--paragraph-number", defaults)
        self.assertNotIn("--custom-system-prompt", defaults)

    def test_provided_script_and_local_source_require_no_api_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")
            provider, missing = movies_agent.missing_config(
                config_path,
                ["--video-source", "local", "--video-materials", "clip.mp4"],
                provided_script="Roteiro pronto em pt-BR.",
            )
            self.assertEqual(missing, [])
            self.assertEqual(provider, "moonshot")

    def test_provided_script_is_forwarded_and_style_prompt_is_not(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_id = "12345678-1234-1234-1234-123456789abc"
            script = "Gancho. A história de Vingadores: Ultimato."

            def finish_cli(command, **kwargs):
                task_dir = root / "storage" / "tasks" / task_id
                task_dir.mkdir(parents=True)
                (task_dir / "final-1.mp4").write_bytes(b"video")
                return SimpleNamespace(returncode=0)

            with (
                patch.object(movies_agent.shutil, "which", return_value="uv"),
                patch.object(movies_agent, "run_checked"),
                patch.object(movies_agent.uuid, "uuid4", return_value=task_id),
                patch.object(
                    movies_agent.subprocess, "run", side_effect=finish_cli
                ) as run_mock,
            ):
                videos, task_dir, log_path, result_path = movies_agent.generate_video(
                    root,
                    "Vingadores: Ultimato",
                    "resumo",
                    ["--video-source", "local", "--video-materials", "clip.mp4"],
                    script=script,
                )

            self.assertEqual(videos, [(task_dir / "final-1.mp4").resolve()])
            command = run_mock.call_args.args[0]
            self.assertIn("--video-script", command)
            self.assertIn(script, command)
            self.assertNotIn("--custom-system-prompt", command)
            self.assertNotIn("--video-language", command)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertTrue(result["script_provided"])

    def test_zip_extraction_rejects_parent_directory_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "unsafe.zip"
            destination = Path(temp_dir) / "extract"
            destination.mkdir()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "unsafe")

            with zipfile.ZipFile(archive_path) as archive, self.assertRaises(
                movies_agent.SkillError
            ):
                movies_agent._safe_extract(archive, destination)


if __name__ == "__main__":
    unittest.main()
