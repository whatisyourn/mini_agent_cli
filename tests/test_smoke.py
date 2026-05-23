from __future__ import annotations

import py_compile
import unittest
from pathlib import Path


class SmokeTests(unittest.TestCase):
    def test_full_agent_compiles(self) -> None:
        root = Path(__file__).resolve().parents[1]
        full_agent_path = root / "mini_agent_cli" / "full_agent.py"
        py_compile.compile(str(full_agent_path), doraise=True)

    def test_cli_module_compiles(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cli_path = root / "mini_agent_cli" / "cli.py"
        py_compile.compile(str(cli_path), doraise=True)


if __name__ == "__main__":
    unittest.main()