#!/usr/bin/env python3
"""Extract a .pptx into per-slide JSON for script writing.

Usage:
    python scripts/extract_deck.py deck.pptx [--slides 4-9,12] [--minutes 10]

Emits JSON to stdout:
    {
      "file": "deck.pptx",
      "slide_count": 14,
      "selected": [4,5,6,7,8,9,12],
      "budget": {...}          # only when --minutes is passed
      "slides": [
        {"n": 1, "title": "...", "body": ["bullet", ...], "notes": "...",
         "tables": 0, "charts": 1, "pictures": 2, "words": 37,
         "weight": 2, "kind": "content"}
      ]
    }

The `weight` field drives the time allocation described in SKILL.md.
Nothing here writes to the deck; it is read-only.
"""

import argparse
import json
import re
import sys

try:
    from pptx import Presentation
    from pptx.util import Emu
except ImportError:
    sys.exit("python-pptx is required: pip install python-pptx --break-system-packages")


# Slides matching these get fixed word allocations rather than proportional ones.
TITLE_HINTS = re.compile(r"^\s*$", re.I)
AGENDA_HINTS = re.compile(r"\b(agenda|outline|contents?|overview|road ?map)\b", re.I)
CLOSING_HINTS = re.compile(r"\b(conclusion|summary|takeaways?|future (work|scope)|"
                           r"references?|bibliograph)\b", re.I)
THANKS_HINTS = re.compile(r"\b(thank ?you|thanks|q\s*&\s*a|questions\??)\b", re.I)
RESULTS_HINTS = re.compile(r"\b(results?|findings?|evaluation|accuracy|performance|"
                           r"benchmark|comparison|analysis|testing)\b", re.I)
DIAGRAM_HINTS = re.compile(r"\b(architecture|flow ?chart|flow ?diagram|block diagram|"
                           r"work ?flow|pipeline|use ?case|sequence diagram|er diagram|"
                           r"schema|design|dfd|uml|methodology|system model)\b", re.I)
ARROW = re.compile(r"(->|-->|→|=>)")


def parse_ranges(spec, maximum):
    """'4-9,12' -> [4,5,6,7,8,9,12]. 'all' or None -> every slide."""
    if not spec or spec.strip().lower() == "all":
        return list(range(1, maximum + 1))
    out = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(chunk))
    return [n for n in sorted(set(out)) if 1 <= n <= maximum]


def shape_text(shape):
    if not shape.has_text_frame:
        return []
    lines = []
    for para in shape.text_frame.paragraphs:
        text = "".join(run.text for run in para.runs).strip()
        if text:
            lines.append(text)
    return lines


def walk(shapes):
    """Yield every shape, descending into groups."""
    for shape in shapes:
        if shape.shape_type == 6 and hasattr(shape, "shapes"):  # GROUP
            yield from walk(shape.shapes)
        else:
            yield shape


def classify(n, total, title, body, charts, tables, pictures):
    """Label the slide so the allocator knows whether to use a fixed budget."""
    # Match on the title only. Body text mentions "accuracy" or "analysis" all the
    # time without the slide being a results slide.
    if n == 1 and len(body) <= 3:
        return "opening"
    if AGENDA_HINTS.search(title) and len(body) <= 10:
        return "agenda"
    if THANKS_HINTS.search(title) and len((title + " ".join(body)).split()) < 12:
        return "thanks"
    if CLOSING_HINTS.search(title):
        return "closing"
    if RESULTS_HINTS.search(title) or charts or tables:
        return "results"
    if DIAGRAM_HINTS.search(title) or any(ARROW.search(b) for b in body):
        return "diagram"
    if not body and pictures:
        return "visual"
    return "content"


def weigh(kind, body, charts, tables, pictures, words):
    """1 = light, 2 = normal, 3 = heavy. Drives proportional time split."""
    if kind in ("opening", "agenda", "thanks"):
        return 0  # fixed allocation, excluded from the proportional pool
    score = 1
    bullets = len(body)
    if bullets >= 3 or words >= 30:
        score = 2
    if bullets >= 6 or words >= 70:
        score = 3
    if charts or tables:
        score = max(score, 3)
    if kind in ("visual", "diagram"):
        # A diagram carries little text but takes the longest to explain aloud.
        score = max(score, 2)
    return score


