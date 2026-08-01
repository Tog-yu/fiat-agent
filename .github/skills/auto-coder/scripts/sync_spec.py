#!/usr/bin/env python3
"""
Spec Sync — splits fiat-agent/DEV_SPEC.md into chapter files under
.github/skills/auto-coder/references/.

The fiat-agent DEV_SPEC is organized as 13 top-level chapters
("## 1. 项目概述" ... "## 13. 后续扩展"). Each chapter is written to a
stable, English-slugged file so the auto-coder can load only what it
needs (progressive disclosure). A sha256 hash of DEV_SPEC.md gates the
sync so unchanged specs are not re-written.

Usage:
    python scripts/sync_spec.py [--force]
"""

import hashlib
import re
import sys
from pathlib import Path
from typing import List, NamedTuple


class Chapter(NamedTuple):
    number: int
    cn_title: str
    filename: str
    start_line: int
    end_line: int
    line_count: int


# Maps the 13 DEV_SPEC top-level chapter numbers to stable English slugs.
# Keep this in sync with DEV_SPEC section numbering.
NUMBER_SLUG_MAP = {
    1: "overview",        # 项目概述
    2: "principles",      # 设计原则
    3: "tech-stack",      # 技术选型
    4: "architecture",    # 系统架构
    5: "directory",       # 目录结构
    6: "modules",         # 模块说明
    7: "data-flow",       # 数据流说明
    8: "config",          # 配置设计
    9: "testing",         # 测试方案
    10: "schedule",       # 项目排期
    11: "tasks",          # 分阶段任务清单
    12: "milestones",     # 交付里程碑
    13: "future",         # 后续扩展
}


def _slug(chapter_num: int, title: str) -> str:
    if chapter_num in NUMBER_SLUG_MAP:
        return NUMBER_SLUG_MAP[chapter_num]
    # Fallback: sanitize whatever title text we have (ASCII-only).
    clean = re.sub(r'[^\w]+', '-', title, flags=re.ASCII).strip('-').lower()
    return clean or f"chapter-{chapter_num}"


def detect_chapters(content: str) -> List[Chapter]:
    lines = content.split('\n')
    starts: List[tuple] = []
    for i, line in enumerate(lines):
        m = re.match(r'^## (\d+)\.\s+(.+)$', line)
        if m:
            starts.append((int(m.group(1)), m.group(2).strip(), i))
    if not starts:
        raise ValueError("No chapters found. Expected '## N. Title'")
    chapters = []
    for idx, (num, title, start) in enumerate(starts):
        end = starts[idx + 1][2] if idx + 1 < len(starts) else len(lines)
        chapters.append(Chapter(num, title, f"{num:02d}-{_slug(num, title)}.md", start, end, end - start))
    return chapters


def sync(force: bool = False):
    skill_dir = Path(__file__).parent.parent          # auto-coder/
    repo_root = skill_dir.parent.parent.parent        # project root
    dev_spec  = repo_root / "DEV_SPEC.md"
    specs_dir = skill_dir / "references"
    hash_file = skill_dir / ".spec_hash"

    if not dev_spec.exists():
        print(f"ERROR: {dev_spec} not found (expected DEV_SPEC.md at repo root)")
        sys.exit(1)

    # Hash check
    current_hash = hashlib.sha256(dev_spec.read_bytes()).hexdigest()
    if not force and hash_file.exists() and hash_file.read_text().strip() == current_hash:
        print("specs up-to-date")
        return

    content = dev_spec.read_text(encoding='utf-8')
    chapters = detect_chapters(content)
    lines = content.split('\n')

    specs_dir.mkdir(parents=True, exist_ok=True)

    # Clean orphans no longer produced by the current spec.
    old = {f.name for f in specs_dir.glob("*.md")}
    new = {ch.filename for ch in chapters}
    for f in old - new:
        (specs_dir / f).unlink()

    # Write chapters
    for ch in chapters:
        (specs_dir / ch.filename).write_text('\n'.join(lines[ch.start_line:ch.end_line]), encoding='utf-8')

    hash_file.write_text(current_hash)
    print(f"synced {len(chapters)} chapters")


if __name__ == "__main__":
    sync(force="--force" in sys.argv)
