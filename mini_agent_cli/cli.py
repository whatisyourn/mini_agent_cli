from __future__ import annotations

import argparse
from typing import Any

from dotenv import load_dotenv


HELP_TEXT = """可用命令：
/help   显示帮助
/todo   查看当前待办
/skills 查看可用技能
/reset  清空会话历史
q / quit / exit 退出
"""


def _banner() -> None:
    """打印 CLI 的欢迎信息。"""
    print("mini Agent CLI")
    print("输入自然语言让模型工作。输入 /help 查看命令。\n")


def _print_help() -> None:
    """打印内置命令帮助。"""
    print(HELP_TEXT)


def _run_single_prompt(agent, prompt: str) -> str:
    """单次运行模式。

    Args:
        agent: 已构建好的 Agent 实例。
        prompt: 这次要让模型处理的一次性任务描述。

    Returns:
        模型最后输出的文本结果。
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    return agent.run_conversation(messages)


def _run_repl(agent) -> None:
    """交互式 REPL。

    Args:
        agent: 已构建好的 Agent 实例。
    """
    _banner()
    history: list[dict[str, Any]] = []

    while True:
        try:
            query = input("mini-agent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not query:
            continue

        lowered = query.lower()
        if lowered in {"q", "quit", "exit"}:
            break
        if query == "/help":
            _print_help()
            continue
        if query == "/todo":
            print(agent.workspace.todo.render())
            continue
        if query == "/skills":
            print(agent.workspace.skills.list_text())
            continue
        if query == "/reset":
            history.clear()
            print("会话历史已清空。")
            continue

        history.append({"role": "user", "content": query})

        try:
            result = agent.run_conversation(history)
        except Exception as exc:  # noqa: BLE001
            print(f"Error: {exc}")
            print()
            continue

        print(result)
        print()


def main(argv: list[str] | None = None) -> None:
    """CLI 入口。

    Args:
        argv: 传给 `argparse` 的参数列表；传 None 时使用 `sys.argv`。

    这个入口负责加载环境变量、解析命令行参数，然后启动一次性模式
    或交互式模式。
    """
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(prog="mini-agent", description="一个最小可运行的个人 Agent CLI")
    parser.add_argument("--model", help="覆盖 .env 中的模型名")
    parser.add_argument("--prompt", help="一次性运行的任务提示词")
    args = parser.parse_args(argv)

    # 这里做延迟导入，是为了让 `--help` 这种纯参数查询不需要提前初始化模型客户端。
    from .agent import build_agent

    agent = build_agent(model=args.model)

    if args.prompt:
        try:
            result = _run_single_prompt(agent, args.prompt)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"Error: {exc}") from exc
        print(result)
        return

    _run_repl(agent)