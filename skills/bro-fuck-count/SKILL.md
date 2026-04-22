---
name: bro-fuck-count
description: Count f-bombs in your AI session history and show a line chart over all time.
disable-model-invocation: true
---

Run the bundled script and relay its output verbatim:

    python3 scripts/count.py

The script walks `~/.claude/projects`, `~/.pi/agent/sessions`, and `~/.codex/sessions`, matches case-insensitive `fuck` in user-authored text only (not tool results, not assistant output), buckets by day from the first occurrence through today, and prints a Braille line chart with stats and per-source breakdown. Python 3.8+, no third-party deps. The output is the product — pass it through as-is.
