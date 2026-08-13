---
name: presentation-script
description: Turn a PowerPoint deck into a timed, word-for-word teleprompter script the user can read aloud. Use this whenever someone uploads or points at a .pptx/.ppt and asks what to say, how to present it, for a speech, a seminar script, a viva or project-review script, speaker notes they can actually read, or help rehearsing. Trigger on phrases like "script for my presentation", "what do I say for these slides", "I have to present this in 10 minutes", "teleprompter", "my seminar is tomorrow", "help me present this deck", and on any request that pairs a deck with a time limit. Also use when the user wants an existing presentation script re-timed, shortened, lengthened, or made to sound less AI-written.
---

# Presentation Script

Produces a `.md` file the user reads aloud, word for word, while presenting. Every
sentence is written out. Pauses, slide clicks, and stress are marked inline. The
script is timed so the talk finishes when the clock does.

Default context: a final-year college project review or seminar, delivered in
**formal academic English**. Adjust if the user says otherwise, but do not drift
casual on your own.

## Step 1: Intake

Four things are needed. Take whatever the user already gave and ask only for the rest,
in a single message, not one at a time.

1. **The deck.** A `.pptx` in `/mnt/user-data/uploads/`. If they described a
   presentation but attached nothing, ask for the file before doing anything else.
2. **Which slides.** Whole deck, or a range like "4 to 9". Accept a description too
   ("just the architecture part") and resolve it against the slide titles after
   extraction, confirming the range you picked.
3. **How many minutes.** This is the hard constraint everything else is fitted to. If
   they say "10 to 12", use the lower number so they finish early rather than get cut off.
4. **The occasion and the panel.** Project review, seminar, mid-term evaluation,
   conference. Whether a guide or examiner is present changes how much the script
   defends its choices.

Two more worth asking once, briefly, since they change the whole script:

- **Solo or team?** Decides "I built" versus "we built". Getting this wrong is
  noticeable in every paragraph.
- **Anything you must mention** — a required section, a rubric point, a number the
  guide asked about last time.

Do not interrogate. If they clearly want it fast and have given the deck, slides, and
minutes, make reasonable assumptions, state them in one line, and write the script.

## Step 2: Read the deck

```bash
python scripts/extract_deck.py <deck.pptx> --slides 4-9 --minutes 10
```

Returns JSON: per-slide title, body lines, speaker notes, table/chart/picture counts,
a `kind` label, and — when `--minutes` is passed — a word budget and clock window per
slide, plus pacing warnings. `--slides all` is the default.

**Read the speaker notes.** They often contain what the user actually intends to say
and what the guide told them last time. Notes outrank the on-slide bullets.

If the script fails, fall back to `markitdown deck.pptx`, which dumps text per slide
under `<!-- Slide number: N -->` markers, and do the budgeting by hand using the
formula below.

For a slide that is only a diagram or image, the extractor cannot see it. Render the
deck and look:

```bash
python /mnt/skills/public/pptx/scripts/office/soffice.py --headless --convert-to pdf deck.pptx
pdftoppm -jpeg -r 150 deck.pdf slide && ls -1 "$PWD"/slide-*.jpg
```

Then view the relevant image. Never narrate a diagram you have not looked at.

## Step 3: Check the time budget before writing

The extractor assumes 130 words per minute and reserves 10% of the clock for pauses,
clicks, and breathing — about 117 spoken words per allotted minute. Fixed allocations:
55 words for the title slide, 45 for an agenda, 20 for a thank-you. The remainder is
split across the rest by weight (1 light, 2 normal, 3 for charts, tables, diagrams,
and results).

Report the pacing warnings to the user **before** writing 900 words they cannot use:

- **Under ~35 words on a slide** means there is no time to say anything real. Suggest
  merging it with a neighbour or dropping it.
- **Over ~200 words** means the slide runs past ninety seconds and the room drifts.
  Suggest splitting it.
- **More than 1.5 slides per minute** is a rushed pace. Say so plainly and offer to
  mark low-value slides as "flip past" so the important ones get proper time.

Offer the fix, but if the user says present it as is, write the script as is.

## Step 4: Write the script

### Per-slide block

Use this shape for every slide, unchanged:

```
---

### SLIDE 7 — Implementation
`03:55 – 04:42` · ~90 words

> On screen: three bullets on dataset, training setup, and model size.

[look up] [pause]

The system was implemented in three stages.
[pause]
The dataset contains **forty ISL words**, with sixty recorded sequences each.
Training ran on a Colab T-four for two hundred epochs using the Adam optimiser.
[pause 2s]
The final model is **four point two megabytes**, and it runs at twenty-four frames
per second on a mid-range laptop.
[CUT IF BEHIND] No dedicated hardware is required at any point.

[next slide →]
```

The `> On screen:` line is a one-line reminder of what the audience is looking at, so
the user can glance up without losing their place. Keep it to one line.

### Line breaks

Break lines at breath points, one clause per line. Long unbroken paragraphs are the
single biggest reason a teleprompter script fails when read aloud. A line should be
readable in one glance.

### Cue vocabulary

Keep to exactly these. A large cue vocabulary is unreadable at speed.

