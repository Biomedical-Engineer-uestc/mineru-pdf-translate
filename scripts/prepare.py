#!/usr/bin/env python3
"""PDF 论文翻译流水线 —— 第 1 步：解析、占位符化、分块。

把 PDF 交给 MinerU 解析成 markdown，然后把图片/公式/表格替换成占位符，
再按章节切成小块，供 LLM 逐块翻译。

用法:
    python prepare.py <input.pdf> [--work DIR] [--tier standard] [--pages 1-5]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from config import find_mineru_kit

MAX_CHUNK_CHARS = 6000  # 单块上限，控制单次翻译的输出长度

REFERENCE_HEADING = re.compile(
    r"(?:\d+(?:\.\d+)*[.)]?\s+)?(?:references|bibliography|literature cited|works cited|参考文献)",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


# --------------------------------------------------------------------------
# MinerU 调用
# --------------------------------------------------------------------------
def run_mineru(pdf: Path, work: Path, tier: str, pages: str | None) -> Path:
    mineru_kit = find_mineru_kit()
    if mineru_kit is None:
        sys.exit(
            "找不到 mineru-kit。请先运行 setup.bat 安装，"
            "或设置环境变量 MINERU_KIT 指向 mineru-kit 可执行文件。"
        )
    if not pdf.exists():
        sys.exit(f"输入文件不存在: {pdf}")

    raw_dir = work / "raw"
    if (raw_dir / "markdown.md").exists():
        print(f"[跳过] 已有解析结果: {raw_dir / 'markdown.md'}")
        return raw_dir / "markdown.md"

    raw_zip = work / "raw.zip"
    cmd = [
        str(mineru_kit), "parse", str(pdf),
        "-o", str(raw_zip), "--format", "zip", "--tier", tier,
    ]
    if pages:
        cmd += ["--pages", pages]

    print(f"[1/4] 调用 MinerU 解析（tier={tier}）…")
    print("      " + " ".join(cmd))
    proc = subprocess.run(cmd)
    if proc.returncode != 0 or not raw_zip.exists():
        sys.exit(f"MinerU 解析失败，退出码 {proc.returncode}")

    raw_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(raw_zip) as z:
        z.extractall(raw_dir)
    return raw_dir / "markdown.md"


# --------------------------------------------------------------------------
# 占位符保护
# --------------------------------------------------------------------------
class Placeholders:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}
        self.counters = {"EQ": 0, "FIG": 0, "TABLE": 0, "REF": 0}

    def add(self, kind: str, payload: str) -> str:
        self.counters[kind] += 1
        key = f"{kind}:{self.counters[kind]:03d}"
        self.store[key] = {"kind": kind, "payload": payload}
        return f"[[{key}]]"

    def tokenize(self, text: str) -> list[str]:
        return re.findall(r"\[\[(?:EQ|FIG|TABLE|REF):\d{3,}\]\]", text)


def protect_display_math(md: str, ph: Placeholders) -> str:
    """行间公式转占位符，同时把 \\tag{n} 换成右侧编号。"""

    def repl(m: re.Match) -> str:
        body = m.group(1).strip()
        body = re.sub(r"\\tag\s*\{([^}]*)\}", r"\\qquad (\1)", body)
        return ph.add("EQ", f"$$\n{body}\n$$")

    return re.sub(r"\$\$(.+?)\$\$", repl, md, flags=re.DOTALL)


def protect_tables(md: str, ph: Placeholders) -> str:
    return re.sub(
        r"<table\b.*?</table>",
        lambda m: ph.add("TABLE", m.group(0)),
        md,
        flags=re.DOTALL | re.IGNORECASE,
    )


def protect_images(md: str, ph: Placeholders) -> str:
    def repl(m: re.Match) -> str:
        target = m.group(1).strip()
        return ph.add("FIG", target)

    md = re.sub(r"!\[[^\]]*\]\(\s*([^)]+?)\s*\)", repl, md)
    # 兜底：残留的 <img>
    md = re.sub(
        r'<img\b[^>]*src="([^"]+)"[^>]*>',
        lambda m: ph.add("FIG", m.group(1)),
        md,
        flags=re.IGNORECASE,
    )
    return md


# --------------------------------------------------------------------------
# HTML 规整：把 MinerU 输出的内联 HTML 变成标准 markdown
# --------------------------------------------------------------------------
def normalize_html(md: str) -> str:
    md = re.sub(r"<strong\b[^>]*>(.*?)</strong>", r"**\1**", md, flags=re.S | re.I)
    md = re.sub(r"<b\b[^>]*>(.*?)</b>", r"**\1**", md, flags=re.S | re.I)
    md = re.sub(r"<em\b[^>]*>(.*?)</em>", r"*\1*", md, flags=re.S | re.I)
    md = re.sub(r"<sup\b[^>]*>(.*?)</sup>", r"^\1^", md, flags=re.S | re.I)
    md = re.sub(r"<sub\b[^>]*>(.*?)</sub>", r"~\1~", md, flags=re.S | re.I)
    md = re.sub(r"<br\s*/?>", "\n", md, flags=re.I)
    # 去掉保留下来的 span/small/div 等包装，只留内容
    md = HTML_TAG.sub("", md)
    return md


# --------------------------------------------------------------------------
# 参考文献切分与分块
# --------------------------------------------------------------------------
def split_references(md: str, ph: Placeholders | None = None) -> tuple[str, str]:
    """Bound each bibliography by the next heading; REF preserves reading order.

    Conservatively stop at any heading level, since OCR may misassign levels.
    Unheaded boundaries cannot be inferred reliably and require source review.
    """
    headings = list(HEADING_RE.finditer(md))
    parts, refs = [], []
    cursor = 0
    for index, heading in enumerate(headings):
        title = heading.group(1).strip().strip("*_").strip()
        if not REFERENCE_HEADING.fullmatch(title):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(md)
        block = md[heading.start():end].strip() + "\n"
        parts.append(md[cursor:heading.start()])
        if ph is not None:
            parts.append(ph.add("REF", block) + "\n\n")
        refs.append(block)
        cursor = end
    if not refs:
        return md, ""
    parts.append(md[cursor:])
    return "".join(parts), "\n".join(refs)


def split_sections(md: str) -> list[str]:
    sections: list[str] = []
    cur: list[str] = []
    for line in md.split("\n"):
        if re.match(r"^#{1,2}\s+\S", line) and any(x.strip() for x in cur):
            sections.append("\n".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        sections.append("\n".join(cur))
    return [s.strip("\n") for s in sections if s.strip()]


def pack_sections(sections: list[str], max_chars: int) -> list[str]:
    """把小节合并成不超过 max_chars 的块；超长小节按段落切开。"""
    chunks: list[str] = []
    buf: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal buf, size
        if buf:
            chunks.append("\n\n".join(buf).strip("\n"))
            buf, size = [], 0

    for sec in sections:
        if len(sec) > max_chars:
            flush()
            paras = [p for p in sec.split("\n\n") if p.strip()]
            acc: list[str] = []
            acc_len = 0
            for p in paras:
                if acc and acc_len + len(p) > max_chars:
                    chunks.append("\n\n".join(acc).strip("\n"))
                    acc, acc_len = [], 0
                acc.append(p)
                acc_len += len(p)
            if acc:
                chunks.append("\n\n".join(acc).strip("\n"))
            continue
        if size + len(sec) > max_chars:
            flush()
        buf.append(sec)
        size += len(sec)
    flush()
    return [c for c in chunks if c.strip()]


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 首页原文保留清单
# --------------------------------------------------------------------------
CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
PLACEHOLDER_RE = re.compile(r"\[\[[A-Z]+:\d+\]\]")
AFFILIATION_RE = re.compile(r"^\d{1,2}[\s.]+")


def frontmatter_exemptions(body: str, chunks: list[str]) -> dict[int, list[dict]]:
    """把首页的作者行和编号机构行登记为原文保留段落。

    只处理第一个二级标题之前的内容，并且只认两种明确形态：
    标题后紧跟的作者行，以及 "1 School of..." 这类带编号的单位行。
    脚注、通讯信息、关键词不在此列——它们通常应当翻译，是否保留由译者决定。

    豁免要求译文与原文完全一致，所以一旦改动这些段落，校验仍会报错。
    """
    match = re.search(r"^##\s+\S", body, re.MULTILINE)
    front = body[: match.start()] if match else body
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", front) if p.strip()]

    items: list[dict] = []
    after_title = False
    authors_taken = False
    for para in paragraphs:
        if para.startswith("# "):
            after_title = True
            continue
        if not after_title or CJK_CHAR_RE.search(para):
            continue

        if not authors_taken and len(para) < 400 and "^" in para and not para.rstrip().endswith("."):
            items.append({"text": para, "reason": "作者姓名与上标"})
            authors_taken = True
            continue

        plain = PLACEHOLDER_RE.sub("", para).strip()
        if AFFILIATION_RE.match(plain):
            items.append({"text": para, "reason": "作者机构原名"})

    by_chunk: dict[int, list[dict]] = {}
    for index, text in enumerate(chunks):
        keep = [item for item in items if item["text"] in text]
        if keep:
            by_chunk[index] = keep
    return by_chunk


def main() -> None:
    ap = argparse.ArgumentParser(description="PDF 论文翻译流水线 - 准备阶段")
    ap.add_argument("pdf", type=Path, help="输入的 PDF 文件")
    ap.add_argument("--work", type=Path, help="工作目录（默认与 PDF 同级）")
    ap.add_argument("--tier", default="basic",
                    help="MinerU 解析档位：flash / basic / standard / advanced，默认 basic（最快）")
    ap.add_argument("--pages", default=None, help="只解析部分页，如 1-5")
    args = ap.parse_args()

    pdf = args.pdf.expanduser().resolve()
    work = (args.work or pdf.parent / f"{pdf.stem}_translate").expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)

    md_path = run_mineru(pdf, work, args.tier, args.pages)
    md = md_path.read_text(encoding="utf-8", errors="replace")

    print("[2/4] 占位符化（公式 / 图片 / 表格）…")
    ph = Placeholders()
    md = protect_display_math(md, ph)
    md = protect_tables(md, ph)
    md = protect_images(md, ph)
    md = normalize_html(md)

    body, refs = split_references(md, ph)
    (work / "references.md").write_text(refs, encoding="utf-8")
    if refs:
        print(f"      参考文献已单独保存（{len(refs)} 字符，不翻译）")

    print("[3/4] 分块…")
    chunks = pack_sections(split_sections(body), MAX_CHUNK_CHARS)
    exemptions = frontmatter_exemptions(body, chunks)
    chunk_dir = work / "chunks"
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    chunk_dir.mkdir(parents=True)

    manifest = {
        "source": str(pdf),
        "tier": args.tier,
        "created": datetime.now().isoformat(timespec="seconds"),
        "work_dir": str(work),
        "placeholders": ph.store,
        "chunks": [],
        "stats": {},
    }

    for i, text in enumerate(chunks):
        name = f"chunk_{i:02d}"
        (chunk_dir / f"{name}.md").write_text(text + "\n", encoding="utf-8")
        entry = {
            "id": name,
            "file": f"chunks/{name}.md",
            "chars": len(text),
            "placeholders": ph.tokenize(text),
            "headings": len([l for l in text.split("\n") if l.strip().startswith("#")]),
        }
        if i in exemptions:
            entry["verbatim_paragraphs"] = exemptions[i]
        manifest["chunks"].append(entry)

    translated_dir = work / "translated"
    translated_dir.mkdir(exist_ok=True)

    total_chars = sum(c["chars"] for c in manifest["chunks"])
    manifest["stats"] = {
        "chunks": len(chunks),
        "chars": total_chars,
        "est_source_tokens": round(total_chars / 4),
        "images": ph.counters["FIG"],
        "equations": ph.counters["EQ"],
        "tables": ph.counters["TABLE"],
        "references_chars": len(refs),
    }
    (work / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    glossary = work / "glossary.md"
    if not glossary.exists():
        glossary.write_text(
            "# 术语表\n\n"
            "翻译过程中维护，确保同一术语全文一致。格式：`英文 = 中文`\n\n"
            "示例：\n"
            "- cortical shape asymmetry = 皮层形状不对称\n"
            "- eigenfunction = 特征函数\n\n"
            "## 已确认术语\n\n",
            encoding="utf-8",
        )

    print("[4/4] 完成，汇总：")
    print(f"      工作目录        {work}")
    print(f"      文本块          {len(chunks)} 个 → chunks/chunk_00.md …")
    print(f"      正文字符        {total_chars}（约 {round(total_chars/4)} tokens）")
    print(f"      占位符          图片 {ph.counters['FIG']} / 公式 {ph.counters['EQ']} / 表格 {ph.counters['TABLE']}")
    exempt_total = sum(len(v) for v in exemptions.values())
    if exempt_total:
        print(f"      首页保留段落    {exempt_total} 条（作者行与编号机构行，已自动登记豁免）")
    print(f"      参考文献        {len(refs)} 字符（原样保留，不翻译）")
    print()
    print("下一步：逐个翻译 chunks/*.md，结果写入 translated/<同名>.md")
    print("       全部完成后运行 check.py 校验，再运行 build.py 生成 PDF。")


if __name__ == "__main__":
    main()
