#!/usr/bin/env python3
"""
bro-fuck-count: tally case-insensitive 'fuck' occurrences across your AI
session history and print a Braille line chart over all time.

Walks three session stores:
  ~/.claude/projects/**/*.jsonl   (Claude Code)
  ~/.pi/agent/sessions/**/*.jsonl (Pi)
  ~/.codex/sessions/**/*.jsonl    (Codex)

Only counts text authored by the user (role == "user"), skipping
tool_result echoes and assistant output. Buckets by day, extends the
range from first-fuck to today so quiet weeks show as gaps.

No third-party deps. Python 3.8+.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

FUCK_RE = re.compile(r"fuck", re.IGNORECASE)


# ---------- per-source extractors ----------

def _extract_claude(obj):
    if obj.get("type") != "user":
        return
    msg = obj.get("message") or {}
    if msg.get("role") != "user":
        return
    ts = obj.get("timestamp")
    content = msg.get("content")
    if isinstance(content, str):
        yield ts, content
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text") or ""
                if t:
                    yield ts, t


def _extract_pi(obj):
    if obj.get("type") != "message":
        return
    msg = obj.get("message") or {}
    if msg.get("role") != "user":
        return
    ts = obj.get("timestamp")
    content = msg.get("content") or []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text") or ""
                if t:
                    yield ts, t


def _extract_codex(obj):
    if obj.get("type") != "response_item":
        return
    payload = obj.get("payload") or {}
    if payload.get("type") != "message" or payload.get("role") != "user":
        return
    ts = obj.get("timestamp")
    content = payload.get("content") or []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "input_text":
                t = item.get("text") or ""
                if t:
                    yield ts, t


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


def walk_and_count():
    per_day = Counter()
    per_source = Counter()
    total = 0
    for name, root, extract in SOURCES:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            try:
                with open(path, "r", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        for ts, text in extract(obj):
                            n = len(FUCK_RE.findall(text))
                            if not n:
                                continue
                            d = _parse_date(ts)
                            if d:
                                per_day[d] += n
                            per_source[name] += n
                            total += n
            except (OSError, IOError):
                continue
    return total, per_day, per_source


# ---------- Braille line chart ----------

BRAILLE_BASE = 0x2800
# Mapping (sub_x in 0..1, sub_y in 0..3) -> Braille dot bit
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

    # Bucket by max-per-bucket if we have more days than horizontal pixels;
    # max-preserving keeps peaks visible instead of averaging them away.
    if n > px_w:
        bucket = (n + px_w - 1) // px_w
        bucketed = [max(counts[i:i + bucket]) for i in range(0, n, bucket)]
        counts = bucketed
        n = len(counts)

    max_c = max(counts) or 1
    xs = [int(i * (px_w - 1) / max(n - 1, 1)) for i in range(n)]

    def y_pixel(c):
        return int((1 - c / max_c) * (px_h - 1))

    # Draw connecting line
    for i in range(n - 1):
        for px, py in _bresenham(xs[i], y_pixel(counts[i]), xs[i + 1], y_pixel(counts[i + 1])):
            _set_pixel(grid, px, py, px_w, px_h)

    # Mark each point
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


C_ACCENT = "\033[38;5;208m"   # burnt orange
C_MUTED  = "\033[38;5;244m"   # warm gray
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

    # Build contiguous day range: first fuck -> today
    first_fuck_day = min(per_day.keys())
    today = datetime.now().date()
    end = max(today, max(per_day.keys()))

    all_days, cur = [], first_fuck_day
    while cur <= end:
        all_days.append(cur)
        cur += timedelta(days=1)
    counts = [per_day.get(d, 0) for d in all_days]

    width, height = 72, 14
    max_c = max(counts)
    chart = render_chart(counts, width=width, height=height)

    # Y-axis labels at top/bottom
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

    # X-axis
    axis = c("└" + "─" * width, C_MUTED)
    print(f"{' ' * y_label_w} {axis}")

    # Date labels: start, middle, end
    start_lbl = first_fuck_day.strftime("%b %Y").lower()
    mid_day = first_fuck_day + (end - first_fuck_day) / 2
    mid_lbl = mid_day.strftime("%b %Y").lower()
    end_lbl = end.strftime("%b %Y").lower()

    axis_line = [" "] * width
    # Place labels, clipped to axis
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

    # Stats block
    span_days = (end - first_fuck_day).days + 1
    peak_day = max(per_day, key=per_day.get)
    mean = total / span_days

    def stat(label, value):
        print(f"  {c(label.ljust(12), C_MUTED)}{value}")

    stat("total",      c(f"{total:,}", C_BOLD + C_ACCENT))
    stat("span",       f"{span_days:,} days  ({first_fuck_day}  →  {end})")
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
