import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import localize_skill_cards as m


def write(root, rel, value):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        'interface:\n  display_name: "Demo"\n  short_description: "'
        + value
        + '"\npolicy:\n  allow_implicit_invocation: false\n'
    )
    return p


def make_record(root, changes):
    return m.write_record({"status": "completed", "changes": changes}, root)


class TestCards(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name).resolve()
        self.old = (m.CODEX_HOME, m.PERSONAL, m.SYSTEM, m.PLUGIN_CACHE, m.TMP_PLUGINS, m.RUN_ROOT)
        m.CODEX_HOME = self.root
        m.PERSONAL = self.root / "skills"
        m.SYSTEM = m.PERSONAL / ".system"
        m.PLUGIN_CACHE = self.root / "cache"
        m.TMP_PLUGINS = self.root / ".tmp/plugins"
        m.RUN_ROOT = self.root / "runs"
        self.p = write(m.PERSONAL, "demo/agents/openai.yaml", "English description here")
        write(m.SYSTEM, "sys/agents/openai.yaml", "系统技能简介已经是中文内容")
        self.system_p = write(m.SYSTEM, "sys2/agents/openai.yaml", "系统技能简介已经是中文内容")
        write(m.PLUGIN_CACHE, "pub/pkg/1.0.0/skills/plug/agents/openai.yaml", "插件技能简介已经是中文内容")
        write(m.PLUGIN_CACHE, "pub/pkg/2.0.0/skills/plug/agents/openai.yaml", "插件技能简介已经是中文内容")
        write(m.TMP_PLUGINS, "bad/skills/agents/openai.yaml", "临时插件简介已经是中文内容")

    def tearDown(self):
        m.CODEX_HOME, m.PERSONAL, m.SYSTEM, m.PLUGIN_CACHE, m.TMP_PLUGINS, m.RUN_ROOT = self.old
        self.t.cleanup()

    def test_default_scope_excludes_system_and_tmp(self):
        rows = m.discover(False)
        ids = {x["stable_id"] for x in rows}
        self.assertEqual(ids, {"personal/demo"})
        self.assertTrue(all("/.tmp/" not in x["path"] for x in rows))

    def test_managed_scope_includes_system_plugin_and_excludes_tmp(self):
        rows = m.discover(True)
        ids = {x["stable_id"] for x in rows}
        self.assertIn("system/sys", ids)
        self.assertIn("plugin/pub/pkg/plug", ids)
        self.assertNotIn("plugin/bad", ids)
        self.assertEqual(next(x for x in rows if x["stable_id"] == "system/sys")["source"], "system")
        self.assertEqual(next(x for x in rows if x["stable_id"] == "plugin/pub/pkg/plug")["source"], "plugin")

    def test_product_name_with_english_word_is_clear_chinese(self):
        self.assertTrue(m.clear_zh("使用 Business Review 模板创建演示文稿"))

    def test_public_catalog_is_empty_and_local_approvals_are_not_loaded(self):
        public = json.loads(m.catalog_path().read_text())
        self.assertEqual(public["translations"], {})
        self.assertEqual(m.translations(), {})

    def test_skill_metadata_contract(self):
        skill = Path(__file__).parents[1] / "SKILL.md"
        ui = Path(__file__).parents[1] / "agents/openai.yaml"
        frontmatter = skill.read_text().split("---", 2)[1]
        fields = dict(line.split(": ", 1) for line in frontmatter.strip().splitlines())
        self.assertEqual(fields["name"], "localize-skill-cards")
        self.assertEqual(fields["description"], "汉化个人或经确认的受管 Codex 技能卡片简介。使用时扫描、生成计划、预览或应用 agents/openai.yaml 中 interface.short_description 的简体中文译文；只在用户确认后写入。")
        self.assertEqual(set(fields), {"name", "description"})
        ui_text = ui.read_text()

        def quoted(name):
            match = re.search(rf"^  {re.escape(name)}:\s*(\".*\")$", ui_text, re.M)
            self.assertIsNotNone(match)
            return json.loads(match.group(1))

        expected = "安全汉化 Codex 技能卡片简介并保留原有语义和格式"
        self.assertEqual(quoted("display_name"), "汉化技能简介")
        self.assertEqual(quoted("short_description"), expected)
        self.assertEqual(quoted("default_prompt"), "使用 $localize-skill-cards 扫描并计划汉化技能卡片简介。")
        self.assertRegex(ui_text, r"(?m)^  allow_implicit_invocation: false$")
        self.assertTrue(25 <= len(expected) <= 64)

    def test_suite_runs_without_external_codex_home(self):
        repo = Path(__file__).parents[3]
        with tempfile.TemporaryDirectory() as isolated:
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "-q", "skills/localize-skill-cards/scripts/test_localize_skill_cards.py", "-k", "test_skill_metadata_contract"],
                cwd=repo,
                env={
                    **os.environ,
                    "HOME": isolated,
                    "PYTHONPATH": "skills/localize-skill-cards/scripts",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_catalog_has_no_environment_fingerprint(self):
        public = json.loads(Path(__file__).parents[1].joinpath("references/approved-translations.json").read_text())
        self.assertEqual(public["translations"], {})
        self.assertTrue(all(not Path(value).is_absolute() for value in public.values() if isinstance(value, str)))

    def test_cli_catalog_requires_strict_schema(self):
        script = Path(m.__file__)
        template = {
            "version": 1,
            "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
            "translations": {"personal/demo": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
        }
        invalid = (
            ("list", []),
            ("null", None),
            ("unsupported-version", {**template, "version": 2}),
            ("unknown-field", {**template, "extra": True}),
            ("non-string-value", {**template, "translations": {"personal/demo": 7}}),
            ("invalid-stable-id", {**template, "translations": {"../escape": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"}}),
            ("bare-map", {"personal/demo": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"}),
        )
        for name, payload in invalid:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as isolated:
                home = Path(isolated).resolve()
                target = write(home / "skills", "demo/agents/openai.yaml", "English description here")
                before = target.read_bytes()
                catalog = home / "catalog.json"
                catalog.write_text(json.dumps(payload, ensure_ascii=False))
                result = subprocess.run(
                    [sys.executable, str(script), "plan", "--codex-home", str(home), "--translations", str(catalog)],
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b"AttributeError", result.stderr)
                self.assertEqual(target.read_bytes(), before)

        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            write(home / "skills", "demo/agents/openai.yaml", "English description here")
            catalog = home / "catalog.json"
            catalog.write_text(json.dumps(template, ensure_ascii=False))
            result = subprocess.run(
                [sys.executable, str(script), "plan", "--codex-home", str(home), "--translations", str(catalog)],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)[0]["action"], "change")

    def test_cli_uses_symlinked_codex_home_consistently(self):
        script = Path(m.__file__)
        with tempfile.TemporaryDirectory() as isolated:
            parent = Path(isolated).resolve()
            actual = parent / "actual-home"
            alias = parent / "codex-home-alias"
            alias.symlink_to(actual, target_is_directory=True)
            target = write(actual / "skills", "demo/agents/openai.yaml", "English description here")
            catalog = actual / "localize-skill-cards/approved-translations.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {"personal/demo": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
            }, ensure_ascii=False))
            env = {**os.environ, "CODEX_HOME": str(alias), "PYTHONDONTWRITEBYTECODE": "1"}
            for command in (("scan",), ("plan",), ("validate",)):
                result = subprocess.run([sys.executable, str(script), *command], env=env, capture_output=True)
                self.assertEqual(result.returncode, 0, command)
            result = subprocess.run([sys.executable, str(script), "apply", "--confirm"], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            records = list((actual / "localize-skill-cards/runs").glob("*.json"))
            self.assertEqual(len(records), 1)
            self.assertIn("安全汉化 Codex 技能卡片简介并保留原有语义和格式".encode(), target.read_bytes())
            result = subprocess.run([sys.executable, str(script), "restore", str(records[0]), "--confirm"], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'"restore_status": "completed"', records[0].read_bytes())

        with tempfile.TemporaryDirectory(prefix="空格 中文 😊 ") as isolated:
            home = Path(isolated).resolve()
            result = subprocess.run(
                [sys.executable, str(script), "scan", "--codex-home", str(home)],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [])

    def test_cli_apply_confirm_prints_one_json_document(self):
        script = Path(m.__file__)
        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            write(home / "skills", "demo/agents/openai.yaml", "English description here")
            catalog = home / "localize-skill-cards/approved-translations.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {"personal/demo": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
            }, ensure_ascii=False))
            result = subprocess.run(
                [sys.executable, str(script), "apply", "--codex-home", str(home), "--confirm"],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(result.stdout)
            self.assertEqual(document["status"], "completed")
            self.assertIsInstance(document["plan"], list)
            self.assertTrue(Path(document["record"]).is_file())

    def test_cli_apply_rejects_mixed_error_and_change_plan(self):
        script = Path(m.__file__)
        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            valid = write(home / "skills", "valid/agents/openai.yaml", "English description here")
            malformed = home / "skills/malformed/agents/openai.yaml"
            malformed.parent.mkdir(parents=True)
            malformed.write_text(
                'interface:\n  display_name: "Malformed"\n'
                '  short_description: "English description here"\n'
                '  short_description: "Duplicate description here"\n'
            )
            catalog = home / "localize-skill-cards/approved-translations.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {"personal/valid": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
            }, ensure_ascii=False))
            before = valid.read_bytes()
            result = subprocess.run(
                [sys.executable, str(script), "apply", "--codex-home", str(home), "--confirm"],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertNotIn(b"Traceback", result.stderr)
            self.assertEqual(valid.read_bytes(), before)
            runs = home / "localize-skill-cards/runs"
            self.assertFalse(runs.exists() and any(json.loads(p.read_text()).get("status") == "completed" for p in runs.glob("*.json")))

    def test_discovery_skips_inner_symlink_components(self):
        script = Path(m.__file__)
        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            real = write(home / "skills", "real/agents/openai.yaml", "English description here")
            outside_root = home.parent / "outside-skill"
            outside = write(outside_root, "agents/openai.yaml", "OUTSIDE description must not be read")
            (home / "skills/inside-link").symlink_to(real.parent.parent, target_is_directory=True)
            (home / "skills/outside-link").symlink_to(outside_root, target_is_directory=True)
            env = {**os.environ, "CODEX_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run([sys.executable, str(script), "scan"], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = json.loads(result.stdout)
            self.assertEqual([row["stable_id"] for row in rows], ["personal/real"])
            self.assertTrue(all("outside-skill" not in row["path"] for row in rows))
            self.assertTrue(all("OUTSIDE" not in row.get("value", "") for row in rows))

    def test_catalog_rejects_unsafe_values_before_skip_branch(self):
        script = Path(m.__file__)
        unsafe_values = ("\u0085", "\u2028", "\u2029", "\x00")
        for control in unsafe_values:
            with self.subTest(codepoint=f"U+{ord(control):04X}"), tempfile.TemporaryDirectory() as isolated:
                home = Path(isolated).resolve()
                target = write(home / "skills", "demo/agents/openai.yaml", "使用 Business Review 模板创建演示文稿")
                catalog = home / "catalog.json"
                catalog.write_text(json.dumps({
                    "version": 1,
                    "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                    "translations": {"personal/demo": "安全汉化 Codex 技能卡片简介并保留原有语义和格式" + control},
                }, ensure_ascii=False))
                before = target.read_bytes()
                result = subprocess.run(
                    [sys.executable, str(script), "plan", "--codex-home", str(home), "--translations", str(catalog)],
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"Traceback", result.stderr)
                self.assertEqual(target.read_bytes(), before)

        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            target = write(home / "skills", "demo/agents/openai.yaml", "使用 Business Review 模板创建演示文稿")
            catalog = home / "localize-skill-cards/approved-translations.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {"personal/unused": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
            }, ensure_ascii=False))
            result = subprocess.run(
                [sys.executable, str(script), "validate", "--codex-home", str(home)],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)[0]["action"], "skip")

    def test_cli_diagnostics_escape_untrusted_fields(self):
        script = Path(m.__file__)
        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            write(home / "skills", "demo/agents/openai.yaml", "English description here")
            catalog = home / "catalog.json"
            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {},
                "\x1b[2J": "unexpected",
            }, ensure_ascii=False))
            result = subprocess.run(
                [sys.executable, str(script), "plan", "--codex-home", str(home), "--translations", str(catalog)],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertNotIn(b"\x1b", result.stderr)
            self.assertIn(b"\\u001b[2J", result.stderr)

            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {"bad\x1b[2Jid": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
            }, ensure_ascii=False))
            result = subprocess.run(
                [sys.executable, str(script), "plan", "--codex-home", str(home), "--translations", str(catalog)],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b"\x1b", result.stderr)

    def test_catalog_rejects_dot_path_components_in_stable_ids(self):
        script = Path(m.__file__)
        invalid_ids = (
            "personal/.",
            "personal/..",
            "system/.",
            "system/..",
            "plugin/./pkg/skill",
            "plugin/acme/../skill",
            "plugin/acme/pkg/./skill",
            "plugin/acme/pkg/../skill",
        )
        for stable_id_value in invalid_ids:
            with self.subTest(stable_id=stable_id_value), tempfile.TemporaryDirectory() as isolated:
                home = Path(isolated).resolve()
                write(home / "skills", "demo/agents/openai.yaml", "English description here")
                catalog = home / "catalog.json"
                catalog.write_text(json.dumps({
                    "version": 1,
                    "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                    "translations": {stable_id_value: "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
                }, ensure_ascii=False))
                result = subprocess.run(
                    [sys.executable, str(script), "plan", "--codex-home", str(home), "--translations", str(catalog)],
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"Traceback", result.stderr)

    def test_catalog_accepts_legal_stable_id_name_controls(self):
        script = Path(m.__file__)
        legal_ids = (
            "personal/.hidden",
            "personal/v1.2.3",
            "personal/foo_bar",
            "personal/foo-bar",
            "system/.hidden",
            "plugin/acme/pkg-1.2/skill_name",
        )
        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            write(home / "skills", "demo/agents/openai.yaml", "使用 Business Review 模板创建演示文稿")
            catalog = home / "localize-skill-cards/approved-translations.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {stable_id_value: "安全汉化 Codex 技能卡片简介并保留原有语义和格式" for stable_id_value in legal_ids},
            }, ensure_ascii=False))
            env = {**os.environ, "CODEX_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run([sys.executable, str(script), "plan"], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)[0]["action"], "skip")
            result = subprocess.run([sys.executable, str(script), "validate"], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_restore_accepts_trusted_codex_home_alias(self):
        script = Path(m.__file__)
        with tempfile.TemporaryDirectory() as isolated:
            parent = Path(isolated).resolve()
            actual = parent / "actual-home"
            alias = parent / "codex-home-alias"
            alias.symlink_to(actual, target_is_directory=True)
            target = write(actual / "skills", "demo/agents/openai.yaml", "English description here")
            before = target.read_bytes()
            catalog = actual / "localize-skill-cards/approved-translations.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {"personal/demo": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
            }, ensure_ascii=False))
            env = {**os.environ, "CODEX_HOME": str(alias), "PYTHONDONTWRITEBYTECODE": "1"}
            applied = subprocess.run([sys.executable, str(script), "apply", "--confirm"], env=env, capture_output=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            canonical_record = Path(json.loads(applied.stdout)["record"])
            alias_record = alias / "localize-skill-cards/runs" / canonical_record.name
            self.assertTrue(alias_record.is_file())
            preview = subprocess.run([sys.executable, str(script), "restore", str(alias_record)], env=env, capture_output=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            restored = subprocess.run([sys.executable, str(script), "restore", str(alias_record), "--confirm"], env=env, capture_output=True)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(target.read_bytes(), before)

            explicit_env = {**env, "CODEX_HOME": str(actual)}
            applied = subprocess.run([sys.executable, str(script), "apply", "--codex-home", str(alias), "--confirm"], env=explicit_env, capture_output=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            canonical_record = Path(json.loads(applied.stdout)["record"])
            canonical_preview = subprocess.run([sys.executable, str(script), "restore", str(canonical_record), "--codex-home", str(alias)], env=explicit_env, capture_output=True)
            self.assertEqual(canonical_preview.returncode, 0, canonical_preview.stderr)

            linked_runs = alias / "localize-skill-cards/linked-runs"
            linked_runs.symlink_to(actual / "localize-skill-cards/runs", target_is_directory=True)
            linked = subprocess.run([sys.executable, str(script), "restore", str(linked_runs / canonical_record.name)], env=env, capture_output=True)
            self.assertNotEqual(linked.returncode, 0)
            self.assertEqual(linked.stdout, b"")
            self.assertNotIn(b"Traceback", linked.stderr)

            external = parent / "external-record.json"
            external.write_bytes(canonical_record.read_bytes())
            external.chmod(0o600)
            outside = subprocess.run([sys.executable, str(script), "restore", str(external)], env=env, capture_output=True)
            self.assertNotEqual(outside.returncode, 0)
            self.assertEqual(outside.stdout, b"")
            self.assertNotIn(b"Traceback", outside.stderr)

    def test_cli_expected_errors_are_concise_and_write_nothing(self):
        script = Path(m.__file__)
        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            target = write(home / "skills", "demo/agents/openai.yaml", "English description here")
            catalog = home / "localize-skill-cards/approved-translations.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {"personal/demo": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
            }, ensure_ascii=False))
            env = {**os.environ, "CODEX_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}

            def run(*args):
                return subprocess.run([sys.executable, str(script), *args], env=env, capture_output=True)

            applied = run("apply", "--confirm")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            record = Path(json.loads(applied.stdout)["record"])

            first_restore = run("restore", str(record), "--confirm")
            self.assertEqual(first_restore.returncode, 0, first_restore.stderr)
            repeated = run("restore", str(record), "--confirm")
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(repeated.stdout, b"")
            self.assertNotIn(b"Traceback", repeated.stderr)

            applied = run("apply", "--confirm")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            record = Path(json.loads(applied.stdout)["record"])
            target.write_bytes(target.read_bytes().replace(
                "安全汉化 Codex 技能卡片简介并保留原有语义和格式".encode(), b"drifted description"
            ))
            drifted = run("restore", str(record), "--confirm")
            self.assertNotEqual(drifted.returncode, 0)
            self.assertEqual(drifted.stdout, b"")
            self.assertNotIn(b"Traceback", drifted.stderr)

            catalog.write_text("{}")
            malformed_catalog = run("plan", "--translations", str(catalog))
            self.assertNotEqual(malformed_catalog.returncode, 0)
            self.assertEqual(malformed_catalog.stdout, b"")
            self.assertNotIn(b"Traceback", malformed_catalog.stderr)

            data = json.loads(record.read_text())
            data["unexpected"] = True
            record.write_text(json.dumps(data))
            malformed_record = run("restore", str(record))
            self.assertNotEqual(malformed_record.returncode, 0)
            self.assertEqual(malformed_record.stdout, b"")
            self.assertNotIn(b"Traceback", malformed_record.stderr)

            record.write_text(json.dumps(data))
            record.chmod(0o644)
            permission = run("restore", str(record))
            self.assertNotEqual(permission.returncode, 0)
            self.assertEqual(permission.stdout, b"")
            self.assertNotIn(b"Traceback", permission.stderr)

            oversized = home / "localize-skill-cards/runs/20260101T000000000000Z-01234567.json"
            oversized.write_bytes(b"{" + b"x" * (m.MAX_RECORD_BYTES + 1) + b"}")
            oversized.chmod(0o600)
            too_large = run("restore", str(oversized))
            self.assertNotEqual(too_large.returncode, 0)
            self.assertEqual(too_large.stdout, b"")
            self.assertNotIn(b"Traceback", too_large.stderr)

    def test_restore_rejects_impossible_record_timestamp(self):
        script = Path(m.__file__)
        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            target = write(home / "skills", "demo/agents/openai.yaml", "安全汉化 Codex 技能卡片简介并保留原有语义和格式")
            runs = home / "localize-skill-cards/runs"
            record = make_record(runs, [{
                "path": str(target),
                "stable_id": "personal/demo",
                "old": "English description here",
                "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式",
            }])
            data = json.loads(record.read_text())
            impossible = runs / "20260230T000000000000Z-01234567.json"
            data["timestamp"] = "20260230T000000000000Z"
            data["record_path"] = str(impossible)
            record.rename(impossible)
            impossible.write_text(json.dumps(data, ensure_ascii=False))
            impossible.chmod(0o600)
            result = subprocess.run(
                [sys.executable, str(script), "restore", str(impossible)],
                env={**os.environ, "CODEX_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertNotIn(b"Traceback", result.stderr)

            valid = make_record(runs, [{
                "path": str(target),
                "stable_id": "personal/demo",
                "old": "English description here",
                "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式",
            }])
            result = subprocess.run(
                [sys.executable, str(script), "restore", str(valid)],
                env={**os.environ, "CODEX_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_rejects_unicode_controls_without_writing(self):
        script = Path(m.__file__)
        unsafe_values = ("\u0085", "\u2028", "\u2029", "\x00", "\x01", "\x7f")
        for control in unsafe_values:
            with self.subTest(codepoint=f"U+{ord(control):04X}"):
                with tempfile.TemporaryDirectory() as isolated:
                    home = Path(isolated).resolve()
                    target = write(home / "skills", "demo/agents/openai.yaml", "English description here")
                    catalog = home / "localize-skill-cards/approved-translations.json"
                    catalog.parent.mkdir(parents=True)
                    catalog.write_text(json.dumps({
                        "version": 1,
                        "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                        "translations": {"personal/demo": "安全汉化 Codex 技能卡片简介并保留原有语义和格式" + control},
                    }, ensure_ascii=False))
                    before = target.read_bytes()
                    for command in (("plan",), ("validate",), ("apply", "--confirm")):
                        result = subprocess.run(
                            [sys.executable, str(script), *command],
                            env={**os.environ, "CODEX_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True,
                        )
                        self.assertNotEqual(result.returncode, 0, command)
                        self.assertEqual(target.read_bytes(), before, command)
                        records = list((home / "localize-skill-cards/runs").glob("*.json"))
                        self.assertFalse(any(json.loads(p.read_text()).get("status") == "completed" for p in records), command)

        with tempfile.TemporaryDirectory() as isolated:
            home = Path(isolated).resolve()
            target = home / "skills/demo/agents/openai.yaml"
            target.parent.mkdir(parents=True)
            target.write_bytes(
                b'interface:\r\n  display_name: "Demo"\r\n'
                b'  short_description: "English description here"\r\n'
                b'policy:\r\n  allow_implicit_invocation: false'
            )
            catalog = home / "localize-skill-cards/approved-translations.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({
                "version": 1,
                "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
                "translations": {"personal/demo": "安全汉化 Codex GitHub 技能卡片并保留语义 😊"},
            }, ensure_ascii=False))
            before = target.read_bytes()
            result = subprocess.run(
                [sys.executable, str(script), "validate"],
                env={**os.environ, "CODEX_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(
                [sys.executable, str(script), "apply", "--confirm"],
                env={**os.environ, "CODEX_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            after = target.read_bytes()
            self.assertIn("安全汉化 Codex GitHub 技能卡片并保留语义 😊".encode(), after)
            self.assertEqual(after.count(b"\r\n"), before.count(b"\r\n"))
            self.assertFalse(after.endswith(b"\n"))

    def test_cli_translation_option_scope(self):
        script = Path(m.__file__)
        help_text = {}
        for command in ("scan", "plan", "apply"):
            result = subprocess.run([sys.executable, str(script), command, "--help"], check=True, capture_output=True, text=True)
            help_text[command] = result.stdout
        self.assertNotIn("--translations", help_text["scan"])
        self.assertIn("--translations", help_text["plan"])
        self.assertIn("--translations", help_text["apply"])

    def test_run_record_names_are_unique(self):
        first = m.write_record({"status": "first"}, self.root / "runs")
        second = m.write_record({"status": "second"}, self.root / "runs")
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists() and second.exists())

    def test_record_is_minimal_and_private(self):
        marker = "unrelated-content-marker"
        self.p.write_text(self.p.read_text() + f"# {marker}\n")
        row = {"path": str(self.p), "stable_id": "personal/demo", "old": "English description here", "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"}
        record = m.apply_rows([row], self.root / "runs")
        text = Path(record).read_text()
        data = json.loads(text)
        self.assertNotIn(marker, text)
        self.assertNotIn("before_data_base64", text)
        self.assertEqual(data["schema_version"], m.RECORD_SCHEMA_VERSION)
        self.assertEqual(data["record_type"], m.RECORD_TYPE)
        self.assertEqual(set(data["changes"][0]), {"path", "stable_id", "old", "new"})
        self.assertEqual(stat.S_IMODE(Path(record).parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(Path(record).stat().st_mode), 0o600)

    def test_bounded_yaml_catalog_and_discovery(self):
        yaml_limit = m.MAX_OPENAI_YAML_BYTES
        catalog_limit = m.MAX_CATALOG_BYTES
        candidate_limit = m.MAX_DISCOVER_CANDIDATES
        total_limit = m.MAX_DISCOVER_TOTAL_BYTES
        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps({
            "version": 1,
            "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
            "translations": {},
        }))
        try:
            m.MAX_OPENAI_YAML_BYTES = 8
            with self.assertRaisesRegex(ValueError, "openai.yaml exceeds"):
                m.parse_yaml(self.p)
            m.MAX_OPENAI_YAML_BYTES = yaml_limit
            m.MAX_CATALOG_BYTES = 8
            with self.assertRaisesRegex(ValueError, "translation catalog exceeds"):
                m.translations(catalog)
            m.MAX_CATALOG_BYTES = catalog_limit
            write(m.PERSONAL, "extra/agents/openai.yaml", "English description here")
            m.MAX_DISCOVER_CANDIDATES = 1
            with self.assertRaisesRegex(ValueError, "candidate count exceeds"):
                m.discover(False)
            m.MAX_DISCOVER_CANDIDATES = candidate_limit
            m.MAX_DISCOVER_TOTAL_BYTES = 1
            with self.assertRaisesRegex(ValueError, "candidate bytes exceed"):
                m.discover(False)
        finally:
            m.MAX_OPENAI_YAML_BYTES = yaml_limit
            m.MAX_CATALOG_BYTES = catalog_limit
            m.MAX_DISCOVER_CANDIDATES = candidate_limit
            m.MAX_DISCOVER_TOTAL_BYTES = total_limit
        self.assertEqual(m.parse_yaml(self.p)[3], "English description here")
        self.assertEqual(m.translations(catalog), {})

    def test_translation_terms_and_title_case_warning(self):
        errors, warnings = m.translation_issues("使用 Codex GitHub API", "使用 Codex GitHub")
        self.assertIn("must preserve API", errors)
        camel_errors, _ = m.translation_issues("保留 fooBar 和 openAI", "删除内部标识")
        self.assertIn("must preserve identifier fooBar", camel_errors)
        self.assertIn("must preserve identifier openAI", camel_errors)
        self.assertTrue(m.translation_issues("使用 Business Review 模板", "使用 Business Review 模板")[1])
        self.assertEqual(m.translation_issues("普通中文", "普通中文"), ([], []))

    def test_write_boundary_rejects_managed_without_scope(self):
        row = {"path": str(self.system_p), "stable_id": "system/sys2", "old": "系统技能简介已经是中文内容", "new": "系统技能简介已经是中文内容"}
        with self.assertRaises(ValueError):
            m.apply_rows([row], self.root / "runs")

    def test_restore_managed_requires_explicit_scope(self):
        record = make_record(self.root / "runs", [{"path": str(self.system_p), "stable_id": "system/sys2", "old": "系统技能简介已经是中文内容", "new": "系统技能简介已经是中文内容"}])
        with self.assertRaises(ValueError):
            m.restore(record)
        self.assertEqual(m.restore(record, managed=True)[0]["stable_id"], "system/sys2")

    def test_parent_symlink_escape_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        target = write(outside, "escape/agents/openai.yaml", "English description here")
        link_root = m.PERSONAL / "linked"
        link_root.symlink_to(outside, target_is_directory=True)
        escaped = link_root / "escape/agents/openai.yaml"
        with self.assertRaises(ValueError):
            m.validate_target_path(escaped, "personal/linked", False)

    def test_failed_second_write_rolls_back_first(self):
        second = write(m.PERSONAL, "second/agents/openai.yaml", "Second English description")
        rows = [
            {"path": str(self.p), "stable_id": "personal/demo", "old": "English description here", "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
            {"path": str(second), "stable_id": "personal/second", "old": "Second English description", "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"},
        ]
        real_replace = m.os.replace
        calls = {"count": 0}

        def fail_second(src, dst):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("injected second write failure")
            return real_replace(src, dst)

        m.os.replace = fail_second
        try:
            with self.assertRaises(OSError):
                m.apply_rows(rows, self.root / "runs")
        finally:
            m.os.replace = real_replace
        self.assertEqual(m.parse_yaml(self.p)[3], "English description here")
        self.assertEqual(m.parse_yaml(second)[3], "Second English description")
        records = list((self.root / "runs").glob("*.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())["status"], "rolled_back")

    def test_concurrent_drift_before_second_write_rolls_back_first(self):
        second = write(m.PERSONAL, "second/agents/openai.yaml", "Second English description")
        translated = "安全汉化 Codex 技能卡片简介并保留原有语义和格式"
        rows = [
            {"path": str(self.p), "stable_id": "personal/demo", "old": "English description here", "new": translated},
            {"path": str(second), "stable_id": "personal/second", "old": "Second English description", "new": translated},
        ]
        real_replace = m.os.replace
        calls = {"count": 0}

        def drift_after_first(src, dst):
            real_replace(src, dst)
            calls["count"] += 1
            if calls["count"] == 1:
                write(m.PERSONAL, "second/agents/openai.yaml", "Concurrent drift description")

        m.os.replace = drift_after_first
        try:
            with self.assertRaises(ValueError):
                m.apply_rows(rows, self.root / "runs")
        finally:
            m.os.replace = real_replace
        self.assertEqual(m.parse_yaml(self.p)[3], "English description here")
        self.assertEqual(m.parse_yaml(second)[3], "Concurrent drift description")
        record = next((self.root / "runs").glob("*.json"))
        self.assertEqual(json.loads(record.read_text())["status"], "rolled_back")

    def test_highest_plugin_version_wins(self):
        row = next(x for x in m.discover(True) if x["stable_id"] == "plugin/pub/pkg/plug")
        self.assertIn("/2.0.0/", row["path"])

    def test_only_description_line_and_dry_plan(self):
        good = "安全汉化 Codex 技能卡片简介并保留原有语义和格式"
        raw, new = m.replacement(self.p, good)
        self.assertEqual(len(raw.splitlines()), len(new.splitlines()))
        before = self.p.read_bytes()
        self.assertEqual(m.plan([{"path": str(self.p), "stable_id": "personal/demo", "value": "English", "valid": True}], {})[0]["action"], "needs-approval")
        self.assertEqual(before, self.p.read_bytes())

    def test_length_chinese_and_symbols(self):
        self.assertIn("Chinese", m.valid_value("a" * 25))
        self.assertIsNone(m.valid_value("安全汉化 Codex 技能卡片简介并保留原有语义和格式"))
        self.assertIsNotNone(m.valid_value("安全$技能简介" + "中文" * 20))

    def test_duplicate_and_symlink_rejected(self):
        self.p.write_text(self.p.read_text().replace("policy:", '  short_description: "重复简介中文内容足够长"\npolicy:'))
        with self.assertRaises(ValueError):
            m.parse_yaml(self.p)
        link = self.root / "link.yaml"
        link.symlink_to(self.p)
        with self.assertRaises(ValueError):
            m.atomic_write(link, b"x")

    def test_apply_prepares_record_and_writes(self):
        x = {"path": str(self.p), "stable_id": "personal/demo", "source": "personal", "old": "English description here", "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"}
        rec = m.apply_rows([x], self.root / "runs")
        d = json.loads(Path(rec).read_text())
        self.assertEqual(d["status"], "completed")
        self.assertEqual(m.parse_yaml(self.p)[3], x["new"])
        self.assertEqual(d["changes"][0]["old"], x["old"])
        self.assertEqual(set(d["changes"][0]), {"path", "stable_id", "old", "new"})

    def test_apply_record_update_failure_rolls_back_files(self):
        row = {"path": str(self.p), "stable_id": "personal/demo", "old": "English description here", "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"}
        real_update = m.update_record
        calls = {"count": 0}

        def fail_once(record, payload):
            calls["count"] += 1
            if calls["count"] == 1:
                raise OSError("injected completed record failure")
            return real_update(record, payload)

        m.update_record = fail_once
        try:
            with self.assertRaisesRegex(RuntimeError, "apply transaction failed during record update"):
                m.apply_rows([row], self.root / "runs")
        finally:
            m.update_record = real_update
        self.assertEqual(m.parse_yaml(self.p)[3], "English description here")
        record = next((self.root / "runs").glob("*.json"))
        self.assertEqual(json.loads(record.read_text())["status"], "rolled_back")

    def test_apply_persistent_record_failure_still_rolls_back_files(self):
        row = {"path": str(self.p), "stable_id": "personal/demo", "old": "English description here", "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"}
        real_update = m.update_record

        def fail_always(record, payload):
            raise OSError("persistent record failure")

        m.update_record = fail_always
        try:
            with self.assertRaisesRegex(RuntimeError, "record_error=persistent record failure"):
                m.apply_rows([row], self.root / "runs")
        finally:
            m.update_record = real_update
        self.assertEqual(m.parse_yaml(self.p)[3], "English description here")

    def test_apply_requires_nonempty_stable_id(self):
        base = {"path": str(self.p), "old": "English description here", "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"}
        for value in (None, ""):
            row = dict(base)
            if value is not None:
                row["stable_id"] = value
            with self.assertRaisesRegex(ValueError, "stable_id must be a non-empty string"):
                m.apply_rows([row], self.root / "runs")

    def test_restore_preview_confirm_and_drift_reject(self):
        old = m.parse_yaml(self.p)[3]
        new = "安全汉化 Codex 技能卡片简介并保留原有语义和格式"
        rec = m.apply_rows([{"path": str(self.p), "stable_id": "personal/demo", "old": old, "new": new}], self.root / "runs")
        self.assertEqual(m.restore(rec)[0]["new"], old)
        m.restore(rec, True)
        self.assertEqual(m.parse_yaml(self.p)[3], old)
        _, restored_record = m.load_restore_record(rec)
        self.assertEqual(restored_record["restore_status"], "completed")
        rec = m.apply_rows([{"path": str(self.p), "stable_id": "personal/demo", "old": old, "new": new}], self.root / "runs")
        _, data = m.replacement(self.p, "另一个安全中文 Codex 技能简介并保留不同语义格式")
        m.atomic_write(self.p, data)
        with self.assertRaises(ValueError):
            m.restore(rec, True)

    def test_failed_second_restore_rolls_back_first_restore(self):
        second = write(m.PERSONAL, "second/agents/openai.yaml", "Second English description")
        translated = "安全汉化 Codex 技能卡片简介并保留原有语义和格式"
        rows = [
            {"path": str(self.p), "stable_id": "personal/demo", "old": "English description here", "new": translated},
            {"path": str(second), "stable_id": "personal/second", "old": "Second English description", "new": translated},
        ]
        record = m.apply_rows(rows, self.root / "runs")
        real_replace = m.os.replace
        calls = {"count": 0}

        def fail_second(src, dst):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("injected second restore failure")
            return real_replace(src, dst)

        m.os.replace = fail_second
        try:
            with self.assertRaises(OSError):
                m.restore(record, True)
        finally:
            m.os.replace = real_replace
        self.assertEqual(m.parse_yaml(self.p)[3], translated)
        self.assertEqual(m.parse_yaml(second)[3], translated)
        restored = json.loads(Path(record).read_text())
        self.assertEqual(restored["restore_status"], "rolled_back")
        self.assertIn("second restore failure", restored["restore_error"])
        self.assertEqual(len(m.restore(record)), 2)

    def test_restore_record_update_failure_rolls_back_files(self):
        translated = "安全汉化 Codex 技能卡片简介并保留原有语义和格式"
        row = {"path": str(self.p), "stable_id": "personal/demo", "old": "English description here", "new": translated}
        record = m.apply_rows([row], self.root / "runs")
        real_update = m.update_record
        calls = {"count": 0}

        def fail_once(path, payload):
            calls["count"] += 1
            if calls["count"] == 1:
                raise OSError("injected restore record failure")
            return real_update(path, payload)

        m.update_record = fail_once
        try:
            with self.assertRaisesRegex(RuntimeError, "restore transaction failed during record update"):
                m.restore(record, True)
        finally:
            m.update_record = real_update
        self.assertEqual(m.parse_yaml(self.p)[3], translated)
        self.assertEqual(json.loads(Path(record).read_text())["restore_status"], "rolled_back")

    def test_restore_persistent_record_failure_still_rolls_back_files(self):
        translated = "安全汉化 Codex 技能卡片简介并保留原有语义和格式"
        row = {"path": str(self.p), "stable_id": "personal/demo", "old": "English description here", "new": translated}
        record = m.apply_rows([row], self.root / "runs")
        real_update = m.update_record

        def fail_always(path, payload):
            raise OSError("persistent restore record failure")

        m.update_record = fail_always
        try:
            with self.assertRaisesRegex(RuntimeError, "record_error=persistent restore record failure"):
                m.restore(record, True)
        finally:
            m.update_record = real_update
        self.assertEqual(m.parse_yaml(self.p)[3], translated)

    def test_restore_requires_nonempty_stable_id(self):
        change = {"path": str(self.p), "old": "English description here", "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"}
        record = make_record(self.root / "runs", [change])
        with self.assertRaisesRegex(ValueError, "stable_id must be a non-empty string"):
            m.restore(record)
        change["stable_id"] = ""
        data = json.loads(Path(record).read_text())
        data["changes"] = [change]
        m.update_record(record, data)
        with self.assertRaisesRegex(ValueError, "stable_id must be a non-empty string"):
            m.restore(record)

    def test_restore_path_escape_rejected(self):
        rec = make_record(self.root / "runs", [{"path": str(self.root.parent / "outside-target"), "stable_id": "personal/x", "old": "x", "new": "安全中文技能简介足够长"}])
        with self.assertRaises(ValueError):
            m.restore(rec, True)

    def test_restore_stable_id_mismatch_rejected(self):
        rec = make_record(self.root / "runs", [{"path": str(self.p), "stable_id": "personal/other", "old": "English description here", "new": "安全汉化 Codex 技能卡片简介并保留原有语义和格式"}])
        with self.assertRaises(ValueError):
            m.restore(rec, True)

    def test_restore_rejects_external_and_symlink_records(self):
        change = {"path": str(self.p), "stable_id": "personal/demo", "old": "Earlier description", "new": "English description here"}
        m.private_record_root(m.RUN_ROOT)
        external = make_record(self.root / "external-records", [change])
        with self.assertRaisesRegex(ValueError, "inside the current run root"):
            m.restore(external)
        real_record = make_record(self.root / "runs", [change])
        link = self.root / "runs/record-link.json"
        link.symlink_to(real_record)
        with self.assertRaisesRegex(ValueError, "without symlinks|real regular file"):
            m.restore(link)
        real_parent = self.root / "real-record-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-record-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "cross a symlink"):
            m.private_record_root(linked_parent / "runs")
        component_record = make_record(real_parent / "runs", [change])
        m.RUN_ROOT = linked_parent / "runs"
        with self.assertRaisesRegex(ValueError, "symlinked"):
            m.restore(component_record)

    def test_restore_rejects_malformed_record_metadata(self):
        change = {"path": str(self.p), "stable_id": "personal/demo", "old": "Earlier description", "new": "English description here"}

        def altered(mutator):
            record = make_record(self.root / "runs", [change])
            data = json.loads(Path(record).read_text())
            mutator(data)
            m.update_record(record, data)
            return record

        cases = [
            (lambda d: d.pop("schema_version"), "missing required"),
            (lambda d: d.update(schema_version=True), "schema or type"),
            (lambda d: d.update(record_type="unexpected"), "schema or type"),
            (lambda d: d.update(timestamp=1), "timestamp"),
            (lambda d: d.update(status=1), "status must be a string"),
            (lambda d: d.update(status="prepared"), "status must be completed"),
            (lambda d: d.update(record_path=1), "record_path"),
            (lambda d: d.update(record_path=str(self.root / "different-record")), "record_path"),
            (lambda d: d.update(changes=[]), "non-empty list"),
            (lambda d: d["changes"][0].update(extra="unexpected"), "fields are invalid"),
            (lambda d: d["changes"][0].update(old="unsafe\x01value"), "safe printable"),
            (lambda d: d.update(restore_status=None), "restore_status is invalid"),
            (lambda d: d.update(restore_status=1), "restore_status is invalid"),
            (lambda d: d.update(restore_status="rolled_back"), "requires error details"),
            (lambda d: d.update(restore_status="completed", restore_error="unexpected"), "error details require"),
            (lambda d: d.update(restore_status="rolled_back", restore_error="failure", restore_rollback_errors=[1]), "list of strings"),
        ]
        for mutator, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    m.restore(altered(mutator))

    def test_restore_rejects_unknown_top_level_fields_before_targets(self):
        change = {"path": str(self.p), "stable_id": "personal/demo", "old": "Earlier description", "new": "English description here"}
        before = self.p.read_bytes()
        for field in ("unrelated_marker", "before_data_base64"):
            for confirm in (False, True):
                with self.subTest(field=field, confirm=confirm):
                    record = make_record(self.root / "runs", [change])
                    data = json.loads(Path(record).read_text())
                    data[field] = "must-not-be-accepted"
                    m.update_record(record, data)
                    with self.assertRaisesRegex(ValueError, "unknown top-level fields"):
                        m.restore(record, confirm)
                    self.assertEqual(self.p.read_bytes(), before)

    def test_restore_rejects_oversized_result_and_accepts_bounded_old(self):
        current = "English description here"
        before = self.p.read_bytes()
        oversized = "A" * m.MAX_OPENAI_YAML_BYTES
        record = make_record(self.root / "runs", [{"path": str(self.p), "stable_id": "personal/demo", "old": oversized, "new": current}])
        for confirm in (False, True):
            with self.subTest(confirm=confirm):
                with self.assertRaisesRegex(ValueError, "resulting openai.yaml exceeds"):
                    m.restore(record, confirm)
                self.assertEqual(self.p.read_bytes(), before)

        bounded = "A" * 4096
        record = make_record(self.root / "runs", [{"path": str(self.p), "stable_id": "personal/demo", "old": bounded, "new": current}])
        self.assertEqual(m.restore(record)[0]["new"], bounded)
        m.restore(record, True)
        self.assertEqual(m.parse_yaml(self.p)[3], bounded)

    def test_restore_record_change_and_size_limits(self):
        change = {"path": str(self.p), "stable_id": "personal/demo", "old": "Earlier description", "new": "English description here"}
        change_limit = m.MAX_RECORD_CHANGES
        record_limit = m.MAX_RECORD_BYTES
        try:
            m.MAX_RECORD_CHANGES = 1
            with self.assertRaisesRegex(ValueError, "changes exceed"):
                m.apply_rows([change, dict(change)], self.root / "runs")
            record = make_record(self.root / "runs", [change, dict(change)])
            with self.assertRaisesRegex(ValueError, "changes exceed"):
                m.restore(record)
            record = make_record(self.root / "runs", [change])
            m.MAX_RECORD_BYTES = 1
            with self.assertRaisesRegex(ValueError, "restore record exceeds"):
                m.restore(record)
        finally:
            m.MAX_RECORD_CHANGES = change_limit
            m.MAX_RECORD_BYTES = record_limit


if __name__ == "__main__":
    unittest.main()
