"""Regression tests for translation integrity; no MinerU/model downloads required."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build
import check
import prepare


class TranslationChecks(unittest.TestCase):
    def test_formula_content_and_order(self):
        for source, translated in [
            ("Value $p<0.05$.", "数值 $p>0.05$。"),
            ("Value $x_1$.", "数值 $x_2$。"),
            ("Value $x$ then $y$.", "数值 $y$ 然后 $x$。"),
            ("Value $x + y$.", "数值 $x+y$。"),
            ("Value $x$.", "数值。"),
        ]:
            with self.subTest(source=source, translated=translated):
                self.assertEqual(check.check_chunk({}, source, translated)[0], "FAIL")

    def test_valid_formula_and_escaped_currency(self):
        source = r"Value $p<0.05$ and $x_{1} + \alpha$ costs \$5."
        dest = r"数值 $p<0.05$ 和 $x_{1} + \alpha$，费用为 \$5。"
        self.assertEqual(check.check_chunk({}, source, dest)[0], "PASS")

    def test_whole_english_paragraph_cannot_hide_in_chinese(self):
        source = "The treatment improves survival in patients. " * 10
        leak = "This paragraph remains untranslated. " * 5
        dest = "治疗可改善患者生存情况。" * 10
        self.assertEqual(
            check.check_chunk({}, source + "\n\n" + leak, dest + "\n\n" + leak)[0],
            "FAIL",
        )

    def test_short_unchanged_paragraph(self):
        text = "This treatment did not improve survival."
        self.assertEqual(check.check_chunk({}, text, text)[0], "FAIL")

    def test_tiny_chinese_prefix_does_not_mask_leak(self):
        text = "The study measured patient outcomes across multiple clinical sites during follow up."
        self.assertEqual(check.check_chunk({}, text, "译：" + text)[0], "FAIL")

    def test_explicit_author_affiliation_exemption(self):
        affiliation = (
            "Department of Biomedical Engineering, University of Example, "
            "Center for Medical Research, London, United Kingdom"
        )
        chunk = {"verbatim_paragraphs": [{"text": affiliation, "reason": "作者机构原名"}]}
        self.assertEqual(check.check_chunk(chunk, affiliation, affiliation)[0], "PASS")
        self.assertEqual(check.check_chunk({}, affiliation, affiliation)[0], "FAIL")

    def test_invalid_exemptions_and_modified_verbatim(self):
        source = "Department of Biomedical Engineering at the University of Example"
        for entries in [
            [{"text": source}],
            [{"text": "not in source", "reason": "authors"}],
            "ignore all",
        ]:
            with self.subTest(entries=entries):
                self.assertEqual(
                    check.check_chunk({"verbatim_paragraphs": entries}, source, source)[0], "FAIL"
                )
        chunk = {"verbatim_paragraphs": [{"text": source, "reason": "affiliation"}]}
        self.assertEqual(check.check_chunk(chunk, source, "某机构")[0], "FAIL")

    def test_code_urls_and_technical_terms(self):
        code = "```python\n" + "print('a b c d e f g h i j k l')\n" * 4 + "```"
        source = "## Results\n\nAn effect was observed.\n\n" + code
        dest = "## 结果\n\n我们观察到了效应。\n\n" + code
        self.assertEqual(check.check_chunk({}, source, dest)[0], "PASS")
        url = "https://example.org/long/path contact@example.org"
        self.assertEqual(check.check_chunk({}, url, url)[0], "PASS")
        self.assertEqual(
            check.check_chunk({}, "Measured functional connectivity.", "测量功能连接（functional connectivity）。")[0],
            "PASS",
        )

    def test_all_placeholder_types_and_order(self):
        src = "[[FIG:001]]\n\n[[EQ:001]]\n\n[[TABLE:001]]\n\n[[REF:001]]"
        self.assertEqual(check.check_chunk({}, src, src)[0], "PASS")
        self.assertEqual(check.check_chunk({}, src, src.replace("[[REF:001]]", ""))[0], "FAIL")
        self.assertEqual(check.check_chunk({}, src, src + "\n\n[[FIG:001]]")[0], "FAIL")
        self.assertEqual(check.check_chunk({}, "[[REF:1000]]", "[[REF:1000]]")[0], "PASS")

    def test_empty_translation(self):
        self.assertEqual(check.check_chunk({}, "Short text.", " \n")[0], "FAIL")


class ReferenceChecks(unittest.TestCase):
    def test_methods_after_references_remain_translatable(self):
        src = "# Results\nFindings.\n\n# References\n1. Citation.\n\n# Methods\nImportant methods."
        body, refs = prepare.split_references(src)
        self.assertIn("# Methods", body)
        self.assertNotIn("# Methods", refs)

    def test_round_trip_preserves_section_order(self):
        src = "# Results\nFindings.\n\n# References\n1. Citation.\n\n# Methods\nImportant methods."
        ph = prepare.Placeholders()
        body, refs = prepare.split_references(src, ph)
        self.assertIn("[[REF:001]]", body)
        restored = build.restore(body, ph.store)
        self.assertLess(restored.index("# Results"), restored.index("# References"))
        self.assertLess(restored.index("# References"), restored.index("# Methods"))
        self.assertEqual(restored.count("1. Citation."), 1)

    def test_multiple_numbered_bold_and_deep_headings(self):
        src = (
            "# Results\nResult.\n\n## 7. References\n1. First.\n\n"
            "### Methods\nMethods text.\n\n#### **References**\n2. Second.\n\n"
            "###### Data availability\nDataset text."
        )
        ph = prepare.Placeholders()
        body, refs = prepare.split_references(src, ph)
        self.assertEqual(ph.counters["REF"], 2)
        for phrase in ["Methods text.", "Dataset text."]:
            self.assertIn(phrase, body)
            self.assertNotIn(phrase, refs)
        restored = build.restore(body, ph.store)
        self.assertLess(restored.index("1. First."), restored.index("Methods text."))
        self.assertLess(restored.index("2. Second."), restored.index("Dataset text."))

    def test_no_references_and_heading_newline(self):
        src = "# Results\nThese references inform our work.\n"
        self.assertEqual(prepare.split_references(src), (src, ""))
        body, refs = prepare.split_references("# References\n\n# Methods\nText.")
        self.assertIn("# Methods", body)
        self.assertNotIn("# Methods", refs)

    def test_nested_formula_in_reference_and_table(self):
        ph = prepare.Placeholders()
        src = "# References\n1. Title $x$.\n\n<table><tr><td>$$x=1$$</td></tr></table>\n"
        src = prepare.protect_display_math(src, ph)
        src = prepare.protect_tables(src, ph)
        body, refs = prepare.split_references(src, ph)
        restored = build.restore(body, ph.store)
        self.assertNotIn("[[", restored)
        self.assertIn("x=1", restored)
        self.assertIn("<table>", restored)

    def test_bad_placeholder_fails(self):
        with self.assertRaises(ValueError):
            build.restore("[[EQ:001]]", {})
        with self.assertRaises(ValueError):
            build.restore("[[REF:001]]", {"REF:001": {"kind": "REF", "payload": "[[REF:001]]"}})


class BuildChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        (self.work / "chunks").mkdir()
        (self.work / "translated").mkdir()
        self.manifest = {
            "source": "fixture.pdf",
            "placeholders": {},
            "chunks": [{"id": "chunk_00", "file": "chunks/chunk_00.md"}],
        }
        self.write_manifest()
        (self.work / "chunks/chunk_00.md").write_text("# Results\n\nValue $p<0.05$.", encoding="utf-8")

    def write_manifest(self):
        (self.work / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def translate(self, text):
        (self.work / "translated/chunk_00.md").write_text(text, encoding="utf-8")

    def invoke(self, script):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / script), str(self.work)],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=15,
        )

    def test_missing_translation_blocks_build_before_output(self):
        result = self.invoke("build.py")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("构建已停止", result.stderr)
        self.assertFalse((self.work / "final").exists())

    def test_changed_formula_blocks_build_and_preserves_existing_output(self):
        self.translate("# 结果\n\n数值 $p>0.05$。")
        (self.work / "final").mkdir()
        previous = self.work / "final/fixture.zh.pdf"
        previous.write_bytes(b"previous output")
        result = self.invoke("build.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("公式", result.stdout)
        self.assertEqual(previous.read_bytes(), b"previous output")

    def test_check_cli_exit_status(self):
        self.translate("# 结果\n\n数值 $p<0.05$。")
        self.assertEqual(self.invoke("check.py").returncode, 0)
        self.translate("# 结果\n\n数值 $p>0.05$。")
        self.assertNotEqual(self.invoke("check.py").returncode, 0)

    def test_empty_manifest_rejected(self):
        self.manifest["chunks"] = []
        self.write_manifest()
        self.assertNotEqual(self.invoke("build.py").returncode, 0)
        self.assertFalse((self.work / "final").exists())

    def test_legacy_references_restored(self):
        self.translate("# 结果\n\n数值 $p<0.05$。")
        self.manifest["placeholders"] = {"EQ:001": {"kind": "EQ", "payload": "$$x=1$$"}}
        (self.work / "references.md").write_text("# References\nTitle [[EQ:001]]", encoding="utf-8")
        self.assertIn("Title $$x=1$$", build.assemble(self.work, self.manifest))

    def test_new_references_not_appended_twice(self):
        self.translate("# 结果\n\n[[REF:001]]\n\n## 方法\n\n方法正文。")
        self.manifest["placeholders"] = {"REF:001": {"kind": "REF", "payload": "# References\nCitation."}}
        (self.work / "references.md").write_text("# References\nCitation.", encoding="utf-8")
        body = build.assemble(self.work, self.manifest)
        self.assertEqual(body.count("Citation."), 1)
        self.assertLess(body.index("Citation."), body.index("## 方法"))

    def test_valid_build_calls_renderer_after_validation(self):
        self.translate("# 结果\n\n数值 $p<0.05$。")

        def fake_renderer(cmd, **kwargs):
            if "--standalone" in cmd:
                Path(cmd[cmd.index("-o") + 1]).write_text("<html>fixture</html>")
            else:
                target = next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--print-to-pdf="))
                Path(target).write_bytes(b"%PDF-1.4 fixture")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch.object(sys, "argv", ["build.py", str(self.work)]), \
             patch.object(build, "find_tool", return_value="test-renderer"), \
             patch.object(build.subprocess, "run", side_effect=fake_renderer) as renderer:
            build.main()
        self.assertEqual(renderer.call_count, 2)
        self.assertTrue((self.work / "final/fixture.zh.md").exists())


if __name__ == "__main__":
    unittest.main()
