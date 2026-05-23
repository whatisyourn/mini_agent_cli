from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from anthropic import Anthropic

from .workspace import WorkspaceRuntime


def _tool_spec(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def _extract_text(content: Any) -> str:
    parts: list[str] = []
    for block in content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    result = "".join(parts).strip()
    return result or "(没有文本输出)"


def _resolve_model(explicit: str | None = None) -> str:
    if explicit:
        return explicit

    for key in ("MODEL_ID", "ANTHROPIC_MODEL", "CLAUDE_MODEL"):
        value = os.getenv(key)
        if value:
            return value

    raise RuntimeError("未找到模型配置，请在 .env 中设置 MODEL_ID 或通过 --model 指定")


def _build_client() -> Anthropic:
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    if base_url:
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        return Anthropic(base_url=base_url)
    return Anthropic()


@dataclass
class MiniAgent:
    """封装最小可运行的 coding agent。"""

    workspace: WorkspaceRuntime
    model: str
    client: Anthropic
    max_tokens: int = 8_000
    max_turns: int = 50
    max_subagent_turns: int = 30
    retry_count: int = 3
    retry_delay: float = 0.5
    parent_tools: list[dict[str, Any]] = field(init=False)
    child_tools: list[dict[str, Any]] = field(init=False)

    def __post_init__(self) -> None:
        self.parent_tools = self._build_parent_tools()
        self.child_tools = self._build_child_tools()

    def _build_base_tools(self) -> list[dict[str, Any]]:
        return [
            _tool_spec(
                "shell",
                "在当前工作区执行系统命令。Windows 上映射到 PowerShell，其他平台使用 bash。",
                {"command": {"type": "string"}},
                ["command"],
            ),
            _tool_spec(
                "read_file",
                "读取当前工作区内的文件内容。",
                {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                ["path"],
            ),
            _tool_spec(
                "write_file",
                "向当前工作区内写入文件。",
                {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                ["path", "content"],
            ),
            _tool_spec(
                "edit_file",
                "把文件中的第一处旧文本替换为新文本。",
                {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                ["path", "old_text", "new_text"],
            ),
        ]

    def _build_todo_tool(self) -> dict[str, Any]:
        return _tool_spec(
            "todo",
            "维护多步骤任务清单，最多 20 条，且同一时间只能有一条 in_progress。",
            {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                        },
                        "required": ["text", "status"],
                    },
                }
            },
            ["items"],
        )

    def _build_load_skill_tool(self) -> dict[str, Any]:
        return _tool_spec(
            "load_skill",
            "按名称加载当前工作区 skills 目录下的 SKILL.md。",
            {"name": {"type": "string"}},
            ["name"],
        )

    def _build_task_tool(self) -> dict[str, Any]:
        return _tool_spec(
            "task",
            "派生一个子代理处理独立子问题。子代理拥有新上下文，但共享文件系统。",
            {
                "prompt": {"type": "string"},
                "description": {"type": "string"},
            },
            ["prompt"],
        )

    def _build_parent_tools(self) -> list[dict[str, Any]]:
        return self._build_base_tools() + [
            self._build_todo_tool(),
            self._build_load_skill_tool(),
            self._build_task_tool(),
        ]

    def _build_child_tools(self) -> list[dict[str, Any]]:
        return self._build_base_tools() + [self._build_load_skill_tool()]

    def _parent_system_prompt(self) -> str:
        skills_text = self.workspace.skills.list_text()
        return (
            f"你是 mini Agent CLI，一个运行在 {self.workspace.root} 的编程助手。\n"
            "优先使用工具完成真实修改，不要把该做的事写成大段说明。\n"
            "多步骤任务先调用 todo 拆分并持续更新。需要独立探索时，使用 task 派生子代理。\n"
            "需要额外约束或工作规范时，按需调用 load_skill。\n\n"
            f"当前可用技能：\n{skills_text}"
        )

    def _child_system_prompt(self) -> str:
        skills_text = self.workspace.skills.list_text()
        return (
            f"你是 mini Agent CLI 的子代理，运行在 {self.workspace.root}。\n"
            "只处理当前子任务，完成后给出简短总结。\n"
            "你可以使用工具读取、修改和验证文件，也可以按需加载技能。\n\n"
            f"当前可用技能：\n{skills_text}"
        )

    def _base_dispatch(self) -> dict[str, Callable[[dict[str, Any]], str]]:
        return {
            "shell": lambda payload: self.workspace.run_shell(payload["command"]),
            "read_file": lambda payload: self.workspace.run_read(
                payload["path"], payload.get("limit")
            ),
            "write_file": lambda payload: self.workspace.run_write(
                payload["path"], payload["content"]
            ),
            "edit_file": lambda payload: self.workspace.run_edit(
                payload["path"], payload["old_text"], payload["new_text"]
            ),
            "load_skill": lambda payload: self.workspace.skills.load(payload["name"]),
            "todo": lambda payload: self.workspace.todo.update(payload["items"]),
        }

    def _call_llm(self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]]):
        last_error: Exception | None = None
        for attempt in range(1, self.retry_count + 1):
            try:
                return self.client.messages.create(
                    model=self.model,
                    system=system,
                    messages=messages,
                    tools=tools,
                    max_tokens=self.max_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.retry_count:
                    break
                time.sleep(self.retry_delay * (2 ** (attempt - 1)))

        raise RuntimeError(f"LLM 调用失败: {last_error}") from last_error

    def _print_tool_result(self, name: str, output: str, prefix: str = "") -> None:
        preview = output if len(output) <= 200 else output[:200] + "..."
        print(f"{prefix}[{name}] {preview}")

    def _run_loop(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        *,
        allow_task: bool,
        prefix: str = "",
        max_turns: int | None = None,
    ) -> str:
        dispatch = self._base_dispatch()
        limit = max_turns or self.max_turns

        for _ in range(limit):
            response = self._call_llm(messages, system_prompt, tools)
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return _extract_text(response.content)

            results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue

                if block.name == "task":
                    if not allow_task:
                        output = "Error: 子代理不支持 task 工具"
                    else:
                        desc = block.input.get("description", "subtask")
                        prompt = block.input.get("prompt", "")
                        print(f"{prefix}[task] {desc}: {prompt[:80]}")
                        output = self.run_subagent(prompt)
                else:
                    handler = dispatch.get(block.name)
                    output = handler(block.input) if handler else f"Error: 未知工具 {block.name}"

                self._print_tool_result(block.name, str(output), prefix=prefix)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    }
                )

            messages.append({"role": "user", "content": results})

        return "(已达到最大轮次限制)"

    def run_subagent(self, prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self._run_loop(
            messages,
            self._child_system_prompt(),
            self.child_tools,
            allow_task=False,
            prefix="  ",
            max_turns=self.max_subagent_turns,
        )

    def run_conversation(self, messages: list[dict[str, Any]]) -> str:
        return self._run_loop(
            messages,
            self._parent_system_prompt(),
            self.parent_tools,
            allow_task=True,
            prefix="",
            max_turns=self.max_turns,
        )


def build_agent(model: str | None = None, workdir: str | None = None) -> MiniAgent:
    resolved_model = _resolve_model(model)
    workspace = WorkspaceRuntime(Path(workdir or os.getcwd()))
    return MiniAgent(workspace=workspace, model=resolved_model, client=_build_client())