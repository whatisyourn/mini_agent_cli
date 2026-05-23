from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .skills import SkillLoader
from .todo import TodoManager


MAX_OUTPUT_CHARS = 50_000
MAX_SHELL_SECONDS = 120


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    return text[:limit] if len(text) > limit else text


@dataclass
class WorkspaceRuntime:
    """封装工作区范围内的文件和命令能力。"""

    root: Path
    todo: TodoManager = field(default_factory=TodoManager)
    skills_dir: Path | None = None
    skills: SkillLoader = field(init=False)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        resolved_skills_dir = self.skills_dir or (self.root / "skills")
        self.skills_dir = resolved_skills_dir.resolve()
        self.skills = SkillLoader(self.skills_dir)

    def safe_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path

        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"路径越界: {raw_path}")
        return resolved

    def run_shell(self, command: str) -> str:
        lowered = command.lower()
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
        try:
            text = self.safe_path(path).read_text(encoding="utf-8")
        except Exception as exc:
            return f"Error: {exc}"

        lines = text.splitlines()
        if limit is not None and 0 <= limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return _clip("\n".join(lines) or "(empty)")

    def run_write(self, path: str, content: str) -> str:
        try:
            target = self.safe_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as exc:
            return f"Error: {exc}"

    def run_edit(self, path: str, old_text: str, new_text: str) -> str:
        try:
            target = self.safe_path(path)
            content = target.read_text(encoding="utf-8")
            if old_text not in content:
                return f"Error: Text not found in {path}"
            target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return f"Edited {path}"
        except Exception as exc:
            return f"Error: {exc}"