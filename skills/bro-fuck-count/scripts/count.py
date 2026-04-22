#!/usr/bin/env python3
"""
bro-fuck-count: tally case-insensitive 'fuck' occurrences across your AI
session history and print a Braille line chart over all time.

Walks three session stores:
  ~/.claude/projects/**/*.jsonl   (Claude Code)
  ~/.pi/agent/sessions/**/*.jsonl (Pi)
  ~/.codex/sessions/**/*.jsonl    (Codex)

Only counts text authored by the user (role == "user"), skipping
tool_result echoes and assistant output. Dedups messages across
resumed/forked sessions by their stable message id so the same message
isn't counted twice. Buckets by day, extends the range from
first-fuck to today so quiet weeks show as gaps.

Fast path: per-file and per-line byte prefilter skips anything that
doesn't contain 'fuck' at all without parsing JSON.

No third-party deps. Python 3.8+.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

FUCK_RE = re.compile(r"fuck", re.IGNORECASE)
FUCK_RE_B = re.compile(rb"fuck", re.IGNORECASE)

CACHE_PATH = Path.home() / ".cache" / "bro-fuck-count" / "cache.json"
CACHE_VERSION = 1


# ---------- per-source extractors ----------
# Each yields (dedup_key, timestamp_str, text) for every user-authored
# text fragment in a line. dedup_key must be stable across session
# resume/fork so the same logical message dedupes out.

def _extract_claude(obj):
    if obj.get("type") != "user":
        return
    msg = obj.get("message") or {}
    if msg.get("role") != "user":
        return
    uuid = obj.get("uuid")
    if not uuid:
        return
    ts = obj.get("timestamp")
    content = msg.get("content")
    if isinstance(content, str):
        yield uuid, ts, content
    elif isinstance(content, list):
        for idx, item in enumerate(content):
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text") or ""
                if t:
                    # Qualify key with part index so multi-part messages
                    # still dedup cleanly without collapsing distinct parts.
                    yield f"{uuid}#{idx}", ts, t


def _extract_pi(obj):
    if obj.get("type") != "message":
        return
    msg = obj.get("message") or {}
    if msg.get("role") != "user":
        return
    mid = obj.get("id")
    if not mid:
        return
    ts = obj.get("timestamp")
    content = msg.get("content") or []
    if isinstance(content, list):
        for idx, item in enumerate(content):
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text") or ""
                if t:
                    yield f"{mid}#{idx}", ts, t


def _extract_codex(obj):
    if obj.get("type") != "response_item":
        return
    payload = obj.get("payload") or {}
    if payload.get("type") != "message" or payload.get("role") != "user":
        return
    ts = obj.get("timestamp")
    content = payload.get("content") or []
    if isinstance(content, list):
        for idx, item in enumerate(content):
            if isinstance(item, dict) and item.get("type") == "input_text":
                t = item.get("text") or ""
                if t:
                    # Codex lines have no stable id; use (ts, content hash).
                    h = hashlib.sha1(t.encode("utf-8", "replace")).hexdigest()[:16]
                    yield f"{ts}-{h}#{idx}", ts, t


SOURCES = [
    ("claude", Path.home() / ".claude" / "projects",       _extract_claude),
    ("pi",     Path.home() / ".pi" / "agent" / "sessions", _extract_pi),
    ("codex",  Path.home() / ".codex" / "sessions",        _extract_codex),
]


def _parse_date(ts):
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).date()
    except Exception:
        return None


def _load_cache():
    if not CACHE_PATH.exists():
        return {}
    try:
        obj = json.loads(CACHE_PATH.read_text())
        if obj.get("version") != CACHE_VERSION:
            return {}
        return obj.get("files", {})
    except Exception:
        return {}


def _save_cache(files_map):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(
            {"version": CACHE_VERSION, "files": files_map},
            separators=(",", ":"),
        ))
    except (OSError, IOError):
        pass


def _scan_file(path, extract):
    """Open a file, byte-prefilter, and return a list of cache entries
    (one per fuck-bearing user text fragment). Empty list is fine and
    is itself cached so we skip this file entirely next run."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except (OSError, IOError):
        return []
    if not FUCK_RE_B.search(data):
        return []

    entries = []
    for raw in data.splitlines():
        if not FUCK_RE_B.search(raw):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for key, ts, text in extract(obj):
            n = len(FUCK_RE.findall(text))
            if n:
                entries.append({"k": key, "t": ts, "n": n})
    return entries


def walk_and_count():
    per_day = Counter()
    per_source = Counter()
    total = 0
    seen_keys = set()

    cached = _load_cache()
    fresh = {}

    for name, root, extract in SOURCES:
        if not root.exists():
            continue
        for dirpath, _, filenames in os.walk(str(root)):
            for fn in filenames:
                if not fn.endswith(".jsonl"):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue

                # Cache hit: same mtime => content unchanged, skip I/O.
                hit = cached.get(path)
                if hit and hit.get("mtime") == mtime and hit.get("source") == name:
                    entries = hit.get("entries", [])
                else:
                    entries = _scan_file(path, extract)

                fresh[path] = {"mtime": mtime, "source": name, "entries": entries}

                for e in entries:
                    key = e["k"]
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    n = e["n"]
                    d = _parse_date(e.get("t"))
                    if d:
                        per_day[d] += n
                    per_source[name] += n
                    total += n

    _save_cache(fresh)
    return total, per_day, per_source


# ---------- Braille line chart ----------

