/* The review page's own script: tabs, selections kept across a reload, and Send.
   It reads and writes form controls and text only, and never builds markup from data, so nothing
   the page shows can become code. It changes nothing by itself: Send hands a list of choices to
   the local server, which hands them to the session, whose script checks each one. */
(function () {
  "use strict";

  var data = JSON.parse(document.getElementById("page-data").textContent);
  var draftKey = "upkeep-review-draft:" + data.review_id;
  var tabKey = "upkeep-review-tab:" + data.review_id;
  var refusalsBeforeClosed = 2;
  var draft = { choices: {}, notes: {}, page_note: "", settled: {} };
  var locked = {};
  var waiting = {};
  var stale = false;
  var failedPolls = 0;
  var timer = null;
  var active = true;
  var closed = false;

  document.documentElement.classList.add("scripted");

  function byId(id) { return document.getElementById(id); }
  function all(selector, within) { return Array.prototype.slice.call((within || document).querySelectorAll(selector)); }

  function loadDraft() {
    try {
      var kept = JSON.parse(window.localStorage.getItem(draftKey));
      if (kept && typeof kept === "object") {
        draft.choices = kept.choices || {};
        draft.notes = kept.notes || {};
        draft.page_note = kept.page_note || "";
        draft.settled = kept.settled || {};
      }
    } catch (ignored) { /* A browser that keeps nothing still works, for this visit. */ }
  }

  function saveDraft() {
    try { window.localStorage.setItem(draftKey, JSON.stringify(draft)); } catch (ignored) { /* See loadDraft. */ }
  }

  function showTab(name) {
    all("[data-panel]").forEach(function (panel) { panel.classList.toggle("active", panel.getAttribute("data-panel") === name); });
    all("[data-tab]").forEach(function (button) { button.setAttribute("aria-selected", button.getAttribute("data-tab") === name ? "true" : "false"); });
    try { window.sessionStorage.setItem(tabKey, name); } catch (ignored) { /* See loadDraft. */ }
  }

  function firstTab() {
    var kept = null;
    try { kept = window.sessionStorage.getItem(tabKey); } catch (ignored) { /* See loadDraft. */ }
    if (kept && byId("panel-" + kept)) { return kept; }
    return all("[data-tab]")[0].getAttribute("data-tab");
  }

  function setChoice(number, value) {
    if (value) { draft.choices[number] = value; } else { delete draft.choices[number]; }
    all("input[name='choice-" + number + "']").forEach(function (radio) { radio.checked = radio.value === value; });
  }

  function restore() {
    Object.keys(draft.choices).forEach(function (number) { setChoice(number, draft.choices[number]); });
    Object.keys(draft.notes).forEach(function (number) {
      var box = byId("note-" + number);
      if (box) { box.value = draft.notes[number]; }
    });
    byId("page-note").value = draft.page_note;
  }

  function selection() {
    var numbers = {};
    Object.keys(draft.choices).forEach(function (number) { numbers[number] = true; });
    Object.keys(draft.notes).forEach(function (number) { if (draft.notes[number].trim()) { numbers[number] = true; } });
    return Object.keys(numbers).map(Number).filter(function (number) { return byId("item-" + number) && !locked[number]; }).sort(function (a, b) { return a - b; });
  }

  function typedFormOf(number) {
    var choice = draft.choices[number] || "";
    var note = (draft.notes[number] || "").trim();
    var parts = [];
    if (choice.indexOf("action:") === 0) {
      parts.push(choice.slice(7) + " " + number);
    } else {
      parts.push("item " + number);
      if (choice) {
        var label = byId("option-" + number + "-" + choice.slice(7));
        if (label) { parts.push("I mean: " + label.textContent); }
      }
    }
    if (note) { parts.push("(" + note + ")"); }
    return parts.join(" ");
  }

  function refreshSummary() {
    var numbers = selection();
    var asked = numbers.filter(function (number) {
      var item = byId("item-" + number);
      return draft.choices[number] === "action:approve" && item.getAttribute("data-asks") === "yes";
    }).length;
    byId("send-count").textContent = numbers.length + " of " + all("fieldset[data-number]").length + " items have a choice or a note. Nothing is sent until you press Send.";
    byId("send-asked").textContent = asked ? asked + " of these will be asked in the session before anything changes." : "";
    var typed = numbers.map(typedFormOf);
    if (draft.page_note.trim()) { typed.push(draft.page_note.trim()); }
    byId("typed-form").value = typed.join(", ");
    byId("send-button").disabled = closed || stale || !data.served || (numbers.length === 0 && !draft.page_note.trim());
  }

  function setResult(number, text, kind) {
    var slot = byId("result-" + number);
    if (!slot) { return; }
    slot.textContent = text;
    slot.hidden = !text;
    slot.className = "result " + (kind || "");
  }

  function lock(number, isLocked) {
    locked[number] = isLocked;
    var fieldset = byId("choose-" + number);
    if (fieldset) { all("input, textarea", fieldset).forEach(function (control) { control.disabled = isLocked; }); }
  }

  function say(text, isWarning) {
    var line = byId("send-status");
    line.textContent = text;
    line.className = isWarning ? "strong-warn" : "soft";
  }

  function forget(number) {
    delete draft.choices[number];
    delete draft.notes[number];
    all("input[name='choice-" + number + "']").forEach(function (radio) { radio.checked = false; });
    var box = byId("note-" + number);
    if (box) { box.value = ""; }
  }

  function applyStatus(status) {
    (status.batches || []).forEach(function (batch) {
      (batch.items || []).forEach(function (entry) {
        var text = entry.state_label + (entry.detail ? ": " + entry.detail : "");
        var settled = entry.final === true;
        var seen = batch.batch_id + ":" + entry.number;
        setResult(entry.number, text, entry.state);
        waiting[entry.number] = !settled;
        // An applied item has nothing left to choose. Anything else that settled can be chosen again.
        lock(entry.number, !settled || entry.state === "applied");
        if (settled && !draft.settled[seen]) {
          // Once only, so that a reload does not clear what was chosen since.
          draft.settled[seen] = true;
          if (entry.state !== "refused") { forget(entry.number); }
          saveDraft();
        }
      });
    });
    if (status.review_id !== data.review_id) {
      stale = true;
      byId("reload-notice").hidden = false;
    }
    if (status.closing) {
      serverClosed(status.closing);
    }
    refreshSummary();
  }

  function serverClosed(reason) {
    if (closed) { return; }
    closed = true;
    if (timer) { window.clearTimeout(timer); }
    byId("server-closed").hidden = false;
    if (reason) { byId("closed-reason").textContent = reason; }
    byId("typed-details").open = true;
    say("Send is off, because the server has closed.", true);
    refreshSummary();
  }

  function post(path, body) {
    return window.fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer"
    });
  }

  function anyPending() { return Object.keys(waiting).some(function (number) { return waiting[number]; }); }

  function schedule() {
    if (closed) { return; }
    timer = window.setTimeout(poll, anyPending() ? data.poll_ms : data.heartbeat_ms);
  }

  function poll() {
    var wasActive = active;
    active = false;
    post("status", { active: wasActive }).then(function (response) {
      if (!response.ok) { throw new Error("status " + response.status); }
      return response.json();
    }).then(function (status) {
      failedPolls = 0;
      applyStatus(status);
      schedule();
    }).catch(function () {
      failedPolls += 1;
      if (failedPolls >= refusalsBeforeClosed) { serverClosed(""); } else { timer = window.setTimeout(poll, data.poll_ms); }
    });
  }

  function send() {
    var numbers = selection();
    var items = numbers.map(function (number) {
      return { number: number, choice: draft.choices[number] || "", note: draft.notes[number] || "" };
    });
    byId("send-button").disabled = true;
    say("Sending...", false);
    post("send", { review_id: data.review_id, page_note: draft.page_note, items: items }).then(function (response) {
      return response.json().then(function (body) { return { code: response.status, body: body }; });
    }).then(function (answer) {
      var body = answer.body;
      (body.refused || []).forEach(function (entry) { setResult(entry.number, "Refused: " + entry.reason, "refused"); });
      if (answer.code === 200) {
        (body.accepted || []).forEach(function (number) {
          setResult(number, "Sent. Waiting for the session.", "sent");
          waiting[number] = true;
          lock(number, true);
        });
        draft.page_note = "";
        byId("page-note").value = "";
        saveDraft();
        say("Sent " + (body.accepted || []).length + " to the session" + ((body.refused || []).length ? ", " + body.refused.length + " refused." : ". Results appear on each item."), false);
      } else {
        if (body.reload) {
          stale = true;
          byId("reload-notice").hidden = false;
        }
        say(body.message || "The server refused this.", true);
      }
      refreshSummary();
      active = true;
      if (timer) { window.clearTimeout(timer); }
      schedule();
    }).catch(function () {
      say("Send did not reach the server. Your choices are kept here. You can type them in the session.", true);
      byId("typed-details").open = true;
      refreshSummary();
    });
  }

  function fillRecommended(name) {
    var filled = 0;
    all("fieldset[data-number]", byId("panel-" + name)).forEach(function (fieldset) {
      var number = fieldset.getAttribute("data-number");
      var recommended = fieldset.getAttribute("data-recommended");
      if (recommended && !draft.choices[number] && !locked[number]) {
        setChoice(number, recommended);
        filled += 1;
      }
    });
    saveDraft();
    say("Filled in " + filled + ". Change any of them, then press Send. Nothing has been sent.", false);
    refreshSummary();
  }

  function clearChoices(name) {
    all("fieldset[data-number]", byId("panel-" + name)).forEach(function (fieldset) {
      var number = fieldset.getAttribute("data-number");
      if (!locked[number]) { setChoice(number, ""); }
    });
    saveDraft();
    refreshSummary();
  }

  function wire() {
    all("[data-tab]").forEach(function (button) {
      button.addEventListener("click", function () { showTab(button.getAttribute("data-tab")); });
    });
    all("input[type=radio]").forEach(function (radio) {
      radio.addEventListener("change", function () {
        draft.choices[radio.getAttribute("data-number")] = radio.value;
        saveDraft();
        refreshSummary();
      });
    });
    all("textarea[data-number]").forEach(function (box) {
      box.addEventListener("input", function () {
        draft.notes[box.getAttribute("data-number")] = box.value;
        saveDraft();
        refreshSummary();
      });
    });
    byId("page-note").addEventListener("input", function () {
      draft.page_note = byId("page-note").value;
      saveDraft();
      refreshSummary();
    });
    all("[data-fill]").forEach(function (button) {
      button.addEventListener("click", function () { fillRecommended(button.getAttribute("data-fill")); });
    });
    all("[data-clear]").forEach(function (button) {
      button.addEventListener("click", function () { clearChoices(button.getAttribute("data-clear")); });
    });
    byId("send-button").addEventListener("click", send);
    ["click", "keydown", "scroll", "input"].forEach(function (name) {
      window.addEventListener(name, function () { active = true; }, { passive: true, capture: true });
    });
  }

  loadDraft();
  wire();
  restore();
  showTab(firstTab());
  refreshSummary();
  if (data.served) {
    poll();
  } else {
    say(data.off_reason, true);
    byId("typed-details").open = true;
  }
}());
