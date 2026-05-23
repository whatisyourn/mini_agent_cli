from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .skills import SkillLoader
from .todo import TodoManager


# 终端输出过长时直接截断，避免把窗口刷满。
MAX_OUTPUT_CHARS = 50_000
# Shell 命令的超时时间，防止某个命令永久阻塞。
MAX_SHELL_SECONDS = 120


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """把长文本裁剪到固定长度。

    Args:
        text: 原始文本。
        limit: 允许返回的最大字符数。

    Returns:
        被截断后的文本，长度不会超过 limit。
    """
    return text[:limit] if len(text) > limit else text


@dataclass
class WorkspaceRuntime:
    """封装工作区范围内的文件和命令能力。

    Args:
        root: 当前工作区根目录，所有文件操作都必须落在这里。
        todo: 由模型维护的待办对象。
        skills_dir: 技能目录；默认使用 root/skills。
    """

    root: Path
    todo: TodoManager = field(default_factory=TodoManager)
    skills_dir: Path | None = None
    skills: SkillLoader = field(init=False)

    def __post_init__(self) -> None:
        """标准化根目录并加载技能目录。"""
        self.root = self.root.resolve()
        resolved_skills_dir = self.skills_dir or (self.root / "skills")
        self.skills_dir = resolved_skills_dir.resolve()
        self.skills = SkillLoader(self.skills_dir)

    def safe_path(self, raw_path: str) -> Path:
        """把用户路径解析为工作区内的绝对路径。

        Args:
            raw_path: 用户传入的路径，允许相对路径或绝对路径。

        Returns:
            解析后的绝对路径，只会指向工作区内部。

        Raises:
            ValueError: 当路径试图越出工作区时抛出。
        """
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path

        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"路径越界: {raw_path}")
        return resolved

    def run_shell(self, command: str) -> str:
        """在当前工作区执行系统命令。

        Args:
            command: 传给 shell 的命令文本。

        Returns:
            命令的 stdout/stderr 合并结果；如果失败则返回错误字符串。
        """
        lowered = command.lower()
        # 这里不是完整安全策略，只做最小演示版的高风险命令拦截。
        blocked = [
            "rm -rf /",
            "sudo",
            "shutdown",
            "reboot",
            ":(){:|:&};:",
            "format ",
            "del /s",
            "remove-item -recurse",
        ]
        if any(token in lowered for token in blocked):
            return "Error: Dangerous command blocked"

        # Windows 优先走 PowerShell，其他平台优先走 bash/sh。
        if os.name == "nt":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if shell:
                args = [shell, "-NoLogo", "-NoProfile", "-Command", command]
            else:
                args = ["cmd", "/c", command]
        else:
            shell = shutil.which("bash") or shutil.which("sh")
            if shell:
                args = [shell, "-lc", command]
            else:
                args = ["sh", "-lc", command]

        try:
            result = subprocess.run(
                args,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=MAX_SHELL_SECONDS,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return f"Error: Timeout ({MAX_SHELL_SECONDS}s)"
        except OSError as exc:
            return f"Error: {exc}"

        output = (result.stdout + result.stderr).strip()
        if not output:
            output = "(no output)"
        return _clip(output)

    def run_read(self, path: str, limit: int | None = None) -> str:
        """读取工作区内的文件内容。

        Args:
            path: 要读取的文件路径。
            limit: 可选行数限制。传入后只返回前 limit 行。

        Returns:
            文件内容，或错误字符串。
        """
        try:
            text = self.safe_path(path).read_text(encoding="utf-8")
        except Exception as exc:
            return f"Error: {exc}"

        lines = text.splitlines()
        if limit is not None and 0 <= limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return _clip("\n".join(lines) or "(empty)")

    def run_write(self, path: str, content: str) -> str:
        """向工作区内写入文件。

        Args:
            path: 目标文件路径。
            content: 需要写入的文件内容。

        Returns:
            写入结果说明，或错误字符串。
        """
        try:
            target = self.safe_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as exc:
            return f"Error: {exc}"

    def run_edit(self, path: str, old_text: str, new_text: str) -> str:
        """把文件中的第一处匹配文本替换为新文本。

        Args:
            path: 目标文件路径。
            old_text: 需要被替换的旧文本。
            new_text: 替换后的新文本。

        Returns:
            编辑结果说明，或错误字符串。
        """
        try:
            target = self.safe_path(path)
            content = target.read_text(encoding="utf-8")
            if old_text not in content:
                return f"Error: Text not found in {path}"
            target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return f"Edited {path}"
        except Exception as exc:
            return f"Error: {exc}"