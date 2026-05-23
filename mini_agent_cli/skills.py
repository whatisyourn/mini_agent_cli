from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    """单个技能文件的解析结果。"""

    name: str
    description: str
    body: str
    path: Path


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """解析简单的 YAML front matter。

    Args:
        text: `SKILL.md` 的完整文本。

    Returns:
        一个二元组:
        - meta: 解析出来的键值对，只支持 `key: value`
        - body: front matter 之后的正文
    """

    if not text.startswith("---\n"):
        return {}, text.strip()

    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text.strip()

    header = text[4:end]
    body = text[end + 5 :].strip()
    meta: dict[str, str] = {}

    for raw_line in header.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()

    return meta, body


class SkillLoader:
    """扫描并加载当前工作区下的技能文件。"""

    def __init__(self, skills_dir: Path):
        """初始化技能加载器。

        Args:
            skills_dir: 技能根目录。程序会递归搜索其中的 `SKILL.md`。
        """
        self.skills_dir = skills_dir
        self.skills: dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        """重新扫描技能目录，把磁盘上的内容同步到内存。"""
        self.skills.clear()

        if not self.skills_dir.exists():
            return

        for skill_path in sorted(self.skills_dir.rglob("SKILL.md")):
            text = skill_path.read_text(encoding="utf-8")
            meta, body = _parse_front_matter(text)
            name = meta.get("name") or skill_path.parent.name
            description = meta.get("description", "")
            self.skills[name] = Skill(
                name=name,
                description=description,
                body=body,
                path=skill_path,
            )

    def list_text(self) -> str:
        """返回可用技能列表，供 system prompt 或 `/skills` 命令展示。"""
        self.reload()

        if not self.skills:
            return "（暂无技能）"

        lines = []
        for name in sorted(self.skills):
            skill = self.skills[name]
            desc = f" - {skill.description}" if skill.description else ""
            lines.append(f"- {name}{desc}")
        return "\n".join(lines)

    def load(self, name: str) -> str:
        """按名称加载技能正文。

        Args:
            name: 技能名，对应 `SKILL.md` 里 front matter 的 `name` 字段。

        Returns:
            包裹在 `<skill>...</skill>` 中的技能内容；如果未找到则返回错误字符串。
        """
        self.reload()

        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(sorted(self.skills)) or "（空）"
            return f"Error: 未找到技能 '{name}'。可用技能: {available}"

        meta_lines = [f"name: {skill.name}"]
        if skill.description:
            meta_lines.append(f"description: {skill.description}")

        meta_block = "\n".join(meta_lines)
        return f"<skill>\n{meta_block}\n\n{skill.body.strip()}\n</skill>"