| Cue | Means |
|---|---|
| `[pause]` | One beat. Roughly a second. |
| `[pause 2s]` | Hold. After a number that matters, or on a new diagram. |
| `[next slide →]` | Click. Always the last line of a block. |
| `[look up]` | Eye contact. Use at the start of a slide and before a key claim. |
| `[point to the graph]` | Gesture at a named element. |
| `[slow down]` | For a definition or a sequence of numbers. |
| `**bold**` | Stress this word. Two or three per slide, no more. |
| `[CUT IF BEHIND]` | Skip this sentence if running late. One or two per slide. |
| `[[FILL IN: what]]` | The deck did not contain this. The user must supply it. |

### Speakability

These are the rules that separate a script from an essay read aloud:

- Sentences under twenty words, averaging around fourteen. One idea each.
- Active voice. "We tested the model", not "testing of the model was performed".
- **Numbers written as spoken**: "ninety-six point seven percent", not "96.7%".
  "Sixty-three million", not "63 million". The eye stumbles on digits mid-sentence.
- **Acronyms**: expand on first use, then hint the pronunciation. "Indian Sign
  Language, or I-S-L". Letter-by-letter acronyms get hyphens; spoken ones do not.
- Do not open a sentence with a subordinate clause longer than about six words.
- Each slide's first sentence should connect to the previous slide, so the talk is
  continuous rather than eleven separate speeches.
- Never write a sentence the user cannot defend. If a slide implies a claim it does
  not support, write the modest version or insert `[[FILL IN: ...]]`.

### Formal register, spoken

Formal here means the register of a project review, not the syntax of a journal paper.
No slang, no jokes, no "you guys", no fake-candid openers. Complete sentences. But
also no nested subordinate clauses, no parentheticals, no nominalisation stacks.
A sentence that reads fine and cannot be said in one breath has failed.

The standard opening is fine and expected: greeting, name, project title, guide's
name if present. Do not dress it up.

### Fixed sections

Every script gets these, in this order:

1. **Header** — deck title, occasion, total time, slide range, word count, and the
   pace assumption in one line.
2. **Pacing card** — a compact table of slide number, title, and clock window, so the
   user can check mid-talk whether they are ahead or behind.
3. **How to use this** — three lines maximum. What the cues mean, and the note that
   the times assume they actually pause where marked.
4. **The slide blocks.**
5. **Likely questions** — six to eight questions the panel will probably ask, each
   with a two-or-three-sentence spoken answer. For a project review this is often the
   most useful part of the file. See `references/style-guide.md` for what panels ask.
   Skip only if the user says they do not want it.

## Step 5: The humanizer pass is mandatory

Run `/mnt/skills/user/humanizer/SKILL.md` on the drafted script **every time**, whether
or not the user asks. Use its **embedded mode**: run the draft, audit, and revise loop
internally, and output only the final text. Do not paste draft-versus-final comparisons
into the conversation.

Two calibrations matter, because the default humanizer behaviour is wrong for this job
in both directions:

**Do not apply its PERSONALITY AND SOUL section.** That section injects opinions,
asides, and mixed feelings. In a formal project review, neutral and plain *is* the
correct human voice. A script with jokes in it will embarrass the user in front of a panel.

**Do apply, aggressively**, its patterns on significance puffery (§1), `-ing` tack-ons
(§3), promotional language (§4), vague attributions (§5), "Challenges and Future
Prospects" filler (§6), AI vocabulary (§7), em dashes (§14), staccato drama (§31),
aphorism formulas (§32), and conversational rhetorical openers (§33). Spoken AI slop is
more obvious than written AI slop, because the audience hears the rhythm.

**Never invent a fact.** No number, dataset size, accuracy figure, citation, or name
enters the script unless it is in the deck, the speaker notes, or something the user
told you. This rule outranks fluency. When a sentence needs a figure the deck does not
have, write `[[FILL IN: accuracy on the test set]]` and move on.

`references/style-guide.md` has the banned opener list and before/after pairs for
presentation prose specifically. Read it before drafting.

## Step 6: Verify the timing before delivering

```bash
python scripts/check_script.py <draft>.md
```

This counts only the words that get spoken, ignoring cues, headers, the pacing card,
and the questions section, then compares each slide against its `~N words` target.
Exit code 1 means rewrite.

**Expect the first draft to come in short.** Tightly written prose feels finished
before the budget is used, and drafts routinely land twenty to twenty-five percent
under, which turns an eight minute talk into a six minute one. Fix by adding substance,
not padding: the reason behind a design choice, the number the panel will ask for, the
limitation stated before someone finds it. If a slide genuinely has nothing more to
say, move its words to the results slide rather than inflating it.

The checker also flags em or en dashes and leftover numerals in spoken lines. Both
rules apply to spoken text only. Structural em dashes in the block headings
(`### SLIDE 7 — Implementation`) are fine and should stay.

Rerun until it passes, then deliver.

## Step 7: Deliver

Write to `/mnt/user-data/outputs/<deck-name>-script.md` and call `present_files`.

Then, in three or four lines of chat, tell the user:

- The word count and what pace it assumes.
- Any slide where you inserted `[[FILL IN: ...]]` and what it needs.
- Any pacing warning they should act on.
- That they should read it aloud once with a timer, since everyone's natural pace
  differs from 130 words per minute by ten or fifteen percent.

Do not paste the whole script into the chat. It belongs in the file.

## Re-timing an existing script

If the user comes back with "make it six minutes instead of ten", do not regenerate
from scratch. Recompute the budget, then cut in this order: `[CUT IF BEHIND]` lines
first, then supporting detail, then whole low-weight slides — and tell the user which
slides you dropped so they can pull them from the deck too. Protect the results and
conclusion sections; those are what the panel grades.
