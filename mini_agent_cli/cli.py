from __future__ import annotations

import argparse
import builtins
import os
import runpy
from pathlib import Path

from dotenv import load_dotenv


FULL_AGENT_PATH = Path(__file__).with_name("full_agent.py")


def _run_full_agent(prompt: str | None = None) -> None:
    """运行全量版 agent 脚本。

    Args:
        prompt: 可选的一次性输入内容。传入后会模拟用户先输入 prompt，
            再输入 q 退出，用于单次演示或快速验证。
    """
    if prompt is None:
        runpy.run_path(str(FULL_AGENT_PATH), run_name="__main__")
        return

    inputs = iter([prompt, "q"])
    original_input = builtins.input

    def fake_input(*args, **kwargs):  # noqa: ANN001, ANN003
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError from None

    builtins.input = fake_input
    try:
        runpy.run_path(str(FULL_AGENT_PATH), run_name="__main__")
    finally:
        builtins.input = original_input


def main(argv: list[str] | None = None) -> None:
    """CLI 入口。

    Args:
        argv: 传给 argparse 的参数列表；传 None 时使用 sys.argv。
    """
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        prog="mini-agent",
        description="mini Agent CLI - full comprehensive harness",
    )
    parser.add_argument("--model", help="在启动全量引擎前覆盖 MODEL_ID")
    parser.add_argument("--prompt", help="单次运行一个 prompt 后退出")
    args = parser.parse_args(argv)

    if args.model:
        os.environ["MODEL_ID"] = args.model

    _run_full_agent(prompt=args.prompt)