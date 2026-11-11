---
name: explain-visually
description: Explain an idea the user did not follow with a small offline HTML page of plain words, worked numbers and pictures, plus decision tabs if the explanation leaves choices. Use this whenever the user signals they don't understand, in any wording, even dictated or misspelled, and even if they never ask for a page - "I don't understand", "what do you mean", "what does X mean", "enlighten me", "I'm not sure what you mean by", "give me more background", "explain", "I can't follow this without examples or pictures", "same question for this other word". Also use it when they ask for an HTML or visual explanation, or for one to take a decision. Do not use it for a plain factual question that one sentence answers, unless they asked for a visual.
argument-hint: "[the term or idea to explain]"
---

# Explain visually

**First decide.** If one or two lines plainly settle it, answer in chat and stop. Otherwise a page gets built, and it stays small: a page for one idea is 2 to 4 sections.

**A subagent must build the page.** The main session never extracts data, writes the fragments, builds or render-checks itself, however small the page. It launches a background subagent straight away (pass `model: "sonnet"`), tells the user in one line that the page is on its way, and stays free to talk. Brief the subagent with the question in the user's own words, the files to use, the vocabulary rules, and these instructions: `${CLAUDE_SKILL_DIR}/SKILL.md`. The subagent runs steps 1 to 5 and returns the page's path and the paths of `cold_read.txt` and the PNGs; the main session then launches the cold read and sends any fixes back to the same subagent, and does steps 7 and 8 itself.

## Hard requirement: the page stands alone

The reader remembers nothing of the conversation and must never need to ask for more to understand the problem or the question.

- Open with **The situation**: what we are trying to find out, what data it rests on (with counts and units), what has already been decided, and why this question comes up now. The first thing after it is the direct answer to the question actually asked.
- Define every term, measure, abbreviation and option the first time it appears, with a number.
- Nothing depends on a chat message, an earlier page or another tab. A tab read alone makes sense.

## Page contents

- Start from what the term means in this project, in plain words. One idea per section: a worked numeric example, a picture, then a short "The point" line.
- Add a click where it clarifies (click a thing, see what changes). Inline HTML, SVG and vanilla JS only; no CDN or external resource, so the page opens offline.
- **Honesty labels.** Every figure carries a small label: real data, with its source and count (`tag real`), or made up for the picture (`tag made`).
- Prefer real data from the conversation's own files. Embed it from a script, never by typing it. Compute every printed number, or check it with `must()` in the page or `assert` in the script.
- State what wasn't measured or checked, and claim no more than the page shows. Colour is never the only signal: a figure also says it in words or shape.

## Questions are optional

Only if the explanation really leaves the user a decision; never invent one. No questions means no question section, and no tabs unless there are several topics.

Each question gets one tab: question box, its own context, evidence, options table (for, against, what each option changes in the results and what follows from it, recommended row in green), what is not known, and a closing line on what happens next. The reader must be able to decide from the page alone. End with a way to answer in one line, such as "1A, 2B". Do not use an option-grid prompt in chat.

## Look

Use `assets/page_template.html` through the build script. It holds the look (beige `#f7f1e3` with matching text halos, colour-blind-safe palette, 17 px body text, no decoration), the tabs and the helpers `el()`, `canvas()`, `axes()`, `plot()`, `must()`. Don't restyle it. Markup for each part is in `references/page_patterns.md`.

## Language

Direct, no praise, no emotional framing. No internal labels or code names unless defined on the page. Full absolute paths. Before writing, check the project's `CLAUDE.md` and auto memory for vocabulary rules, and name the unit of analysis and each term the way the project does.

## Procedure

**The Write tool opens a browser tab for every `.html` it writes in full** (hook `$HOME\.claude\hooks\open-html-docx.ps1`), so repeated writes pile up tabs. Never use Write on a `.html`, whether page or fragment: name fragments `body.txt` and `figures.js`.

1. **Choose the folder.** Where the project keeps review material (see its memory), otherwise the session scratchpad. Never a repo's tracked folders unless asked. Keep fragments in a `<page>_src` subfolder.
2. **Data.** If real data exists, write `extract.py`, which computes the numbers and saves `data.json`. For made-up numbers, do the same with a fixed seed.
3. **Write** `body.txt` and `figures.js`.
4. **Build.**
   ```
   python "${CLAUDE_SKILL_DIR}/scripts/build_page.py" --title "..." --body body.txt --js figures.js --data data.json --out "<abs path>/page.html"
   ```
   It refuses a page without the situation, the answer, figure labels, point lines or the required parts of a question tab, and any page loading an external resource.
5. **Render check,** with no window and without opening the page.
   ```
   python "${CLAUDE_SKILL_DIR}/scripts/render_check.py" "<abs path>/page.html" --work "<scratch folder>" --test clicks.js
   ```
   It runs headless Chrome (`--headless=new`), saves one PNG per tab, and reports script errors, overlapping or clipped labels and sideways scrolling. `clicks.js` holds lines like `document.querySelector("#g2").dispatchEvent(new MouseEvent("click")); check("group 2 selected", ...)`; write it whenever the page has clicks. It can also call `labelProblems()` on a state reached by clicking. Read every PNG with Read and fix what it shows, including what the script can't see, such as a label sitting on a line.
6. **Cold read,** launched by the main session. The builder can't see the page's gaps because it wrote it: give a second, fresh subagent (pass `model: "haiku"`) only `cold_read.txt` and the PNGs, ask it to list any term, number or reference it can't understand from the page, what it can't understand, any claim that goes past what the page shows, any statements that conflict, and whether it could decide each question. Fix everything it lists, rebuild, re-run step 5.
7. **Open exactly once,** only now: `Start-Process -FilePath "<abs path>/page.html"`. A subagent never opens the page; the main session does.
8. **Reply** in a few lines: the absolute path, the direct answer, any question waiting. Do not repeat the page.

**Later changes.** Send them to the same subagent, which rebuilds with the script or uses Edit and re-runs steps 5 and 6 as far as the change needs. The main session then tells the user to press F5. Never open a second tab.
