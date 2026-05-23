from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mini_agent_cli.skills import SkillLoader
from mini_agent_cli.todo import TodoManager
from mini_agent_cli.workspace import WorkspaceRuntime


class SmokeTests(unittest.TestCase):
    def test_workspace_file_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = WorkspaceRuntime(root)

            write_result = workspace.run_write("demo.txt", "hello")
            self.assertIn("Wrote", write_result)

            self.assertEqual(workspace.run_read("demo.txt"), "hello")
            self.assertEqual(workspace.run_edit("demo.txt", "hello", "world"), "Edited demo.txt")
            self.assertEqual(workspace.run_read("demo.txt"), "world")

    def test_safe_path_blocks_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceRuntime(Path(tmp))
            with self.assertRaises(ValueError):
                workspace.safe_path("../escape.txt")

    def test_todo_manager_renders(self) -> None:
        todo = TodoManager()
        output = todo.update([
            {"id": "1", "text": "梳理目录", "status": "pending"},
            {"id": "2", "text": "实现入口", "status": "in_progress"},
        ])
        self.assertIn("[>] #2: 实现入口", output)

    def test_skill_loader_reads_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "demo"
            skill_dir.mkdir(parents=True)
            skill_dir.joinpath("SKILL.md").write_text(
                "---\nname: demo\ndescription: 测试技能\n---\n\n请优先做最小改动。\n",
                encoding="utf-8",
            )

            loader = SkillLoader(root / "skills")
            self.assertIn("demo", loader.list_text())
            skill_text = loader.load("demo")
            self.assertIn("请优先做最小改动。", skill_text)


if __name__ == "__main__":
    unittest.main()