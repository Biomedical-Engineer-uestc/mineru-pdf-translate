"""把本仓库（一个 ZCode skill）打包成 ZCode 插件。

产物:
    dist/pdf-translate/           插件目录（可直接作为本地 marketplace 源）
    dist/pdf-translate-plugin.zip 可分发的插件压缩包
    dist/marketplace.json         本地测试用 marketplace 清单

用法:
    python build_plugin.py [--version 1.0.1]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
PLUGIN_NAME = "pdf-translate"
COPY_ITEMS = ["SKILL.md", "README.md", "LICENSE", "NOTICE", "setup.bat", "setup.ps1",
              "scripts", "tests", "vendor"]

PLUGIN_JSON = {
    "name": PLUGIN_NAME,
    "version": "0.0.0",
    "description": "用 MinerU 提取论文，翻译文字、校验公式和漏译，并生成重新排版的中文 PDF。",
    "description_i18n": {
        "en": "Translate English PDF papers into typeset Chinese PDFs with MinerU. "
              "Translate extracted text, validate content, and preserve figures and formulas.",
        "zh-CN": "用 MinerU 把英文 PDF 论文翻译成中文 PDF。图片、公式、表格走占位符，"
                 "翻译阶段处理文字，验收阶段核对页面。",
    },
    "author": {"name": "Biomedical-Engineer-uestc"},
    "license": "MIT",
    "skills": "./skills",
    "keywords": ["pdf", "translation", "mineru", "academic", "chinese", "token-saving"],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(version: str) -> None:
    # Verify the recursive deletion target before rebuilding generated output.
    resolved_dist = DIST.resolve()
    if resolved_dist.parent != ROOT.resolve() or resolved_dist.name != "dist":
        raise ValueError(f"Unsafe distribution target: {resolved_dist}")
    if DIST.exists():
        shutil.rmtree(resolved_dist)
    plugin_dir = DIST / PLUGIN_NAME
    skill_dir = plugin_dir / "skills" / PLUGIN_NAME
    skill_dir.mkdir(parents=True)

    for item in COPY_ITEMS:
        src = ROOT / item
        if not src.exists():
            continue
        dst = skill_dir / item
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst)

    manifest = dict(PLUGIN_JSON)
    manifest["version"] = version
    (plugin_dir / ".zcode-plugin").mkdir()
    (plugin_dir / ".zcode-plugin" / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    zip_path = DIST / f"{PLUGIN_NAME}-plugin.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(plugin_dir.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(DIST).as_posix())

    marketplace = {
        "name": f"dev-{PLUGIN_NAME}",
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": f"./{PLUGIN_NAME}",
                "version": version,
                "description": manifest["description"],
                "displayName": "PDF 论文翻译",
                "displayName_i18n": {"zh-CN": "PDF 论文翻译", "en": "PDF Paper Translator"},
                "description_i18n": manifest["description_i18n"],
                "category": "productivity",
                "keywords": manifest["keywords"],
            }
        ],
    }
    (DIST / "marketplace.json").write_text(
        json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"插件目录 : {plugin_dir}")
    print(f"压缩包   : {zip_path}  ({zip_path.stat().st_size/1048576:.1f} MB)")
    print(f"SHA256   : {sha256(zip_path)}")
    print(f"市场清单 : {DIST / 'marketplace.json'}")
    print()
    print("本地试用：在应用里打开 插件市场 → 添加 → 添加插件市场，粘贴：")
    print(f"  {DIST}")


def main() -> None:
    ap = argparse.ArgumentParser(description="打包 ZCode 插件")
    ap.add_argument("--version", default="1.0.1")
    args = ap.parse_args()
    build(args.version)


if __name__ == "__main__":
    main()
