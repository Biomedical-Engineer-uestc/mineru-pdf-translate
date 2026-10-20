"""Optional real pandoc/browser smoke test using synthetic parsed Markdown.

Usage: python -B -X utf8 tests/smoke_pdf.py <new-work-directory>
This tests preparation helpers through PDF output, not MinerU OCR quality.
"""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prepare


def main():
    work = Path(sys.argv[1]).resolve()
    work.mkdir(parents=True, exist_ok=False)
    for name in ("raw/images", "chunks", "translated"):
        (work / name).mkdir(parents=True)
    (work / "raw/images/fixture.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="420" height="90">'
        '<rect width="420" height="90" fill="#e8eef5"/>'
        '<circle cx="45" cy="45" r="22" fill="#36648b"/>'
        '<text x="90" y="52" font-family="Arial" font-size="20">Fixture image</text></svg>',
        encoding="utf-8",
    )
    source = """# Translation integrity fixture

Alice Example, Bob Example, Carol Example

## Abstract

This synthetic document tests Chinese text, formulas, tables and section order.

## Results

The observed difference was significant at $p<0.05$.

$$
E = mc^2 \\tag{1}
$$

![Fixture](images/fixture.svg)

Figure 1. A synthetic image used for rendering verification.

<table><tr><th>Group</th><th>Value</th></tr><tr><td>Control</td><td>12</td></tr></table>

## References

1. Example A. A synthetic citation for testing only.

## Methods

Methods after the references must still be translated and remain in this position.

## Data availability

This document contains synthetic data for software testing.
"""
    (work / "raw/markdown.md").write_text(source, encoding="utf-8")
    ph = prepare.Placeholders()
    protected = prepare.protect_display_math(source, ph)
    protected = prepare.protect_tables(protected, ph)
    protected = prepare.protect_images(protected, ph)
    protected = prepare.normalize_html(protected)
    body, refs = prepare.split_references(protected, ph)
    (work / "references.md").write_text(refs, encoding="utf-8")
    chunks = prepare.pack_sections(prepare.split_sections(body), 6000)
    replacements = {
        "# Translation integrity fixture": "# 翻译完整性测试样例",
        "## Abstract": "## 摘要",
        "This synthetic document tests Chinese text, formulas, tables and section order.":
            "本文是软件测试样例，用于检查中文文字、公式、表格和章节顺序。",
        "## Results": "## 结果",
        "The observed difference was significant at $p<0.05$.":
            "观察到的差异具有统计学显著性，$p<0.05$。",
        "Figure 1. A synthetic image used for rendering verification.":
            "图 1. 用于验证排版的测试图像。",
        "## Methods": "## 方法",
        "Methods after the references must still be translated and remain in this position.":
            "位于参考文献之后的方法部分仍须翻译，并保留在这一位置。",
        "## Data availability": "## 数据可用性",
        "This document contains synthetic data for software testing.":
            "本文仅包含用于软件测试的合成数据。",
    }
    manifest = {"source": "integrity-fixture.pdf", "placeholders": ph.store, "chunks": []}
    for i, chunk in enumerate(chunks):
        cid = f"chunk_{i:02d}"
        entry = {"id": cid, "file": f"chunks/{cid}.md", "placeholders": ph.tokenize(chunk)}
        authors = "Alice Example, Bob Example, Carol Example"
        if authors in chunk:
            entry["verbatim_paragraphs"] = [{"text": authors, "reason": "测试作者姓名"}]
        manifest["chunks"].append(entry)
        (work / entry["file"]).write_text(chunk, encoding="utf-8")
        translated = chunk
        for old, new in replacements.items():
            translated = translated.replace(old, new)
        (work / f"translated/{cid}.md").write_text(translated, encoding="utf-8")
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run([sys.executable, "-B", "-X", "utf8", str(ROOT / "scripts/build.py"), str(work)], check=True)
    final_md = (work / "final/integrity-fixture.zh.md").read_text(encoding="utf-8")
    assert "[[" not in final_md
    assert final_md.index("## References") < final_md.index("## 方法")
    assert final_md.count("A synthetic citation") == 1
    assert "$p<0.05$" in final_md
    print("Real PDF smoke build passed; render and inspect the resulting pages.")


if __name__ == "__main__":
    main()
