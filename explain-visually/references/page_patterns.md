# Page patterns

Fragments for `body.txt` and `figures.js`. `build_page.py` rejects a page that drops a required part.

## Opening (every page)

```html
<section class="situation">
<h2>The situation</h2>
<dl>
<dt>What we are trying to find out</dt><dd>One or two sentences, with the terms defined.</dd>
<dt>What data it rests on</dt><dd>What was measured, how much, in what units, and where it is stored, for example "1200 readings, temperature in °C".</dd>
<dt>Already decided</dt><dd>Who decided what and when, in words, or "Nothing yet."</dd>
<dt>Why this comes up now</dt><dd>The step that raised it, told as if the reader was not there.</dd>
</dl>
</section>
<div class="answer">Direct answer to the question asked, in one or two sentences, with a number.</div>
```

## One idea

```html
<section>
<h2>1. The idea in plain words</h2>
<p>Definition, then the worked example. <b>Click a group</b> to see what changes.</p>
<span class="tag made">Made-up numbers</span>
<div class="fig" id="f1"></div>
<div class="cap" id="f1t"></div>
<div class="point"><b>The point:</b> one sentence.</div>
</section>
```

Label wording: `tag real` names the source and count ("Real groups: one sensor, 40 groups"); `tag made` says how it was made ("Made-up numbers, worked by hand", "Simulated noise, 5000 runs"). Where a figure has several panels, put the label before the `.row` and count one label per `.fig`.

## Click, then redraw

```js
let hidden = 2;
function draw() {
  const {s, X, Y} = plot("f1", {x0:0, x1:6, y0:0, y1:40, xt:[1,2,3,4,5], yt:[0,20,40], xl:"group", yl:"value (Hz)"});
  D.values.forEach((v, i) => {
    const dot = el("circle", {cx:X(i+1), cy:Y(v), r:9, fill:i===hidden?ORANGE:BLUE, class:"clickable"}, s);
    dot.addEventListener("click", () => { hidden = i; draw(); });
  });
  document.getElementById("f1t").textContent = `Group ${hidden+1} is hidden: ${D.values[hidden].toFixed(1)} Hz.`;
}
draw();
must(Math.abs(D.values[0] - D.expected_first) < 1e-9, "first value differs from the script's");
```

Use `class:"nohalo"` on text placed over a coloured shape.

## Questions (only when the explanation really leaves a decision)

Tabs go right after `.answer`, one per question. A tab must make sense read alone.

```html
<div class="tabs" id="tabs">
  <button data-t="t1">1. Short name</button>
  <button data-t="t2">2. Short name</button>
</div>
<div class="tab" id="t1">
<h2>Question 1: the question as a sentence</h2>
<div class="ask">Do A, or B?</div>
<div class="context">What this tab needs from the rest of the page, restated: terms, data, counts, units.</div>
<span class="tag real">Real numbers: source and count</span>
<div class="fig" id="f1"></div>
<table>
  <tr><th>Option</th><th>What it changes in the results, and what happens after this answer</th><th>For</th><th>Against</th></tr>
  <tr class="rec"><td><b>A (my recommendation)</b></td><td>The median falls from 20% to 15%; no refit needed.</td><td>...</td><td>...</td></tr>
  <tr><td><b>B</b></td><td>Nothing changes; the sentences stay as printed.</td><td>...</td><td>...</td></tr>
</table>
<div class="unknown"><b>Not known:</b> what was not measured or checked that bears on this choice.</div>
<div class="next">What happens next: what I do once you answer, and what stays as it is until then.</div>
</div>
```

After the last tab, with an example using the real option letters:

```html
<div class="reply">To answer, reply in one line, for example: <b>1A, 2B</b>.</div>
```

With no questions there are no `.ask`, tabs or `.reply`. Tabs without questions are only for pages covering several topics; a topic tab has no `.ask` and still restates its own context.