def extract(path, slide_spec):
    prs = Presentation(path)
    total = len(prs.slides)
    selected = parse_ranges(slide_spec, total)
    slides = []

    for idx, slide in enumerate(prs.slides, start=1):
        if idx not in selected:
            continue
        title, body = "", []
        charts = tables = pictures = 0

        # Prefer the real title placeholder; fall back to the topmost text box.
        try:
            if slide.shapes.title is not None:
                title = (slide.shapes.title.text or "").strip()
        except (AttributeError, ValueError):
            pass

        candidates = []
        for shape in walk(slide.shapes):
            if getattr(shape, "has_chart", False):
                charts += 1
            if getattr(shape, "has_table", False):
                tables += 1
                tbl = shape.table
                cells = [c.text.strip() for row in tbl.rows for c in row.cells]
                body.append("[table] " + " | ".join(c for c in cells if c)[:400])
            if shape.shape_type == 13:  # PICTURE
                pictures += 1
            lines = shape_text(shape)
            if lines:
                top = shape.top if shape.top is not None else Emu(0)
                candidates.append((top, lines))

        candidates.sort(key=lambda pair: pair[0])
        for _, lines in candidates:
            for line in lines:
                if line == title:
                    continue
                if line not in body:
                    body.append(line)

        if not title and body:
            title = body.pop(0)

        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()

        words = len(" ".join([title] + body).split())
        kind = classify(idx, total, title, body, charts, tables, pictures)
        slides.append({
            "n": idx,
            "title": title,
            "body": body,
            "notes": notes,
            "tables": tables,
            "charts": charts,
            "pictures": pictures,
            "words": words,
            "kind": kind,
            "weight": weigh(kind, body, charts, tables, pictures, words),
        })

    return {"file": path, "slide_count": total, "selected": selected, "slides": slides}


FIXED = {"opening": 55, "agenda": 45, "thanks": 20}
WPM = 130
PAUSE_ALLOWANCE = 0.90     # ~10% of the clock goes to pauses, clicks, breathing
FLOOR = 35                 # fewer words than this and the slide is a flash card
CEILING = 200              # more than this and the slide runs past ~90 seconds


def budget(data, minutes):
    """Split the word budget across slides and flag pacing problems."""
    total_words = int(minutes * WPM * PAUSE_ALLOWANCE)
    slides = data["slides"]
    fixed = sum(FIXED[s["kind"]] for s in slides if s["kind"] in FIXED)
    pool = max(total_words - fixed, 0)
    weight_sum = sum(s["weight"] for s in slides) or 1

    warnings = []
    clock = 0.0
    for s in slides:
        if s["kind"] in FIXED:
            words = FIXED[s["kind"]]
        else:
            words = int(pool * s["weight"] / weight_sum)
        s["target_words"] = words
        seconds = words / WPM * 60 / PAUSE_ALLOWANCE
        s["target_seconds"] = round(seconds)
        s["clock_start"] = f"{int(clock // 60):02d}:{int(clock % 60):02d}"
        clock += seconds
        s["clock_end"] = f"{int(clock // 60):02d}:{int(clock % 60):02d}"
        if words < FLOOR and s["kind"] not in FIXED:
            warnings.append(
                f"Slide {s['n']} gets only ~{words} words (~{s['target_seconds']}s). "
                "Too little to say anything real.")
        if words > CEILING:
            warnings.append(
                f"Slide {s['n']} gets ~{words} words (~{s['target_seconds']}s). "
                "Long enough that the audience will drift. Consider splitting it.")

    per_minute = len(slides) / minutes if minutes else 0
    if per_minute > 1.5:
        warnings.append(
            f"{len(slides)} slides in {minutes} minutes is {per_minute:.1f} slides/min. "
            "Above roughly 1.5 the pace feels rushed. Suggest cutting or merging slides.")

    data["budget"] = {
        "minutes": minutes,
        "wpm": WPM,
        "total_words": total_words,
        "slides_per_minute": round(per_minute, 2),
        "warnings": warnings,
    }
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deck")
    ap.add_argument("--slides", default="all",
                    help="Slide range, e.g. '4-9,12'. Default: all.")
    ap.add_argument("--minutes", type=float, default=None,
                    help="Total talk time. Adds the per-slide word budget.")
    args = ap.parse_args()

    data = extract(args.deck, args.slides)
    if args.minutes:
        data = budget(data, args.minutes)
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
