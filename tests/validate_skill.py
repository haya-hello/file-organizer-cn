"""验证 Skill 包的基本结构。 / Validate the basic Skill package structure."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "file-organizer-cn"
REQUIRED = [
    SKILL_DIR / "SKILL.md",
    SKILL_DIR / "agents" / "openai.yaml",
    SKILL_DIR / "scripts" / "file_organizer.py",
    SKILL_DIR / "references" / "quickstart-cn.md",
    SKILL_DIR / "references" / "rules-cn.md",
]


def main() -> int:
    """执行轻量、无依赖验证。 / Run lightweight dependency-free checks."""
    errors: list[str] = []
    for path in REQUIRED:
        if not path.is_file():
            errors.append(f"缺少文件：{path.relative_to(ROOT)}")

    skill_path = SKILL_DIR / "SKILL.md"
    if skill_path.is_file():
        content = skill_path.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
        if not match:
            errors.append("SKILL.md 缺少有效 YAML frontmatter")
        else:
            frontmatter = match.group(1)
            if "name: file-organizer-cn" not in frontmatter:
                errors.append("SKILL.md 的 name 不正确")
            if "description:" not in frontmatter:
                errors.append("SKILL.md 缺少 description")
        for relative in ("references/quickstart-cn.md", "references/rules-cn.md"):
            if f"]({relative})" not in content:
                errors.append(f"SKILL.md 未引用 {relative}")

    script_path = SKILL_DIR / "scripts" / "file_organizer.py"
    if script_path.is_file():
        source = script_path.read_text(encoding="utf-8")
        compile(source, str(script_path), "exec")
        for required_text in ("--confirm", "preview", "undo", "overwrites_files"):
            if required_text not in source:
                errors.append(f"脚本缺少安全能力标记：{required_text}")

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: Skill 结构、引用和安全能力检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
