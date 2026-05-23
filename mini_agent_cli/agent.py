from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from anthropic import Anthropic

from .workspace import WorkspaceRuntime


def _tool_spec(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    """构造 Anthropic 工具定义。

    Args:
        name: 工具名，模型会在 `tool_use` 中使用这个名字。
        description: 工具用途说明，会进入模型上下文。
        properties: 输入参数 JSON Schema 的 `properties` 部分。
        required: 必填参数名列表。

    Returns:
        符合 Anthropic tools 格式的工具描述对象。
    """
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
    """从模型返回的 content block 中提取纯文本。"""
    parts: list[str] = []
    for block in content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    result = "".join(parts).strip()
    return result or "(没有文本输出)"


def _resolve_model(explicit: str | None = None) -> str:
    """解析运行时模型名。

    Args:
        explicit: 命令行显式传入的模型名，优先级最高。

    Returns:
        最终生效的模型名。

    Raises:
        RuntimeError: 当命令行和环境变量都没有提供模型名时抛出。
    """
    if explicit:
        return explicit

    for key in ("MODEL_ID", "ANTHROPIC_MODEL", "CLAUDE_MODEL"):
        value = os.getenv(key)
        if value:
            return value

    raise RuntimeError("未找到模型配置，请在 .env 中设置 MODEL_ID 或通过 --model 指定")


def _build_client() -> Anthropic:
    """创建 Anthropic 客户端。

    如果配置了 `ANTHROPIC_BASE_URL`，则切换到兼容接口；这种情况下不再
    依赖默认认证头，避免错误认证信息干扰请求。
    """
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    if base_url:
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        return Anthropic(base_url=base_url)
    return Anthropic()


@dataclass
class MiniAgent:
    """封装最小可运行的 coding agent。

    这个类把模型、工作区能力、工具注册和循环执行逻辑集中在一起，
    这样 CLI 入口只需要负责接收用户输入并调用它。

    Attributes:
        workspace: 当前工作区能力封装，负责文件和命令访问。
        model: 运行时使用的模型名。
        client: Anthropic API 客户端。
        max_tokens: 单次模型调用的最大输出长度。
        max_turns: 父代理的最大循环轮次。
        max_subagent_turns: 子代理的最大循环轮次。
        retry_count: 模型调用失败后的重试次数。
        retry_delay: 重试基础退避时间，单位秒。
        parent_tools: 父代理可用工具列表。
        child_tools: 子代理可用工具列表。
    """

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
        """在 dataclass 初始化后，构造父子代理的工具列表。"""
        self.parent_tools = self._build_parent_tools()
        self.child_tools = self._build_child_tools()

    def _build_base_tools(self) -> list[dict[str, Any]]:
        """构建父子代理共用的基础工具。

        这些工具提供最小闭环所需的基础能力：执行命令、读取文件、
        写入文件和编辑文件。
        """
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
        """构建待办工具。

        这个工具让模型自己维护多步骤任务的进度，而不是把计划写死在代码里。
        """
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
        """构建技能加载工具。

        这个工具按需把 `skills/` 里的 `SKILL.md` 展开给模型，避免把所有
        规则一次性塞进 prompt。
        """
        return _tool_spec(
            "load_skill",
            "按名称加载当前工作区 skills 目录下的 SKILL.md。",
            {"name": {"type": "string"}},
            ["name"],
        )

    def _build_task_tool(self) -> dict[str, Any]:
        """构建子代理派发工具。

        子代理用于处理独立的探索任务，能减少主上下文被无关细节污染。
        """
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
        """父代理工具集合：基础工具 + todo + skill + task。"""
        return self._build_base_tools() + [
            self._build_todo_tool(),
            self._build_load_skill_tool(),
            self._build_task_tool(),
        ]

    def _build_child_tools(self) -> list[dict[str, Any]]:
        """子代理工具集合：基础工具 + skill，不允许继续派发 task。"""
        return self._build_base_tools() + [self._build_load_skill_tool()] 

    def _parent_system_prompt(self) -> str:
        """生成父代理系统提示词。"""
        skills_text = self.workspace.skills.list_text()
        return (
            f"你是 mini Agent CLI，一个运行在 {self.workspace.root} 的编程助手。\n"
            "优先使用工具完成真实修改，不要把该做的事写成大段说明。\n"
            "多步骤任务先调用 todo 拆分并持续更新。需要独立探索时，使用 task 派生子代理。\n"
            "需要额外约束或工作规范时，按需调用 load_skill。\n\n"
            f"当前可用技能：\n{skills_text}"
        )

    def _child_system_prompt(self) -> str:
        """生成子代理系统提示词。"""
        skills_text = self.workspace.skills.list_text()
        return (
            f"你是 mini Agent CLI 的子代理，运行在 {self.workspace.root}。\n"
            "只处理当前子任务，完成后给出简短总结。\n"
            "你可以使用工具读取、修改和验证文件，也可以按需加载技能。\n\n"
            f"当前可用技能：\n{skills_text}"
        )

    def _base_dispatch(self) -> dict[str, Callable[[dict[str, Any]], str]]:
        """把工具名映射到本地处理函数。"""
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
        """调用 Anthropic 并带上简单重试。

        Args:
            messages: 当前对话历史，包含用户、助手和工具结果消息。
            system: 当前轮使用的系统提示词。
            tools: 当前轮可用的工具定义列表。

        Returns:
            Anthropic 返回的完整响应对象。

        Raises:
            RuntimeError: 多次重试后仍然调用失败时抛出。
        """
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
        """打印工具执行结果的简短预览。

        Args:
            name: 工具名。
            output: 工具执行结果。
            prefix: 子代理输出前缀，用于区分嵌套层级。
        """
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
        """运行一次完整的 agent 循环。

        Args:
            messages: 对话历史，工具结果会继续追加回这个列表。
            system_prompt: 当前角色使用的系统提示词。
            tools: 当前角色可用的工具集合。
            allow_task: 是否允许调用 `task` 工具。
            prefix: 打印日志前缀，子代理会用缩进区分输出。
            max_turns: 最大轮次数，避免模型持续调用工具导致死循环。

        Returns:
            模型最后一轮的文本输出；如果超过轮次限制，则返回提示字符串。
        """
        dispatch = self._base_dispatch()
        limit = max_turns or self.max_turns

        for _ in range(limit):
            response = self._call_llm(messages, system_prompt, tools)
            messages.append({"role": "assistant", "content": response.content})

            # 模型不再请求工具时，说明这一轮已经结束，返回最终文本。
            if response.stop_reason != "tool_use":
                return _extract_text(response.content)

            results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue

                # `task` 只允许父代理使用，子代理拿到后会直接报错。
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

            # 把工具结果回填给模型，进入下一轮推理。
            messages.append({"role": "user", "content": results})

        return "(已达到最大轮次限制)"

    def run_subagent(self, prompt: str) -> str:
        """运行子代理，用于处理独立子任务。

        Args:
            prompt: 发送给子代理的任务描述。

        Returns:
            子代理最终汇总出来的文本结果。
        """
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
        """运行父代理对话。

        Args:
            messages: 当前会话历史，通常由 CLI 入口维护。

        Returns:
            当前输入对应的最终模型文本结果。
        """
        return self._run_loop(
            messages,
            self._parent_system_prompt(),
            self.parent_tools,
            allow_task=True,
            prefix="",
            max_turns=self.max_turns,
        )


def build_agent(model: str | None = None, workdir: str | None = None) -> MiniAgent:
    """构建可直接用于 CLI 的 MiniAgent。

    Args:
        model: 显式指定的模型名；如果为空则从环境变量读取。
        workdir: 工作区目录；为空时使用当前进程目录。

    Returns:
        初始化完成的 `MiniAgent` 实例。
    """
    resolved_model = _resolve_model(model)
    workspace = WorkspaceRuntime(Path(workdir or os.getcwd()))
    return MiniAgent(workspace=workspace, model=resolved_model, client=_build_client())