BRAILLE_BASE = 0x2800
DOT_BIT = {
    (0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
    (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80,
}


def _set_pixel(grid, px, py, px_w, px_h):
    if 0 <= px < px_w and 0 <= py < px_h:
        cx, sx = divmod(px, 2)
        cy, sy = divmod(py, 4)
        grid[cy][cx] |= DOT_BIT[(sx, sy)]


def _bresenham(x1, y1, x2, y2):
    dx = abs(x2 - x1)
    dy = -abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx + dy
    while True:
        yield x1, y1
        if x1 == x2 and y1 == y2:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x1 += sx
        if e2 <= dx:
            err += dx
            y1 += sy


def render_chart(counts, width=72, height=14):
    px_w = width * 2
    px_h = height * 4
    grid = [[0] * width for _ in range(height)]

    n = len(counts)
    if n == 0:
        return "(no data)"

    # Max-preserving bucketing keeps peaks visible when the window is wide.
    if n > px_w:
        bucket = (n + px_w - 1) // px_w
        counts = [max(counts[i:i + bucket]) for i in range(0, n, bucket)]
        n = len(counts)

    max_c = max(counts) or 1
    xs = [int(i * (px_w - 1) / max(n - 1, 1)) for i in range(n)]

    def y_pixel(c):
        return int((1 - c / max_c) * (px_h - 1))

    for i in range(n - 1):
        for px, py in _bresenham(xs[i], y_pixel(counts[i]), xs[i + 1], y_pixel(counts[i + 1])):
            _set_pixel(grid, px, py, px_w, px_h)
    for i, c in enumerate(counts):
        _set_pixel(grid, xs[i], y_pixel(c), px_w, px_h)

    return "\n".join("".join(chr(BRAILLE_BASE + b) for b in row) for row in grid)


# ---------- ANSI coloring ----------

def _use_color():
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


C_ACCENT = "\033[38;5;208m"
C_MUTED  = "\033[38;5;244m"
C_BOLD   = "\033[1m"
C_RESET  = "\033[0m"


def c(s, code):
    if not _use_color():
        return s
    return f"{code}{s}{C_RESET}"


# ---------- main ----------

def main():
    total, per_day, per_source = walk_and_count()

    print()
    print(c("  f-bomb tracker", C_BOLD) + c("  — all sources, all time", C_MUTED))
    print()

    if total == 0:
        print(c("  no fucks found. everything fine?", C_MUTED))
        print()
        return

    first_day = min(per_day.keys())
    today = datetime.now().date()
    end = max(today, max(per_day.keys()))

    all_days, cur = [], first_day
    while cur <= end:
        all_days.append(cur)
        cur += timedelta(days=1)
    counts = [per_day.get(d, 0) for d in all_days]

    width, height = 72, 14
    max_c = max(counts)
    chart = render_chart(counts, width=width, height=height)

    y_label_w = 5
    top_lbl = f"{max_c:>{y_label_w}}"
    bot_lbl = f"{0:>{y_label_w}}"

    lines = chart.split("\n")
    for i, line in enumerate(lines):
        if i == 0:
            prefix = c(top_lbl, C_MUTED)
        elif i == len(lines) - 1:
            prefix = c(bot_lbl, C_MUTED)
        else:
            prefix = " " * y_label_w
        print(f"{prefix} {c('│', C_MUTED)} {c(line, C_ACCENT)}")

    axis = c("└" + "─" * width, C_MUTED)
    print(f"{' ' * y_label_w} {axis}")

    start_lbl = first_day.strftime("%b %Y").lower()
    mid_day = first_day + (end - first_day) / 2
    mid_lbl = mid_day.strftime("%b %Y").lower()
    end_lbl = end.strftime("%b %Y").lower()

    axis_line = [" "] * width
    def place(label, col):
        col = max(0, min(col, width - len(label)))
        for i, ch in enumerate(label):
            if col + i < width:
                axis_line[col + i] = ch
    place(start_lbl, 0)
    place(mid_lbl, (width - len(mid_lbl)) // 2)
    place(end_lbl, width - len(end_lbl))
    print(f"{' ' * (y_label_w + 2)}{c(''.join(axis_line), C_MUTED)}")
    print()

    span_days = (end - first_day).days + 1
    peak_day = max(per_day, key=per_day.get)
    mean = total / span_days

    def stat(label, value):
        print(f"  {c(label.ljust(12), C_MUTED)}{value}")

    stat("total",      c(f"{total:,}", C_BOLD + C_ACCENT))
    stat("span",       f"{span_days:,} days  ({first_day}  →  {end})")
    stat("mean/day",   f"{mean:.2f}")
    stat("peak",       c(f"{per_day[peak_day]}", C_BOLD) + f"  on  {peak_day}")
    print()

    print(f"  {c('by source', C_MUTED)}")
    for name in ("claude", "codex", "pi"):
        v = per_source.get(name, 0)
        pct = 100 * v / total if total else 0
        bar_w = 20
        filled = int(bar_w * v / total) if total else 0
        bar = c("█" * filled, C_ACCENT) + c("·" * (bar_w - filled), C_MUTED)
        print(f"    {name:<6} {bar}  {v:>6,}  {c(f'({pct:>4.1f}%)', C_MUTED)}")
    print()

    print(f"  {c('rattiest days', C_MUTED)}")
    for d, n in per_day.most_common(5):
        print(f"    {d}   {c(str(n), C_BOLD)}")
    print()


if __name__ == "__main__":
    main()
