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

TOKEN_RE = re.compile(r"\[\[(?:EQ|FIG|TABLE):\d{3}\]\]")
INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


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

    # 3. 行内公式数量
    src_m = len(INLINE_MATH_RE.findall(src))
    dst_m = len(INLINE_MATH_RE.findall(dst))
    if src_m != dst_m:
        fails += 1
        issues.append(f"行内公式数变化：{src_m} → {dst_m}")

    # 4. 段落数量（允许少量合并/拆分）
    src_p, dst_p = paragraphs(src), paragraphs(dst)
    if src_p and not (0.75 <= dst_p / src_p <= 1.35):
        issues.append(f"段落数偏差较大：{src_p} → {dst_p}")

    # 5. 中英比例：英文词 → 中文字符，学术翻译经验值 0.4–2.4
    words = len(re.findall(r"[A-Za-z]{2,}", TOKEN_RE.sub("", src)))
    cjk = len(CJK_RE.findall(dst))
    if words > 30:
        ratio = cjk / words
        if ratio < 0.3:
            fails += 1
            issues.append(f"疑似未翻译：中文 {cjk} 字 / 英文 {words} 词（比值 {ratio:.2f}）")
        elif ratio > 2.6:
            issues.append(f"中文比例异常偏高：{ratio:.2f}（可能重复或扩写）")

    # 6. 大段残留英文（只看含中文的段落，忽略作者单位/URL）
    latin, cjk_mixed = mixed_paragraph_stats(dst)
    if cjk_mixed and latin / cjk_mixed > 1.2:
        issues.append(f"英文残留较多：拉丁字母 {latin} vs 中文 {cjk_mixed}")

    status = "FAIL" if fails else ("WARN" if issues else "PASS")
    return status, issues


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("用法: python check.py <work-dir>")

    work = Path(sys.argv[1]).expanduser().resolve()
    manifest_path = work / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"找不到 {manifest_path}，请先运行 prepare.py")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = manifest["chunks"]

    rows: list[tuple[str, str, str]] = []
    all_issues: list[str] = []
    missing: list[str] = []
    failed = 0

    for ch in chunks:
        cid = ch["id"]
        src_path = work / ch["file"]
        dst_path = work / "translated" / f"{cid}.md"
        if not dst_path.exists():
            missing.append(cid)
            continue
        src = src_path.read_text(encoding="utf-8", errors="replace")
        dst = dst_path.read_text(encoding="utf-8", errors="replace")
        status, issues = check_chunk(ch, src, dst)
        if status == "FAIL":
            failed += 1
        rows.append((cid, status, "；".join(issues) if issues else "-"))
        for issue in issues:
            all_issues.append(f"{cid}: {issue}")

    print(f"工作目录: {work}")
    print(f"分块总数: {len(chunks)}   已翻译: {len(rows)}   缺失: {len(missing)}\n")

    width = max([len(r[0]) for r in rows] + [4])
    for cid, status, note in rows:
        mark = {"PASS": "✓", "WARN": "!", "FAIL": "×"}[status]
        print(f"  {mark} {cid.ljust(width)}  {note}")

    if missing:
        print(f"\n未翻译的块: {', '.join(missing)}")

    if failed or missing:
        print(f"\n结果: 需要处理 —— {failed} 块失败，{len(missing)} 块缺失")
        print("修复失败块后重新运行 check.py。")
        sys.exit(1)

    warns = len([r for r in rows if r[1] == "WARN"])
    print(f"\n结果: 全部通过（{len(rows)} 块，{warns} 块有提醒）")
    print("下一步: python build.py <work-dir>")


if __name__ == "__main__":
    main()
