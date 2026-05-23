from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


VALID_TODO_STATUSES = {"pending", "in_progress", "completed"}


@dataclass
class TodoManager:
    """维护模型自己写入的待办状态。"""

    items: list[dict[str, str]] = field(default_factory=list)

    def update(self, items: list[dict[str, Any]]) -> str:
        if len(items) > 20:
            raise ValueError("最多只能维护 20 条待办")

        validated: list[dict[str, str]] = []
        in_progress_count = 0

        for index, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).strip().lower()
            todo_id = str(item.get("id", index + 1)).strip() or str(index + 1)

            if not text:
                raise ValueError(f"第 {todo_id} 条待办缺少 text")
            if status not in VALID_TODO_STATUSES:
                raise ValueError(f"第 {todo_id} 条待办状态非法: {status}")
            if status == "in_progress":
                in_progress_count += 1

            validated.append({"id": todo_id, "text": text, "status": status})

        if in_progress_count > 1:
            raise ValueError("同一时间只能有一条 in_progress")

        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "暂无待办。"

        markers = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
        }

        lines: list[str] = []
        for item in self.items:
            marker = markers.get(item["status"], "[?]")
            lines.append(f"{marker} #{item['id']}: {item['text']}")

        completed = sum(1 for item in self.items if item["status"] == "completed")
        lines.append(f"({completed}/{len(self.items)} completed)")
        return "\n".join(lines)