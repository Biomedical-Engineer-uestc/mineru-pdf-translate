#!/usr/bin/env python3
"""PDF 论文翻译流水线 —— 第 2 步：校验译文。

检查每块译文是否满足硬性约束（占位符、标题、行内公式），
以及软性指标（段落数、中英长度比、是否有大段未翻译）。

用法:
    python check.py <work-dir>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"\[\[(?:EQ|FIG|TABLE|REF):\d{3,}\]\]")
INLINE_MATH_RE = re.compile(r"(?<![\\$])\$(?!\$)((?:\\.|[^$\\\n])+?)(?<!\\)\$(?!\$)")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")


def prose_blocks(text: str) -> list[str]:
    """Exclude fenced code, while retaining prose and headings for leak detection."""
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            if re.fullmatch(r"\s*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                fence = None
            continue
        if match:
            fence = match.group(1)
            lines.append("")
        else:
            lines.append(line)
    return [p.strip() for p in re.split(r"\n\s*\n", "\n".join(lines)) if p.strip()]


def linguistic_text(text: str) -> str:
    text = TOKEN_RE.sub("", text)
    text = INLINE_MATH_RE.sub("", text)
    text = re.sub(r"`[^`\n]*`", "", text)
    text = re.sub(r"https?://\S+|[\w.+-]+@[\w.-]+\.\w+", "", text)
    return text


def translation_text(chunk: dict, src: str, dst: str) -> tuple[str, str, list[str]]:
    """Only explicit, exact source paragraphs can be exempted from language checks."""
    source_blocks, dest_blocks = prose_blocks(src), prose_blocks(dst)
    exemptions = set()
    errors = []
    entries = chunk.get("verbatim_paragraphs", [])
    if not isinstance(entries, list):
        return src, dst, ["verbatim_paragraphs 必须是含 text/reason 的列表"]
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
            errors.append("原文保留清单缺少 text")
            continue
        text = entry["text"].strip()
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            errors.append("原文保留清单缺少 reason")
        elif text not in source_blocks:
            errors.append("原文保留清单与源段落不完全匹配")
        elif dest_blocks.count(text) != source_blocks.count(text):
            errors.append("声明保留的原文段落缺失或被修改")
        else:
            exemptions.add(text)
    return (
        "\n\n".join(linguistic_text(p) for p in source_blocks if p not in exemptions),
        "\n\n".join(linguistic_text(p) for p in dest_blocks if p not in exemptions),
        errors,
    )


def paragraphs(text: str) -> int:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return len([b for b in blocks if not b.startswith("#")])


def mixed_paragraph_stats(text: str) -> tuple[int, int]:
    """只统计含中文的段落，避开作者单位、URL 这类刻意不翻译的内容。"""
    text = TOKEN_RE.sub("", text)
    text = re.sub(r"https?://\S+", "", text)
    paras = [p for p in re.split(r"\n\s*\n", text) if CJK_RE.search(p)]
    joined = "\n".join(paras)
    return len(re.findall(r"[A-Za-z]", joined)), len(CJK_RE.findall(joined))


def check_chunk(chunk: dict, src: str, dst: str) -> tuple[str, list[str]]:
    """返回 (状态, 问题列表)。状态: PASS / WARN / FAIL"""
    issues: list[str] = []
    fails = 0
    if not dst.strip():
        return "FAIL", ["译文为空"]
    language_src, language_dst, exemption_errors = translation_text(chunk, src, dst)
    issues.extend(exemption_errors)
    fails += len(exemption_errors)

    # 1. 占位符必须一字不差、顺序一致
    src_tokens = TOKEN_RE.findall(src)
    dst_tokens = TOKEN_RE.findall(dst)
    if src_tokens != dst_tokens:
        fails += 1
        missing = [t for t in src_tokens if t not in dst_tokens]
        extra = [t for t in dst_tokens if t not in src_tokens]
        detail = []
        if missing:
            detail.append(f"丢失 {missing[:4]}")
        if extra:
            detail.append(f"多出 {extra[:4]}")
        if not detail:
            detail.append("顺序不一致")
        issues.append("占位符不匹配：" + "，".join(detail))

    # 2. 标题数量
    src_h = len([l for l in src.split("\n") if l.strip().startswith("#")])
    dst_h = len([l for l in dst.split("\n") if l.strip().startswith("#")])
    if src_h != dst_h:
        fails += 1
        issues.append(f"标题数变化：{src_h} → {dst_h}")

    # 3. 比较完整内容及顺序，而不只是公式数量
    src_m = INLINE_MATH_RE.findall(src)
    dst_m = INLINE_MATH_RE.findall(dst)
    if src_m != dst_m:
        fails += 1
        issues.append(f"行内公式内容、数量或顺序变化：{len(src_m)} → {len(dst_m)}")

    # 4. 段落数量（允许少量合并/拆分）
    src_p, dst_p = paragraphs(src), paragraphs(dst)
    if src_p and not (0.75 <= dst_p / src_p <= 1.35):
        issues.append(f"段落数偏差较大：{src_p} → {dst_p}")

    # 5. 中英比例：英文词 → 中文字符，学术翻译经验值 0.4–2.4
    words = len(WORD_RE.findall(language_src))
    cjk = len(CJK_RE.findall(language_dst))
    if words > 30:
        ratio = cjk / words
        if ratio < 0.3:
            fails += 1
            issues.append(f"疑似未翻译：中文 {cjk} 字 / 英文 {words} 词（比值 {ratio:.2f}）")
        elif ratio > 2.6:
            issues.append(f"中文比例异常偏高：{ratio:.2f}（可能重复或扩写）")

    # 6. 独立检查每个段落，纯英文不能被其他段落的中文稀释
    source_normalized = {
        " ".join(p.split()) for p in re.split(r"\n\s*\n", language_src) if p.strip()
    }
    for index, para in enumerate(re.split(r"\n\s*\n", language_dst), 1):
        count = len(WORD_RE.findall(para))
        chinese = len(CJK_RE.findall(para))
        unchanged = " ".join(para.split()) in source_normalized
        if (count >= 6 and unchanged and chinese == 0) or (
            count >= 12 and chinese / count < 0.1
        ):
            fails += 1
            issues.append(f"第 {index} 段疑似漏译；若为作者/机构等保留内容，请在 manifest 的该块中登记原文及理由")

    latin, cjk_mixed = mixed_paragraph_stats(language_dst)
    if cjk_mixed and len(WORD_RE.findall(language_dst)) >= 12 and latin / cjk_mixed > 1.2:
        issues.append(f"英文残留较多：拉丁字母 {latin} vs 中文 {cjk_mixed}")

    status = "FAIL" if fails else ("WARN" if issues else "PASS")
    return status, issues


def validate_work(work: Path) -> dict:
    """Shared validation entrypoint; also used by build before any output is written."""
    manifest_path = work / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"找不到 {manifest_path}，请先运行 prepare.py")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = manifest["chunks"]

    rows: list[tuple[str, str, str]] = []
    missing: list[str] = []
    failed = 0
    if not chunks:
        raise ValueError("manifest 中没有文本块，不能作为完整译文交付")

    for ch in chunks:
        cid = ch["id"]
        src_path = work / ch["file"]
        dst_path = work / "translated" / f"{cid}.md"
        if not dst_path.exists():
            missing.append(cid)
            continue
        src = src_path.read_text(encoding="utf-8")
        dst = dst_path.read_text(encoding="utf-8")
        status, issues = check_chunk(ch, src, dst)
        if status == "FAIL":
            failed += 1
        rows.append((cid, status, "；".join(issues) if issues else "-"))
    return {"rows": rows, "missing": missing, "failed": failed, "total": len(chunks)}


def print_report(work: Path, report: dict) -> None:
    rows, missing, failed = report["rows"], report["missing"], report["failed"]
    print(f"工作目录: {work}")
    print(f"分块总数: {report['total']}   已翻译: {len(rows)}   缺失: {len(missing)}\n")

    width = max([len(r[0]) for r in rows] + [4])
    for cid, status, note in rows:
        mark = {"PASS": "✓", "WARN": "!", "FAIL": "×"}[status]
        print(f"  {mark} {cid.ljust(width)}  {note}")

    if missing:
        print(f"\n未翻译的块: {', '.join(missing)}")

    if failed or missing:
        print(f"\n结果: 需要处理 —— {failed} 块失败，{len(missing)} 块缺失")
        print("修复失败块后重新运行 check.py。")
    else:
        warns = len([r for r in rows if r[1] == "WARN"])
        print(f"\n结果: 硬性校验通过（{len(rows)} 块，{warns} 块有提醒；仍需语义与版面核对）")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("用法: python check.py <work-dir>")
    work = Path(sys.argv[1]).expanduser().resolve()
    try:
        report = validate_work(work)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(f"校验失败: {exc}")
    print_report(work, report)
    sys.exit(1 if report["failed"] or report["missing"] else 0)


if __name__ == "__main__":
    main()
