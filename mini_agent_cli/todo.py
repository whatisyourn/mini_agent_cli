from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 待办状态只允许这三种，避免模型写入不可识别的值。
VALID_TODO_STATUSES = {"pending", "in_progress", "completed"}


@dataclass
class TodoManager:
    """模型维护的待办清单。

    这个类不负责生成计划，只负责接收模型写入的状态、校验它们，
    再把当前进度渲染成适合终端查看的文本。
    """

    items: list[dict[str, str]] = field(default_factory=list)

    def update(self, items: list[dict[str, Any]]) -> str:
        """用新的待办列表覆盖当前状态。

        Args:
            items: 待办项数组。每个元素至少应包含:
                - text: 待办内容
                - status: pending / in_progress / completed
                - id: 可选标识，不传时按顺序自动生成

        Returns:
            当前待办清单的渲染文本。

        Raises:
            ValueError: 当条目数量、字段内容或状态值不合法时抛出。
        """
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
        """把当前待办状态渲染成可直接打印的文本。"""
        if not self.items:
            return "暂无待办。"

        # 用符号展示状态，比纯文字更容易在终端里扫描。
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