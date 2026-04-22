---
name: bro-fbombs
description: Count f-bombs and frustration markers in your AI session history and show a line chart over all time.
disable-model-invocation: true
---

Run the bundled script and relay its output verbatim:

    python3 scripts/count.py

The script walks `~/.claude/projects`, `~/.pi/agent/sessions`, and `~/.codex/sessions`, counts case-insensitive matches of an aggregated frustration pattern (`fuck*`, `wtf`, `wth`, `ffs`, `omfg`, `shit*`, `dumbass`, `horrible`, `awful`, `what the hell`) in user-authored text only, dedupes messages that appear in multiple files from session resume/fork, buckets by day from the first match through today, and prints a Braille line chart with stats and per-source breakdown. Uses `ripgrep` when available for a ~10x cold-run speedup; falls back to pure Python otherwise. Python 3.8+, no third-party Python deps. The output is the product — pass it through as-is.
