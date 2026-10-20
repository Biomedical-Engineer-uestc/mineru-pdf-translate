"""路径解析：让脚本在任何机器上都能找到 MinerU / pandoc / Edge。

查找顺序：
1. 环境变量（MINERU_KIT / PANDOC_EXE / EDGE_EXE）
2. 技能目录下的 config.json（由 setup.ps1 生成）
3. 系统 PATH
4. 默认安装位置
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"
INSTALL_DIR = Path.home() / ".pdf-translate"


def _from_config(key: str) -> str | None:
    if not CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    value = data.get(key)
    return str(value) if value else None


def _first_existing(candidates: list[Path | None]) -> Path | None:
    for c in candidates:
        if c and Path(c).exists():
            return Path(c)
    return None


def find_mineru_kit() -> Path | None:
    env = os.environ.get("MINERU_KIT")
    cfg = _from_config("mineru_kit")
    which = shutil.which("mineru-kit")
    exe = "mineru-kit.exe" if os.name == "nt" else "mineru-kit"
    return _first_existing([
        env,
        cfg,
        which,
        INSTALL_DIR / ".venv" / "Scripts" / exe,
        INSTALL_DIR / ".venv" / "bin" / exe,
    ])


def find_pandoc() -> Path | None:
    env = os.environ.get("PANDOC_EXE")
    cfg = _from_config("pandoc")
    which = shutil.which("pandoc")
    base = INSTALL_DIR / "tools" / "pandoc"
    bundled = sorted(base.glob("pandoc-*/pandoc.exe"), reverse=True) if base.exists() else []
    return _first_existing([
        env,
        cfg,
        which,
        *bundled,
        base / "pandoc.exe",
    ])


def find_edge() -> Path | None:
    env = os.environ.get("EDGE_EXE")
    cfg = _from_config("edge")
    return _first_existing([
        env,
        cfg,
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ])


def python_exe() -> str:
    """当前解释器；如果没有就用安装目录里的。"""
    if sys.executable:
        return sys.executable
    exe = INSTALL_DIR / ".venv" / "Scripts" / "python.exe"
    return str(exe)
