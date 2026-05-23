# mini Agent CLI

A full comprehensive coding agent CLI, reconstructed from `learn-claude-code-main`.

This repository runs the complete `s20` harness runtime as the default entry point. It includes the major agent mechanisms from the source project:

- agent loop and tool dispatch
- todo tracking
- subagents
- skill loading
- context compaction
- memory persistence
- hooks
- permission checks
- error recovery
- background tasks
- cron scheduling
- team messaging and autonomous teammates
- worktree isolation
- MCP tool routing

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

Run the full agent:

```bash
mini-agent
```

You can also pass a one-shot prompt:

```bash
mini-agent --prompt "Inspect the current repository and summarize the structure."
```

## Notes

- The default runtime is the full engine in `mini_agent_cli/full_agent.py`.
- The full runtime expects `git` on the PATH for the worktree and task features.

## License

MIT