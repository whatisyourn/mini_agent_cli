# mini Agent CLI

A compact personal coding agent CLI.

It keeps the minimum working harness loop:

- `shell` to run commands in the current workspace
- `read_file`, `write_file`, `edit_file` for file operations
- `todo` for model-owned task tracking
- `task` for spawning a subagent on an isolated subtask
- `load_skill` for loading `./skills/**/SKILL.md` on demand

## Quick start

```bash
cd mini-agent-cli
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env
```

Set your API key and model in `.env`:

```bash
ANTHROPIC_API_KEY=...
MODEL_ID=claude-3-5-sonnet-latest
```

Run the CLI:

```bash
mini-agent
```

Or run a one-shot prompt:

```bash
mini-agent --prompt "Inspect the current repository and suggest the next refactor step."
```

## Commands

- `/help` show help
- `/todo` show current todo list
- `/skills` show available skills
- `/reset` clear chat history
- `q`, `quit`, `exit` leave the session

## Project layout

```text
mini-agent-cli/
  mini_agent_cli/
    agent.py
    cli.py
    skills.py
    todo.py
    workspace.py
  skills/
    repo-iteration/
      SKILL.md
  tests/
```

## License

MIT