#!/usr/bin/env python3
"""Check a drafted script against its own word budget.

Usage:
    python scripts/check_script.py outputs/deck-script.md [--wpm 130] [--tolerance 0.15]

Counts only words that will actually be spoken: cue markers, on-screen reminders,
clock lines, headings, and table rows are excluded. Reports per-slide drift against
the `~N words` target in each block header, plus the total runtime estimate.

Drafts routinely land 20-25% under target because writing tight prose feels finished
before the budget is used. Run this before delivering; it is the difference between
an eight minute talk and a six minute one.

Exit code is 1 if the total is outside tolerance, so it can gate a rewrite loop.
"""

import argparse
import re
import sys

SLIDE_RE = re.compile(r"^###\s+SLIDE\s+(\d+)\s*[—\-–]\s*(.*)$")
TARGET_RE = re.compile(r"~\s*(\d+)\s*words")
CUE_RE = re.compile(r"\[\[.*?\]\]|\[[^\]]*\]")
PAUSE_CUES = {"pause", "look up", "next slide", "slow down", "point to", "cut if behind"}


def spoken_lines(block):
    """The lines a presenter actually says, with cues and markup stripped."""
    out = []
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", ">", "|", "---", "***")):
            continue
        if stripped.startswith("`") and stripped.endswith("`"):
            continue
        # A line that is only cues contributes no spoken words.
        text = CUE_RE.sub(" ", stripped)
        text = text.replace("**", "").replace("*", "").replace("`", "")
        # Drop the inline clock/word-count line if it survived.
        if re.match(r"^\s*\d{2}:\d{2}", text):
            continue
        if text.strip():
            out.append(text.strip())
    return out


def spoken_words(block):
    text = " ".join(spoken_lines(block))
    return [w for w in text.split() if any(c.isalnum() for c in w)]


def parse(path):
    text = open(path, encoding="utf-8").read()
    # Everything after the Q&A heading is read silently, not spoken.
    body = re.split(r"^##\s+Likely questions", text, flags=re.M)[0]
    chunks = re.split(r"^(?=###\s+SLIDE\s)", body, flags=re.M)

    slides = []
    for chunk in chunks:
        header = chunk.split("\n", 1)[0]
        m = SLIDE_RE.match(header.strip())
        if not m:
            continue
        target = TARGET_RE.search(chunk)
        slides.append({
            "n": int(m.group(1)),
            "title": m.group(2).strip(),
            "target": int(target.group(1)) if target else None,
            "actual": len(spoken_words(chunk)),
            "text": " ".join(spoken_lines(chunk)),
        })
    return slides, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--wpm", type=float, default=130)
    ap.add_argument("--tolerance", type=float, default=0.10,
                    help="Allowed fractional drift before a slide or the total is flagged.")
    args = ap.parse_args()

    slides, text = parse(args.script)
    if not slides:
        sys.exit("No '### SLIDE N — Title' blocks found. Check the file format.")

    total_t = sum(s["target"] for s in slides if s["target"])
    total_a = sum(s["actual"] for s in slides)

    print(f"{'#':>3}  {'target':>6} {'actual':>6} {'drift':>7}  title")
    problems = []
    for s in slides:
        if s["target"]:
            drift = (s["actual"] - s["target"]) / s["target"]
            flag = "" if abs(drift) <= args.tolerance * 1.5 else "  <-- fix"
            if flag:
                problems.append(s)
            print(f"{s['n']:>3}  {s['target']:>6} {s['actual']:>6} {drift:>+6.0%}{flag}  {s['title'][:38]}")
        else:
            print(f"{s['n']:>3}  {'?':>6} {s['actual']:>6} {'':>7}  {s['title'][:38]}")

    mins = total_a / args.wpm / 0.90
    target_mins = total_t / args.wpm / 0.90 if total_t else 0
    print()
    print(f"total spoken words : {total_a}  (target {total_t})")
    print(f"estimated runtime  : {int(mins)}:{int(mins % 1 * 60):02d}"
          f"   (target {int(target_mins)}:{int(target_mins % 1 * 60):02d})")

    # Style checks run on spoken text only, never on headers or the pacing card.
    spoken_only = " ".join(s["text"] for s in slides)
    if "—" in spoken_only or "–" in spoken_only:
        print("WARN: em or en dash in spoken text. Replace with a full stop or comma.")
    digits = re.findall(r"(?<![\w:])\d+(?:\.\d+)?\s*(?:%|percent|MB|GB|FPS|fps)?(?![\w])",
                        spoken_only)
    if digits:
        print(f"WARN: {len(digits)} numeral(s) left in spoken text "
              f"({', '.join(digits[:6])}). Write them as words.")

    if total_t:
        overall = abs(total_a - total_t) / total_t
        if overall > args.tolerance:
            direction = "short" if total_a < total_t else "long"
            print(f"\nFAIL: {overall:.0%} {direction} overall. Rewrite the flagged slides.")
            sys.exit(1)
    print("\nOK: within tolerance.")


if __name__ == "__main__":
    main()
