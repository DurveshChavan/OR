# Style guide for spoken presentation scripts

Read this before drafting. It covers what to cut, what a rewrite looks like, how to
say numbers, and what a project-review panel actually asks.

**Contents**
1. Banned openers and phrases
2. Before and after
3. Numbers, symbols, and acronyms aloud
4. Transitions between slides
5. Slide types and what to say on each
6. Likely questions section

---

## 1. Banned openers and phrases

These are the phrases that mark a script as machine-written the moment they are spoken.
None of them should survive the humanizer pass.

**Openers**
- In today's fast-paced world / in today's digital age / in the modern era
- Since the dawn of / throughout history / for centuries
- Good morning everyone, I am **excited** / **thrilled** / **delighted** to present
- Have you ever wondered / imagine a world where / picture this
- Without further ado
- Let me walk you through / let's dive into / let's dive right in

**Body**
- plays a crucial role / plays a vital role / is a key component of
- it is important to note that / it is worth noting that / notably
- this groundbreaking approach / this innovative solution / cutting-edge
- seamlessly integrates / leverages / harnesses the power of
- delve into / unpack / explore the intricacies of
- robust, comprehensive, holistic, streamlined, scalable (when used as praise rather
  than as a measured technical claim)
- serves as a testament to / underscores the importance of / highlights the significance
- revolutionize / transform the way we / paradigm shift
- a wide range of / a plethora of / myriad

**Closers**
- In conclusion, we can say that
- Thank you for your valuable time / for your kind attention
- I hope you found this informative
- The possibilities are endless / the future looks bright
- Feel free to ask any questions you may have

A plain "Thank you. I am happy to take questions." is correct and finishes cleanly.

**Structural tells**
- Groups of exactly three adjectives or three clauses, repeatedly.
- Every slide opening with the same construction ("Moving on to...", "Next, we have...").
- A "Challenges and Future Prospects" paragraph that lists generic difficulties nobody
  in the room asked about.
- Em dashes. Do not use them; they have no spoken form and the reader trips.

---

## 2. Before and after

**Puffed significance**

> Before: This project stands as a testament to the transformative power of deep
> learning, playing a crucial role in bridging the communication gap and marking a
> pivotal moment in accessibility technology.

> After: This project addresses one specific gap. Existing sign language tools are
> built for American Sign Language, and they do not transfer to I-S-L.

**The `-ing` tack-on**

> Before: The model achieves ninety-six point seven percent accuracy, demonstrating
> the effectiveness of the attention mechanism and highlighting its potential for
> real-world deployment.

> After: The model reaches **ninety-six point seven percent** accuracy. [pause] That is
> three and a half points above the plain Bi-L-S-T-M, which is the gain from the
> attention layer.

**Unspeakable syntax**

> Before: Following the completion of preprocessing, wherein keypoint extraction is
> performed on each frame utilising the MediaPipe Holistic pipeline, the resultant
> feature vectors are subsequently aggregated into fixed-length windows.

> After: Each frame goes through MediaPipe Holistic, which extracts the keypoints.
> [pause] Thirty frames are then grouped into one window, and that window is what the
> model classifies.

**Manufactured drama**

> Before: Then we hit a wall. The accuracy plateaued. Nothing worked. Until we tried
> attention.

> After: Accuracy plateaued at around ninety-three percent with the plain Bi-L-S-T-M.
> Adding the attention layer moved it to ninety-six point seven.

**Claim the deck cannot support**

> Before: Our system is ready for deployment across schools and hospitals nationwide.

> After: The system runs on a standard laptop webcam, which makes classroom
> deployment realistic. [pause] It has not yet been tested outside our own recordings.

---

## 3. Numbers, symbols, and acronyms aloud

Write what the mouth says, not what the slide shows.

