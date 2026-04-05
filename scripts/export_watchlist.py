"""
Export the AI tool watchlist to Markdown or CSV.

Usage:
    python scripts/export_watchlist.py              # → prints Markdown
    python scripts/export_watchlist.py --csv        # → prints CSV
    python scripts/export_watchlist.py --out tools.md
"""

import json
import os
import sys

WATCHLIST_PATH = "learning/db/ai_watchlist.json"


def load_watchlist() -> list[dict]:
    if not os.path.exists(WATCHLIST_PATH):
        print("No watchlist found. Run the monthly report first.")
        return []
    with open(WATCHLIST_PATH) as f:
        return json.load(f)


def to_markdown(tools: list[dict]) -> str:
    lines = ["# AI Tool Watchlist\n",
             "| Tool | Category | Rating | First Seen | Description |",
             "|---|---|---|---|---|"]
    for t in sorted(tools, key=lambda x: x.get("first_seen", ""), reverse=True):
        lines.append(
            f"| {t.get('tool_name', '?')} "
            f"| {t.get('category', '?')} "
            f"| {t.get('claude_rating', '?')} "
            f"| {t.get('first_seen', '?')} "
            f"| {t.get('description', '')} |"
        )
    return "\n".join(lines)


def to_csv(tools: list[dict]) -> str:
    lines = ["tool_name,category,claude_rating,first_seen,description"]
    for t in tools:
        desc = t.get("description", "").replace(",", ";")
        lines.append(
            f"{t.get('tool_name','')},{t.get('category','')},{t.get('claude_rating','')},"
            f"{t.get('first_seen','')},{desc}"
        )
    return "\n".join(lines)


def main():
    tools = load_watchlist()
    if not tools:
        return

    use_csv = "--csv" in sys.argv
    output = to_csv(tools) if use_csv else to_markdown(tools)

    out_path = None
    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        if idx + 1 < len(sys.argv):
            out_path = sys.argv[idx + 1]

    if out_path:
        with open(out_path, "w") as f:
            f.write(output)
        print(f"Exported {len(tools)} tools to {out_path}")
    else:
        print(output)


if __name__ == "__main__":
    main()
