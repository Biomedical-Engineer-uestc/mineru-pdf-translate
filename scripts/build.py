#!/usr/bin/env python3
"""PDF 论文翻译流水线 —— 第 3 步：回填占位符、合并、生成 PDF。

流程：合并译文 → 还原图片/公式/表格 → 拼上参考文献 → pandoc 转 HTML
      → Edge 无头模式打印 PDF。全程不依赖 LaTeX。

用法:
    python build.py <work-dir> [--output out.pdf]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from config import find_edge, find_pandoc
from check import print_report, validate_work

TOKEN_RE = re.compile(r"\[\[(EQ|FIG|TABLE|REF):(\d{3,})\]\]")

CSS = """
@page { size: A4; margin: 2.2cm 2.2cm 2.4cm 2.2cm; }
html { -webkit-print-color-adjust: exact; }
body {
  font-family: "Times New Roman", "SimSun", serif;
  font-size: 10.5pt; line-height: 1.65; color: #000;
  text-align: justify; text-justify: inter-ideograph;
}
h1, h2, h3, h4 { font-family: "Times New Roman", "Microsoft YaHei", sans-serif; }
h1 { font-size: 17pt; text-align: center; line-height: 1.3; margin: 0.2em 0 0.7em; }
h2 { font-size: 13pt; margin: 1.3em 0 0.45em; text-align: left; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 1em 0 0.35em; text-align: left; page-break-after: avoid; }
h4 { font-size: 10.5pt; margin: 0.8em 0 0.3em; text-align: left; }
p { margin: 0.45em 0; overflow-wrap: anywhere; text-indent: 2em; }
/* 含链接的段落左对齐：长 URL 无法断开时，两端对齐会把整行字撑开 */
p:has(a) { text-align: left; }
.authors, .authors p { text-align: center; text-indent: 0; font-size: 10.5pt; margin: 0.5em 0 0.3em; }
.note, .note p { text-align: center; text-indent: 0; font-size: 9pt; color: #333; margin: 0.2em 0 0.8em; }
.abstract p { text-indent: 2em; }
.abstract h2 { text-align: left; }
.affiliations { font-size: 8.5pt; line-height: 1.45; color: #222; margin-top: 0.8em; }
.affiliations p { text-align: left; text-indent: 0; margin: 0.12em 0; }
.label p { text-indent: 0; text-align: left; font-family: "Times New Roman", "Microsoft YaHei", sans-serif; margin: 1em 0 0.4em; }
img { max-width: 100%; height: auto; display: block; margin: 1em auto; page-break-inside: avoid; }
figure { margin: 1em 0; page-break-inside: avoid; }
table { border-collapse: collapse; margin: 1em auto; font-size: 9pt; page-break-inside: avoid; }
td, th { border: 1px solid #888; padding: 3px 7px; }
code { font-family: Consolas, monospace; font-size: 0.92em; }
math { font-size: 1.05em; }
blockquote { margin: 0.8em 0; padding-left: 1em; border-left: 3px solid #ccc; color: #444; }
"""


def style_frontmatter(md: str) -> str:
    """把标题页（标题/作者/摘要/单位）改写成便于排版的 fenced div。

    MinerU 往往不输出 Abstract 标题，这里在检测到摘要段时补一个「## 摘要」。
    """
    lines = md.split("\n")
    h1 = next((i for i, l in enumerate(lines) if re.match(r"^#\s+\S", l)), None)
    if h1 is None or h1 > 6:
        return md

    end = next(
        (i for i, l in enumerate(lines) if i > h1 and re.match(r"^#{2,3}\s+\S", l)),
        len(lines),
    )
    head, front, tail = lines[:h1], lines[h1:end], lines[end:]

    title_line = front[0]
    paras: list[str] = []
    cur: list[str] = []
    for line in front[1:]:
        if line.strip() == "":
            if cur:
                paras.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        paras.append("\n".join(cur))
    if len(paras) < 2:
        return md

    # 最长且足够长的段落当作摘要
    lengths = [len(re.sub(r"\[\[[A-Z]+:\d{3}\]\]", "", p)) for p in paras]
    best = max(range(len(paras)), key=lambda i: lengths[i])
    abstract_idx = best if lengths[best] >= 400 else None

    has_abstract_heading = any(
        re.match(r"^#{1,3}\s*(摘要|abstract)", l, re.IGNORECASE) for l in front
    )

    def wrap(cls: str, text: str) -> list[str]:
        return [f"::: {{.{cls}}}", text.strip(), ":::", ""]

    out = head + [title_line, ""]
    for i, p in enumerate(paras):
        if abstract_idx is not None and i == abstract_idx:
            if not has_abstract_heading:
                out += ["## 摘要", ""]
            out += wrap("abstract", p)
        elif i == 0:
            out += wrap("authors", p)
        elif re.fullmatch(r"\*\*[^*]+\*\*", p.strip()):
            out += wrap("label", p)
        elif re.match(r"^\\?[*]\s", p.strip()):
            out += wrap("note", p)
        else:
            out += wrap("affiliations", p)

    out += tail
    return "\n".join(out)


def find_tool(candidates, name: str) -> str:
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    sys.exit(f"找不到 {name}，请先运行 setup.bat 安装。")


def restore(text: str, placeholders: dict) -> str:
    def expand(key: str, stack: tuple[str, ...]) -> str:
        if key in stack:
            raise ValueError(f"占位符循环引用: {key}")
        entry = placeholders.get(key)
        if entry is None:
            raise ValueError(f"找不到占位符: {key}")
        if entry["kind"] == "FIG":
            return f"![]({entry['payload']})"
        return TOKEN_RE.sub(
            lambda m: expand(f"{m.group(1)}:{m.group(2)}", (*stack, key)),
            entry["payload"],
        )

    return TOKEN_RE.sub(lambda m: expand(f"{m.group(1)}:{m.group(2)}", ()), text)


def assemble(work: Path, manifest: dict) -> str:
    parts = [
        (work / "translated" / f"{ch['id']}.md").read_text(encoding="utf-8").strip("\n")
        for ch in manifest["chunks"]
    ]
    body = "\n\n".join(parts)
    # Legacy work directories have no REF tokens and stored references separately.
    if not any(p["kind"] == "REF" for p in manifest["placeholders"].values()):
        refs = work / "references.md"
        if refs.exists():
            body += "\n\n" + refs.read_text(encoding="utf-8")
    return restore(body, manifest["placeholders"])


def main() -> None:
    ap = argparse.ArgumentParser(description="PDF 论文翻译流水线 - 构建阶段")
    ap.add_argument("work", type=Path, help="工作目录")
    ap.add_argument("--output", type=Path, default=None, help="输出 PDF 路径")
    args = ap.parse_args()

    work = args.work.expanduser().resolve()
    manifest_path = work / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"找不到 {manifest_path}，请先运行 prepare.py")

    try:
        report = validate_work(work)
        print_report(work, report)
        if report["failed"] or report["missing"]:
            sys.exit("构建已停止：请先修复校验失败或缺失的译文；不会用英文原文代替。")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print("[1/4] 合并译文并还原占位符…")
        body = assemble(work, manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(f"构建前检查失败: {exc}")

    final_dir = work / "final"
    final_dir.mkdir(exist_ok=True)

    images_src = work / "raw" / "images"
    if images_src.exists():
        images_dst = final_dir / "images"
        if images_dst.exists():
            shutil.rmtree(images_dst)
        shutil.copytree(images_src, images_dst)

    stem = Path(manifest["source"]).stem
    md_out = final_dir / f"{stem}.zh.md"
    body = style_frontmatter(body.strip())
    md_out.write_text(body + "\n", encoding="utf-8")

    title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else stem

    header = final_dir / "_header.html"
    header.write_text(f"<style>{CSS}</style>", encoding="utf-8")

    pandoc = find_tool([find_pandoc()], "pandoc")
    html_out = final_dir / f"{stem}.zh.html"

    print("[2/4] pandoc 转 HTML…")
    cmd = [
        pandoc, str(md_out),
        "-o", str(html_out),
        "--standalone",
        "--mathml",
        # pagetitle 只进 <title> 标签，不渲染成页面内的标题块，避免和正文 H1 重复
        "--metadata", f"pagetitle={title}",
        "--metadata", "lang=zh-CN",
        "-H", str(header),
        "--resource-path", str(final_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(proc.stderr[-3000:])
        sys.exit("pandoc 转换失败")
    if proc.stderr.strip():
        print("      pandoc 提示:", proc.stderr.strip().splitlines()[-1])

    print("[3/4] Edge 打印 PDF…")
    edge = find_tool([find_edge()], "Microsoft Edge（或 Chrome）")
    pdf_out = (args.output.expanduser().resolve() if args.output
               else final_dir / f"{stem}.zh.pdf")
    pdf_out.parent.mkdir(parents=True, exist_ok=True)
    if pdf_out.exists():
        try:
            pdf_out.unlink()
        except PermissionError:
            # 文件可能正被阅读器占用，换个名字输出而不是直接失败
            alt = pdf_out.with_name(f"{pdf_out.stem}_new{pdf_out.suffix}")
            n = 2
            while alt.exists():
                alt = pdf_out.with_name(f"{pdf_out.stem}_new{n}{pdf_out.suffix}")
                n += 1
            print(f"      ⚠ 原文件被占用，改写到 {alt.name}")
            pdf_out = alt

    profile = work / "_edge_profile"
    profile.mkdir(exist_ok=True)

    cmd = [
        edge,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=10000",
        f"--print-to-pdf={pdf_out}",
        html_out.as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    for _ in range(20):
        if pdf_out.exists() and pdf_out.stat().st_size > 0:
            break
        time.sleep(0.5)

    if not pdf_out.exists() or pdf_out.stat().st_size == 0:
        print(proc.stderr[-2000:])
        sys.exit(f"PDF 生成失败。可以手动打开 {html_out} 用浏览器打印。")

    print("[4/4] 完成")
    print(f"      Markdown  {md_out}  ({md_out.stat().st_size/1024:.0f} KB)")
    print(f"      HTML      {html_out}")
    print(f"      PDF       {pdf_out}  ({pdf_out.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