| On the slide | In the script |
|---|---|
| 96.7% | ninety-six point seven percent |
| 63 million | sixty-three million |
| 1,662 keypoints | one thousand six hundred and sixty-two keypoints |
| 4.2 MB | four point two megabytes |
| 24 FPS | twenty-four frames per second |
| 2019–2023 | two thousand nineteen to two thousand twenty-three |
| ~30 | roughly thirty |
| ISL | Indian Sign Language, or I-S-L (then I-S-L after) |
| API | A-P-I |
| JSON | Jason |
| SQL | see-quel, or S-Q-L if the user prefers |
| CNN, LSTM | C-N-N, L-S-T-M |
| Kumar et al. | Kumar and colleagues |
| e.g. / i.e. | for example / that is |

Round long decimals when precision does not matter. "Roughly ninety-seven percent"
is easier to say and just as true, unless the panel is comparing against a baseline,
in which case keep the exact figure and put `[slow down]` in front of it.

---

## 4. Transitions between slides

The last sentence of a slide should set up the next one. Without this the talk sounds
like separate paragraphs read in sequence.

Vary the construction. Do not open every slide with "Moving on to". Working patterns:

- Answer a question the previous slide raised: "So the question is how the model
  handles two-handed signs."
- Name the consequence: "That constraint is what shaped the architecture."
- Contrast: "The existing work stops at static alphabets. Ours handles continuous signs."
- Sequence, only occasionally: "With the design settled, here is how it was built."

When the user is presenting a partial deck, the first slide needs a one-sentence
bridge that establishes context the skipped slides would have given, and the last
slide needs a closing line so it does not end mid-thought.

---

## 5. Slide types and what to say on each

**Title.** Greeting, name, project title, guide's name. Do not read the subtitle
verbatim; the audience can read. Roughly twenty-five seconds.

**Agenda.** Name the sections in one sentence, do not read all six bullets one by one.
Say where the interesting part is: "Most of the time today goes to the results."

**Problem statement.** The number that establishes scale, then the specific gap. Panels
ask for the source of the number, so if the deck does not cite one, flag it.

**Literature survey.** Do not narrate every row. Group them: what the field does well,
what it does not do, and which single gap this project takes. Name two or three papers,
not all of them.

**Architecture or flow diagram.** Trace it in the order the data moves, left to right or
top to bottom. Use `[point to ...]`. Never read the box labels as a list. This slide
usually needs more time than its word count suggests, so leave `[pause 2s]` after
introducing it and let people read.

**Implementation.** Concrete and short. Dataset, environment, hyperparameters that
actually mattered, size, speed. Skip anything that is just a library version number.

**Results.** The most important slide. State the headline number, `[pause]`, then say
what it is being compared against, then the one thing the chart shows that the number
alone does not. Never say "as you can see from the graph" without saying what to see.

**Comparison table.** Read only the row that is yours and the closest competitor. The
rest is on screen.

**Conclusion.** Repeat the headline result once, state the honest limitation, then the
next step. A limitation stated by the presenter is worth more than one found by the panel.

**Thank you.** Two sentences. Do not thank them for their valuable time.

---

## 6. Likely questions section

Format each as the question in bold, then a spoken answer of two or three sentences the
user can say without reading. Draw every answer from the deck. If the deck does not
answer it, say so in the answer and mark it `[[FILL IN: ...]]` so the user prepares.

What college project panels reliably ask:

1. **Novelty.** How is this different from the papers in your survey? The weakest
   answers restate what the project does; the answer must name the specific thing no
   cited work did.
2. **Dataset.** Where did the data come from, how large, how was it split, is the test
   set genuinely held out? For self-recorded data, expect a question about bias.
3. **Baseline justification.** Why this model and not a simpler one? Have the ablation
   number ready if the deck has one.
4. **The metric.** Why accuracy and not precision, recall, or F1? Whether the classes
   were balanced.
5. **Failure cases.** When does it break? Answering honestly scores better than
   claiming it does not.
6. **Real-world use.** Latency, hardware needed, what would have to change to deploy.
7. **Individual contribution.** For team projects, what did you personally build.
8. **Scope.** Why this scale and not larger, and what the next step would cost in time
   or data.

For a seminar rather than a project review, replace 3 and 7 with questions about the
sources surveyed and about work the presenter chose to leave out.
