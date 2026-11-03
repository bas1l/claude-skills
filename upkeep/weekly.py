"""The weekly pass: memory changes checked and applied, and proposals researched and stored.

Order of a run:

    1. If this ISO week's pass already succeeded, do nothing.
    2. Run the daily pass if none completed today.
    3. For each project: one tool-less model call over its notes, memories and source. Each
       suggested change then goes through the script checks of ``weekly_gate``. One more tool-less
       call for the whole pass then judges what is left, given only each claim and its quotes.
    4. One tool-less call across projects for proposals, checked against the routes.
    5. Research for new skills, plugins and tool servers. If search is unavailable the pass
       fails here, before any proposal or memory is written.
    6. Write proposals. Apply memory changes as one commit per folder, or mark them
       ``would_apply`` if ``apply_memory_changes`` is false in the local settings.
    7. Write the report and the review, and commit the data folder.

Idempotent per ISO week. A run reuses model replies whose input is unchanged. A folder holding
this week's commit is never written again, and a run that succeeded does nothing the next time.
What was applied is recorded before it is written, in ``applied_changes.py``, and every report of
the week takes applied changes from there, so a retry or a crash cannot lose them. A retry also
keeps the proposals and rejections of the run before it, whose notes are used up by then.
A run with application off does not count against one with it on, and does not use up notes.
It also researches held items, which stay held, so that it proves the research path in a thin week.

Written under the data folder:

    reports/YYYY-Www/report.json     the format below, which the review step reads
    reports/YYYY-Www/review.json     the review built from it; see review_data.py
    reports/YYYY-Www/review.html     the page rendered from that, by review_page.py
    reports/YYYY-Www/groups/         model replies by group, with a hash of their input
    reports/YYYY-Www/research/       research records
    reports/YYYY-Www/usage.jsonl     one line per model call
    reports/YYYY-Www/applied.json    changes applied this week, written before the files
    proposals/YYYY-Www/<id>/         proposal.json, and SKILL.md for a skill's draft
    state/weekly.json                windows and counts used up by a pass that applied its changes

report.json, schema version 1 (checked by ``schemas.validate_weekly_report``):

    week, run_id, generated_at, status ok|failed|budget_stopped, stop_reason
    apply_enabled      false means nothing touched a memory folder
    coverage           windows, sessions, notes, first, last, days_of_notes, windows_skipped,
                       memory_notes, proposal_notes
    memory_changes[]   id, project_folder, memory, action, claim, old_text, endorsement, quote,
                       assistant_statement, session, source {notes, note_index}, new_evidence,
                       outcome applied|would_apply, commit, before, after (the file's text)
    rejected[]         subject, project_folder, reason, detail, claim, quote, source
    proposals[]        id, kind (skill, plugin, hook, mcp, global_rule, memory_fact, memory_split_claim,
                       memory_deletion, memory_revision, item_revision), change_type, title,
                       what, why, target, basis, evidence, exact_change, draft_path, research,
                       status open|already_open, project_folder
    held[]             the same fields, status held:<reason>; not written under proposals/
    failures_ranked[]  ref, tool, signature, commands_lost, sessions; by commands lost
    before_after[]     per earlier applied change: entries before and since, still in the file
    usage              model_calls, tokens, cost_usd

A failed run writes the report too, with empty lists for what it did not reach.
"""
from __future__ import annotations

import applied_changes
import argparse
import glob
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

import backfill
import daily
import extract
import ledger
import memory_store
import model_call
import pass_support
import render
import research
import review_data
import schemas
import sessions
import stance_check
import transcripts
import weekly_gate
import weekly_notes
from config import Config, LocalSettings, load_config, load_local_settings

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_BUDGET_STOPPED = "budget_stopped"
EXIT_CODES = {STATUS_OK: 0, STATUS_FAILED: 1, STATUS_BUDGET_STOPPED: 3}
RESULT_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 2
OLD_STATE_SCHEMA_VERSION = 1
PROPOSAL_SCHEMA_VERSION = 1

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
MEMORY_PROMPT = os.path.join(PROMPTS_DIR, "weekly_memory.md")
VERIFY_PROMPT = os.path.join(PROMPTS_DIR, "weekly_verify.md")
PROPOSALS_PROMPT = os.path.join(PROMPTS_DIR, "weekly_proposals.md")

KIND_MEMORY_FACT = "memory_fact"
KIND_MEMORY_SPLIT = "memory_split_claim"
KIND_MEMORY_DELETION = "memory_deletion"
KIND_MEMORY_REVISION = "memory_revision"
KIND_ITEM_REVISION = "item_revision"
STATUS_OPEN = "open"
STATUS_ALREADY_OPEN = "already_open"
STATUS_HELD_PREFIX = "held:"
REJECT_RESEARCH = "research_rejected"
WEEKLY_SOURCE_PREFIX = "weekly/"
HELD_RESEARCH_LIMIT = "research_limit_for_this_pass"
SKILL_DRAFT_FILE = "SKILL.md"
THIS_RUN_TOOL = "upkeep-weekly"


def iso_week_of(moment: datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def report_dir_of(config: Config, week: str) -> str:
    return os.path.join(config.paths.data_dir, "reports", week)


_write_json = pass_support.write_json
_read_text = pass_support.read_text
_read_json = pass_support.read_json


def weekly_state_path(config: Config) -> str:
    return os.path.join(config.paths.data_dir, "state", "weekly.json")


def load_weekly_state(config: Config) -> dict[str, Any]:
    """Which note windows and which counts files are used up. No file means none, since the first
    pass creates it. Version 1 held both in one map, and which of the two a key stood for cannot be
    told from it, so a key counts as used up in both: nothing used up is read again. A window a
    version 1 pass wrongly used up stays used up."""
    path = weekly_state_path(config)
    if not os.path.exists(path):
        return {"schema_version": STATE_SCHEMA_VERSION, "consumed_windows": {}, "consumed_counts": {}}
    state = _read_json(path)
    if state.get("schema_version") == OLD_STATE_SCHEMA_VERSION:
        return {"schema_version": STATE_SCHEMA_VERSION, "consumed_windows": dict(state["consumed_windows"]), "consumed_counts": dict(state["consumed_windows"])}
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(f"{path}: schema_version {state.get('schema_version')!r}")
    return state


def week_already_done(config: Config, week: str, apply_enabled: bool) -> bool:
    """A retry does nothing after a success. A dry run does not stop a real one."""
    path = os.path.join(report_dir_of(config, week), "report.json")
    if not os.path.exists(path):
        return False
    report = _read_json(path)
    return report["status"] == STATUS_OK and (report["apply_enabled"] or not apply_enabled)


def daily_completed_on(config: Config, local_date: datetime) -> bool:
    """True if a daily pass that started on this local date ended clean."""
    pattern = os.path.join(glob.escape(config.paths.data_dir), "logs", f"daily-{local_date.strftime('%Y%m%d')}-*.result.json")
    return any(_read_json(path)["status"] == daily.STATUS_OK for path in glob.glob(pattern))


_cached_or_called_reply = pass_support.cached_or_called_reply


def _declined_lines(decisions: Sequence[Mapping[str, Any]], scope_test: Callable[[str], bool]) -> str:
    return "\n".join(
        f"{item['decided_at']} {item['decision']}: {item['kind']} {item['name']}: {item['claim']}"
        for item in decisions
        if scope_test(item["scope"])
    )


def _memory_folder(config: Config, project_folder: str) -> str:
    return os.path.join(config.paths.projects_dir, project_folder, "memory")


def _add_problem(config: Config, what: str, error: Exception) -> None:
    ledger.add_item_problems(ledger.ledgers_dir_of(config.paths.data_dir), [{"what": what, "detail": f"{type(error).__name__}: {error}"}])


def _memories_input(config: Config, project_folder: str) -> str:
    """The memories of a project, each with its recorded entries. A founding reason appears only
    if verified: a backfilled, unverified reason is not evidence for anything. A ledger that cannot
    be read is listed for the review, and the memory is shown without it."""
    folder = _memory_folder(config, project_folder)
    ledgers_dir = ledger.ledgers_dir_of(config.paths.data_dir)
    if not os.path.isdir(folder):
        return ""
    parts = []
    for name in memory_store.list_files(folder):
        if not name.endswith(".md"):
            continue
        text = memory_store.read_memory_file(os.path.join(folder, name))
        lines = [f'<memory name="{name[:-3]}">\n{render.neutralise_tags(text)}\n</memory>']
        item = ledger.ItemId(ledger.project_scope(project_folder), ledger.KIND_MEMORY, name[:-3])
        if ledger.item_exists(ledgers_dir, item):
            try:
                document = ledger.load_ledger(ledgers_dir, item)
            except ledger.UNREADABLE as error:
                _add_problem(config, f"memory {name[:-3]} in {project_folder}", error)
            else:
                if document["founding"]["status"] == schemas.FOUNDING_VERIFIED:
                    lines.append(render.neutralise_tags(f"verified founding reason: {document['founding']['reason']}"))
                lines.extend(
                    render.neutralise_tags(f"recorded {entry['direction']}, by {entry['who']} ({entry['basis']}): {entry['what']}")
                    for entry in document["entries"]
                )
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _memory_group_input(
    group: weekly_notes.MemoryGroup, store: weekly_notes.SourceStore, config: Config, decisions: Sequence[Mapping[str, Any]]
) -> tuple[str, dict[str, weekly_notes.NoteRecord]]:
    session_refs = {window.key: f"s{position}" for position, window in enumerate(group.windows, 1)}
    refs = {f"n{position}": record for position, record in enumerate(group.records, 1)}
    notes = render.neutralise_tags("\n".join(weekly_notes.render_note(ref, session_refs[record.window.key], record) for ref, record in refs.items()))
    sources = "\n".join(
        f'<session ref="{session_refs[window.key]}">{store.exchanges(window)}\n</session>' for window in group.windows
    )
    scope = ledger.project_scope(group.project_folder)
    declined = render.neutralise_tags(_declined_lines(decisions, lambda value: value == scope))
    text = (
        f"<memories>\n{_memories_input(config, group.project_folder)}\n</memories>\n\n"
        f"<declined>\n{declined}\n</declined>\n\n"
        f"<notes>\n{notes}\n</notes>\n\n"
        f"<source>\n{sources}\n</source>\n"
    )
    return text, refs


def _existing_items_input(ledgers_dir: str) -> str:
    problems: list[dict[str, str]] = []
    text = "\n".join(
        f"{document['identity']['kind']}: {document['identity']['name']}"
        for document in ledger.iter_ledgers(ledgers_dir, problems)
        if document["identity"]["scope"] == ledger.SCOPE_GLOBAL
    )
    ledger.add_item_problems(ledgers_dir, problems)
    return text


def _hook_settings_input(config: Config) -> str:
    """The hooks block as it stands, because a hook proposal must show the exact command."""
    settings = _read_json(config.inventory.settings_file)
    return json.dumps(settings["hooks"], ensure_ascii=False, indent=1) if "hooks" in settings else ""


def _proposals_input(
    records: Sequence[weekly_notes.NoteRecord],
    failures: Sequence[weekly_notes.FailureCount],
    procedures: Sequence[weekly_notes.ProcedureCount],
    config: Config,
    decisions: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, weekly_notes.NoteRecord]]:
    chosen = [record for record in records if weekly_notes.is_proposal_note(record)]
    session_refs: dict[str, str] = {}
    for record in chosen:
        session_refs.setdefault(record.window.session_id, f"s{len(session_refs) + 1}")
    refs = {f"n{position}": record for position, record in enumerate(chosen, 1)}
    notes = render.neutralise_tags("\n".join(weekly_notes.render_note(ref, session_refs[record.window.session_id], record) for ref, record in refs.items()))
    shown = failures[: config.weekly.failures_shown]
    failure_lines = render.neutralise_tags("\n".join(
        json.dumps({
            "ref": item.ref, "tool": item.tool, "error_start": item.signature, "commands_lost": item.commands_lost,
            "sessions": [session_refs.get(session, "other") for session in item.sessions],
        }, ensure_ascii=False)
        for item in shown
    ))
    procedure_lines = render.neutralise_tags("\n".join(
        json.dumps({"ref": item.ref, "name": item.name, "calls": item.calls, "session": session_refs.get(item.session_id, "other")}, ensure_ascii=False)
        for item in procedures
    ))
    declined = render.neutralise_tags(_declined_lines(decisions, lambda value: value == ledger.SCOPE_GLOBAL))
    weekly = config.weekly
    text = (
        f"Thresholds: recurrence in {weekly.recurrence_sessions} sessions; costly once at "
        f"{weekly.costly_once_tool_calls} calls; failures at {weekly.failure_min_commands_lost} commands lost.\n\n"
        f"<existing_items>\n{render.neutralise_tags(_existing_items_input(ledger.ledgers_dir_of(config.paths.data_dir)))}\n</existing_items>\n\n"
        f"<hook_settings>\n{render.neutralise_tags(_hook_settings_input(config))}\n</hook_settings>\n\n"
        f"<declined>\n{declined}\n</declined>\n\n"
        f"<notes>\n{notes}\n</notes>\n\n"
        f"<failures>\n{failure_lines}\n</failures>\n\n"
        f"<procedures>\n{procedure_lines}\n</procedures>\n"
    )
    return text, refs


def proposal_id(kind: str, name: str) -> str:
    words = " ".join(weekly_notes.plain_words(name))
    return f"{kind}-{hashlib.sha256(f'{kind}|{words}'.encode('utf-8')).hexdigest()[:10]}"


def _evidence_of(cited: Sequence[weekly_notes.NoteRecord], **extra: Any) -> dict[str, Any]:
    return {
        "notes": [
            {"session": record.window.session_id, "source": record.source_json(), "what": record.values["what"], "quote": record.values["endorsement_quote"]}
            for record in cited
        ],
        **extra,
    }


def _proposal_record(
    proposal: schemas.Proposal,
    refs: Mapping[str, weekly_notes.NoteRecord],
    failures: Mapping[str, weekly_notes.FailureCount],
    procedures: Mapping[str, weekly_notes.ProcedureCount],
    status: str,
) -> dict[str, Any]:
    failure = failures.get(proposal.failure)
    procedure = procedures.get(proposal.procedure)
    return {
        "id": proposal_id(proposal.kind, f"{proposal.target} {proposal.title}"),
        "kind": proposal.kind,
        "change_type": proposal.change_type,
        "title": proposal.title,
        "what": proposal.what,
        "why": proposal.why,
        "target": proposal.target,
        "basis": proposal.basis,
        "evidence": _evidence_of(
            [refs[ref] for ref in proposal.notes if ref in refs],
            failure=None if failure is None else failure.to_json(),
            procedure=None if procedure is None else {"name": procedure.name, "calls": procedure.calls, "session": procedure.session_id},
        ),
        "exact_change": proposal.exact_change,
        "draft_path": None,
        "research": None,
        "status": status,
        "project_folder": "",
        "_draft": proposal.draft,
        "_description": proposal.generic_description,
    }


def _memory_proposal(kind: str, name: str, folder: str, title: str, what: str, why: str, exact: str, evidence: dict[str, Any], distinct: str = "") -> dict[str, Any]:
    """``distinct`` keeps two proposals on one memory apart, which would otherwise overwrite
    each other's folder and be taken for each other in later weeks."""
    return {
        "id": proposal_id(kind, f"{folder} {name} {distinct}"),
        "kind": kind,
        "change_type": schemas.CHANGE_NEW if kind in (KIND_MEMORY_FACT, KIND_MEMORY_SPLIT) else schemas.CHANGE_EXISTING,
        "title": title,
        "what": what,
        "why": why,
        "target": name,
        "basis": "",
        "evidence": evidence,
        "exact_change": exact,
        "draft_path": None,
        "research": None,
        "status": STATUS_OPEN,
        "project_folder": folder,
        "_draft": "",
        "_description": "",
    }


def _private_material(config: Config, local: LocalSettings, windows: Sequence[weekly_notes.Window], discovered: Sequence[sessions.SessionFiles]) -> research.PrivateMaterial:
    names = [os.path.basename(os.path.normpath(window.project_cwd)) for window in windows]
    return pass_support.private_material(config, local, names, [files.project_folder for files in discovered])


def _research_candidates(
    candidates: list[dict[str, Any]],
    private: research.PrivateMaterial,
    caller: pass_support.Caller,
    week: str,
    rejected: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Research what needs it. Search failing raises, and no proposal gets written."""
    config = caller.config
    kept = []
    held = []
    researched = 0
    for candidate in candidates:
        if not (candidate["kind"] in schemas.RESEARCHED_KINDS and candidate["change_type"] == schemas.CHANGE_NEW):
            kept.append(candidate)
            continue
        if researched >= config.research.max_per_pass:
            held.append({**candidate, "status": f"{STATUS_HELD_PREFIX}{HELD_RESEARCH_LIMIT}"})
            continue
        researched += 1
        description = candidate["_description"]
        digest = hashlib.sha256(description.encode("utf-8")).hexdigest()
        cache = os.path.join(report_dir_of(config, week), "research", f"{candidate['id']}.json")
        if os.path.exists(cache) and _read_json(cache)["description_sha256"] == digest:
            record = _read_json(cache)["research"]
        else:
            try:
                record = research.research_description(
                    description, private, config, caller.usage_log, caller.remaining(), caller.tracked(f"research:{candidate['id']}")
                )
            except research.ResearchRejectedError as error:
                rejected.append({
                    "subject": candidate["title"], "project_folder": "", "reason": REJECT_RESEARCH, "detail": str(error),
                    "claim": candidate["what"], "quote": "", "source": None,
                })
                continue
            record, _ = extract.redact_value(record, config)
            _write_json(cache, {"description_sha256": digest, "research": record})
        kept.append({**candidate, "research": record})
    return kept, held


def _open_elsewhere(config: Config, week: str) -> set[str]:
    """Proposal ids stored by an earlier week: left open, they are not written again."""
    root = os.path.join(config.paths.data_dir, "proposals")
    found = set()
    for path in glob.glob(os.path.join(glob.escape(root), "*", "*", "proposal.json")):
        parts = os.path.normpath(path).split(os.sep)
        if parts[-3] != week:
            found.add(parts[-2])
    return found


def _store_proposals(proposals: list[dict[str, Any]], config: Config, week: str) -> tuple[list[dict[str, Any]], int]:
    """Write each proposal under its week, with a skill's draft beside it. Returns public records."""
    earlier = _open_elsewhere(config, week)
    stored = []
    redacted_total = 0
    for proposal in proposals:
        draft = proposal["_draft"]
        record = {key: value for key, value in proposal.items() if not key.startswith("_")}
        if record["id"] in earlier:
            record["status"] = STATUS_ALREADY_OPEN
            stored.append(record)
            continue
        directory = os.path.join(config.paths.data_dir, "proposals", week, record["id"])
        os.makedirs(directory, exist_ok=True)
        if record["kind"] == "skill":
            with open(os.path.join(directory, SKILL_DRAFT_FILE), "w", encoding="utf-8", newline="\n") as handle:
                handle.write(draft)
            record["draft_path"] = f"proposals/{week}/{record['id']}/{SKILL_DRAFT_FILE}"
        record, redacted = extract.redact_value(record, config)
        redacted_total += redacted
        _write_json(os.path.join(directory, "proposal.json"), {"schema_version": PROPOSAL_SCHEMA_VERSION, "week": week, **record})
        stored.append(record)
    return stored, redacted_total


def _revision_declined(decisions: Sequence[Mapping[str, Any]], identity: Mapping[str, str], cited: Sequence[Mapping[str, Any]]) -> bool:
    """A flag stays up for as long as its entries stand, so a rejection has to be read here: this
    revision stays out until an entry behind the flag is newer than the rejection."""
    latest = max(datetime.fromisoformat(entry["date"]) for entry in cited)
    return any(
        decision["scope"] == identity["scope"] and decision["kind"] == identity["kind"] and decision["name"].casefold() == identity["name"].casefold()
        and decision["action"] == schemas.ACTION_REVISION and datetime.fromisoformat(decision["decided_at"]) >= latest
        for decision in decisions
    )


def _revision_proposals(
    flags: Sequence[Mapping[str, Any]], config: Config, ledgers_dir: str, changed: set[tuple[str, str]], decisions: Sequence[Mapping[str, Any]], found: backfill.InventoryScan
) -> list[dict[str, Any]]:
    """A flag raises a proposal to revise, and never edits or deletes. An item gone from the setup,
    a memory changed in this pass or by the weekly pass since the entries behind the flag, or a
    revision rejected since them is passed over. An item that could not be read cannot be called
    gone, so its flag stands."""
    proposals = []
    for flag in flags:
        identity = flag["identity"]
        item = ledger.ItemId(**identity)
        document = ledger.load_ledger(ledgers_dir, item)
        cited = [entry for entry in document["entries"] if entry["id"] in flag["entries"]]
        if _revision_declined(decisions, identity, cited):
            continue
        if identity["kind"] == ledger.KIND_MEMORY:
            folder = identity["scope"][len(ledger.SCOPE_PROJECT_PREFIX):]
            if (folder, identity["name"]) in changed:
                continue
            if not os.path.exists(os.path.join(_memory_folder(config, folder), f"{identity['name']}.md")):
                continue
            applied = [entry["date"] for entry in document["entries"] if entry["source"]["notes"].startswith(WEEKLY_SOURCE_PREFIX)]
            if applied and all(datetime.fromisoformat(entry["date"]) <= max(map(datetime.fromisoformat, applied)) for entry in cited):
                continue
            kind = KIND_MEMORY_REVISION
        else:
            if not found.could_be_there(identity):
                continue
            folder = ""
            kind = KIND_ITEM_REVISION
        shown = ("date", "session", "who", "basis", "what", "quote")
        support = [entry for entry in document["entries"] if entry["id"] in flag["entries_for"]]
        evidence = {"identity": identity, "flag_reason": flag["reason"], "entries": [{k: entry[k] for k in shown} for entry in cited], "entries_for": [{k: entry[k] for k in shown} for entry in support]}
        proposals.append(_memory_proposal(
            kind, identity["name"], folder, f"Review {identity['kind']} {identity['name']}",
            "Read this item against what was said about it, and revise it if it no longer holds.",
            f"It lost balance: {flag['reason']}.", "", evidence,
        ))
    return proposals


def _split_proposal(item: weekly_gate.ScreenedChange, sibling: str) -> dict[str, Any]:
    """A claim whose source statement also gave a rejected claim. A create or add can be written by
    approving it. A replace or remove changes text already there, so it is read and revised by hand."""
    change = item.change
    why = f"From the same statement of the user, this other claim was rejected: {sibling}. Saved alone, this one could say something the user did not say, so someone reads them together."
    evidence = _evidence_of([item.record], change={
        "action": change.action, "claim": change.claim, "old_text": change.old_text, "endorsement": change.endorsement, "quote": change.quote,
        "assistant_statement": change.assistant_statement, "session": item.record.window.session_id,
    })
    if change.action in (schemas.ACTION_CREATE, schemas.ACTION_ADD):
        return _memory_proposal(KIND_MEMORY_SPLIT, change.memory, item.project_folder, f"Half of a statement: {change.memory}", change.claim, why, change.claim, evidence, distinct=change.claim)
    return _memory_proposal(
        KIND_MEMORY_REVISION, change.memory, item.project_folder, f"Half of a statement: {change.memory}",
        f"{change.action} in memory {change.memory}: {change.old_text} -> {change.claim}", why, "", {**evidence, "identity": {"scope": ledger.project_scope(item.project_folder), "kind": ledger.KIND_MEMORY, "name": change.memory}},
        distinct=change.claim,
    )


def _fact_and_deletion_proposals(state: weekly_gate.MemoryGateState, title_max_chars: int) -> list[dict[str, Any]]:
    proposals = [_split_proposal(item, sibling) for item, sibling in state.split_proposals]
    for fact, record, folder in state.fact_proposals:
        proposals.append(_memory_proposal(
            KIND_MEMORY_FACT, fact.memory, folder, fact.title[: title_max_chars], fact.claim,
            "A lasting fact the user never reacted to, so someone reads it before it is saved.",
            fact.claim, _evidence_of([record]), distinct=fact.claim,
        ))
    for gated in state.deletion_proposals:
        change = gated.change
        whole_file = change.action == schemas.ACTION_DELETE
        proposals.append(_memory_proposal(
            KIND_MEMORY_DELETION, f"{change.memory} {change.old_text}", gated.project_folder,
            f"Delete memory {change.memory}" if whole_file else f"Remove from memory {change.memory}",
            f"Delete this whole file: {change.memory}. It holds: {change.old_text}" if whole_file else f"Take this out: {change.old_text}",
            "Deleting a whole memory always waits for review." if whole_file else "Past the limit on deletions in one pass, so this one waits for review.",
            f"{change.action} {change.memory}: {change.old_text}",
            _evidence_of([gated.record], change={
                "claim": change.claim, "endorsement": change.endorsement, "quote": change.quote,
                "assistant_statement": change.assistant_statement, "session": gated.record.window.session_id,
            }),
        ))
    return proposals


def _writes_of_folder(
    changes: Sequence[weekly_gate.GatedChange], state: weekly_gate.MemoryGateState, config: Config
) -> tuple[list[memory_store.FileWrite], list[memory_store.IndexEdit]]:
    writes = []
    index_edits = []
    names = sorted({gated.change.memory for gated in changes})
    for name in names:
        key = (changes[0].project_folder, name)
        file_name = f"{name}.md"
        writes.append(memory_store.FileWrite(file_name, state.originals[key], state.current[key]))
        for gated in changes:
            change = gated.change
            if change.memory != name:
                continue
            if change.action == schemas.ACTION_CREATE:
                hook = change.claim[: config.weekly.index_hook_chars]
                index_edits.append(memory_store.IndexEdit(file_name, memory_store.index_line(change.title[: config.weekly.title_max_chars], file_name, hook)))
            elif change.action == schemas.ACTION_DELETE:
                index_edits.append(memory_store.IndexEdit(file_name, None))
    return writes, index_edits


def _record_in_ledger(record: Mapping[str, Any], week: str, now: datetime, ledgers_dir: str) -> None:
    """A change's ledger entry, from its applied record. Safe to repeat: an entry id is added once."""
    item = ledger.ItemId(ledger.project_scope(record["project_folder"]), ledger.KIND_MEMORY, record["memory"])
    if record["action"] == schemas.ACTION_CREATE:
        ledger.ensure_ledger(
            ledgers_dir, item,
            {"reason": record["claim"], "status": schemas.FOUNDING_VERIFIED, "source": "discussion"},
            {"status": schemas.LIMIT_NOT_STATED, "text": None},
            {"status": schemas.ORIGIN_TRACED, "session": record["session"], "project_folder": record["project_folder"], "at": now.isoformat(), "tool": THIS_RUN_TOOL, "creating_call_found": True},
            now.isoformat(),
        )
    basis = schemas.BASIS_DIRECT if record["endorsement"] == schemas.ENDORSED_SAID else record["endorsement"]
    ledger.append_entry(ledgers_dir, item, {
        "id": record["id"],
        "date": now.isoformat(),
        "session": record["session"],
        "project_folder": record["project_folder"],
        "direction": schemas.STANCE_AGAINST if record["action"] in schemas.DELETING_ACTIONS else schemas.STANCE_FOR,
        "who": schemas.WHO_USER,
        "basis": basis,
        "what": f"{record['action']}: {record['claim']}",
        "quote": record["quote"],
        "quote_check": schemas.QUOTE_VERIFIED,
        "origin_of_point": "user",
        "source": {"notes": f"{WEEKLY_SOURCE_PREFIX}{week}/{record['id']}", "note_index": record["source"]["note_index"]},
    })


def _mark_folder_committed(config: Config, journal: dict[str, Any], folder_name: str, commit: str) -> None:
    applied_changes.mark_committed(journal["folders"][folder_name], commit)
    applied_changes.save(config, journal)


def _record_folder_in_ledger(config: Config, journal: dict[str, Any], folder_name: str, now: datetime) -> None:
    """Entries for a folder's changes, once. One whose ledger cannot be read is listed for the
    review and tried again by the next run; the change itself is already made and stays in the review."""
    entry = journal["folders"][folder_name]
    recorded = True
    for record in entry["changes"]:
        try:
            _record_in_ledger(record, journal["week"], now, ledger.ledgers_dir_of(config.paths.data_dir))
        except ledger.UNREADABLE as error:
            _add_problem(config, f"memory {record['memory']} in {folder_name}", error)
            recorded = False
    entry["ledger_recorded"] = recorded
    applied_changes.save(config, journal)


def _sync_items(config: Config, now: datetime) -> None:
    synced = backfill.sync_items(config, now)
    ledger.add_item_problems(ledger.ledgers_dir_of(config.paths.data_dir), synced["item_problems"])


def _reconcile_applied(config: Config, week: str, weekly_state: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Finish what a crash left, in every week on record: folders settled, ledger entries added, and
    for an earlier week, its windows used up. Returns changes no report has shown from earlier weeks."""
    applied_changes.settle_folders(config)
    unreported = []
    windows_before = len(weekly_state["consumed_windows"])
    for held_week in applied_changes.weeks_on_disk(config):
        journal = applied_changes.load(config, held_week)
        for folder_name, entry in applied_changes.committed_entries(journal):
            if not entry["ledger_recorded"]:
                _sync_items(config, now)
                _record_folder_in_ledger(config, journal, folder_name, now)
            if held_week < week and not entry["reported"]:
                unreported.extend(entry["changes"])
                for key in entry["windows"]:
                    weekly_state["consumed_windows"][key] = held_week
    if len(weekly_state["consumed_windows"]) != windows_before:
        _write_json(weekly_state_path(config), weekly_state)
    return unreported


def _mark_reported(config: Config, week: str) -> None:
    for held_week in applied_changes.weeks_on_disk(config):
        if held_week <= week:
            journal = applied_changes.load(config, held_week)
            for _, entry in applied_changes.committed_entries(journal):
                entry["reported"] = True
            applied_changes.save(config, journal)


def _apply_changes(
    state: weekly_gate.MemoryGateState, config: Config, week: str, run_id: str, now: datetime, windows: Sequence[weekly_notes.Window]
) -> tuple[list[dict[str, Any]], list[dict[str, str]], int]:
    """Apply per folder, recording each before writing it. Returns changes refused at the last moment,
    folders that failed, and secret patterns redacted from the record. A folder holding this week's
    commit is left alone."""
    journal = applied_changes.load(config, week)
    _sync_items(config, now)
    redacted_total = 0
    conflicts: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    by_folder: dict[str, list[weekly_gate.GatedChange]] = {}
    for gated in state.accepted:
        by_folder.setdefault(gated.project_folder, []).append(gated)
    for folder_name, changes in sorted(by_folder.items()):
        folder = _memory_folder(config, folder_name)
        if memory_store.week_already_applied(folder, week):
            errors.append({"project_folder": folder_name, "error": f"already holds a commit of {week}; its changes were not applied again"})
            continue
        writes, index_edits = _writes_of_folder(changes, state, config)
        message = f"Upkeep weekly {week}, run {run_id}: {len(changes)} memory changes"

        def record_before_writing(left_alone: Sequence[str], written: Sequence[Mapping[str, Any]]) -> None:
            nonlocal redacted_total
            records, redacted = extract.redact_value(
                [_change_record(gated, schemas.OUTCOME_APPLIED, None) for gated in changes if f"{gated.change.memory}.md" not in left_alone], config
            )
            redacted_total += redacted
            journal["folders"][folder_name] = {
                "status": applied_changes.STATUS_PREPARED, "run_id": run_id, "commit": None, "changes": records, "written": list(written),
                "windows": [window.key for window in windows if window.project_folder == folder_name],
                "ledger_recorded": False, "reported": False,
            }
            applied_changes.save(config, journal)

        try:
            outcome = memory_store.apply_memory_writes(folder, writes, index_edits, config.memory, week, message, record_before_writing)
        except memory_store.MemoryStoreError as error:
            errors.append({"project_folder": folder_name, "error": str(error)})
            continue
        for gated in changes:
            if f"{gated.change.memory}.md" in outcome["conflicts"]:
                conflicts.append({
                    "subject": gated.change.memory, "project_folder": folder_name, "reason": "changed_during_the_pass",
                    "detail": "a live session changed this file after the change was worked out",
                    "claim": gated.change.claim, "quote": gated.change.quote, "source": gated.record.source_json(),
                })
        if outcome["commit"] is not None:
            _mark_folder_committed(config, journal, folder_name, outcome["commit"])
            _record_folder_in_ledger(config, journal, folder_name, now)
    return conflicts, errors, redacted_total


def _merge_with_earlier_run(
    report: dict[str, Any], earlier: Optional[Mapping[str, Any]], applied: Sequence[Mapping[str, Any]], carried_over: Sequence[Mapping[str, Any]]
) -> None:
    """What a report holds besides this run's findings. Applied changes come from their record,
    and a retry keeps what the run before it found, since those notes are used up. A trial run's
    report is left out of this: it used up nothing, so the same things are worked out again."""
    trial = [item for item in report["memory_changes"] if item["outcome"] == schemas.OUTCOME_WOULD_APPLY]
    report["memory_changes"] = [*carried_over, *applied, *trial]
    if earlier is None or not earlier["apply_enabled"]:
        return
    fresh_ids = {item["id"] for item in report["proposals"]}
    report["proposals"] = [*(item for item in earlier["proposals"] if item["id"] not in fresh_ids), *report["proposals"]]
    held_ids = {item["id"] for item in report["held"]}
    report["held"] = [*(item for item in earlier["held"] if item["id"] not in held_ids), *report["held"]]
    known = {(item["subject"], item["reason"], item["claim"]) for item in report["rejected"]}
    report["rejected"] = [*(item for item in earlier["rejected"] if (item["subject"], item["reason"], item["claim"]) not in known), *report["rejected"]]
    if not report["coverage"].get("windows"):
        report["coverage"] = earlier["coverage"]
        report["failures_ranked"] = earlier["failures_ranked"]


def before_after_checks(config: Config, week: str) -> list[dict[str, Any]]:
    """For each change applied in an earlier week: what was recorded before and since, and
    whether its text is still in the file. Per change, with no trend worked out across them."""
    ledgers_dir = ledger.ledgers_dir_of(config.paths.data_dir)
    checks = []
    for path in sorted(glob.glob(os.path.join(glob.escape(config.paths.data_dir), "reports", "*", "report.json"))):
        report = _read_json(path)
        if report["week"] >= week:
            continue
        applied_at = datetime.fromisoformat(report["generated_at"])
        for change in report["memory_changes"]:
            if change["outcome"] != schemas.OUTCOME_APPLIED or change["commit"] is None:
                continue
            item = ledger.ItemId(ledger.project_scope(change["project_folder"]), ledger.KIND_MEMORY, change["memory"])
            entries = []
            if ledger.item_exists(ledgers_dir, item):
                try:
                    entries = [
                        entry for entry in ledger.load_ledger(ledgers_dir, item)["entries"]
                        if not entry["source"]["notes"].startswith(WEEKLY_SOURCE_PREFIX)
                    ]
                except ledger.UNREADABLE as error:
                    _add_problem(config, f"memory {change['memory']} in {change['project_folder']}", error)
            before = [entry for entry in entries if datetime.fromisoformat(entry["date"]) <= applied_at]
            since = [entry for entry in entries if datetime.fromisoformat(entry["date"]) > applied_at]
            text = memory_store.read_memory_file(os.path.join(_memory_folder(config, change["project_folder"]), f"{change['memory']}.md"))
            checks.append({
                "change": change["id"],
                "week": report["week"],
                "memory": change["memory"],
                "project_folder": change["project_folder"],
                "action": change["action"],
                "before": _direction_counts(before),
                "since": _direction_counts(since),
                "since_what": [{"direction": entry["direction"], "who": entry["who"], "what": entry["what"]} for entry in since],
                "text_still_in_file": text is not None and change["claim"] in text,
            })
    return checks


def _direction_counts(entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        schemas.STANCE_FOR: sum(1 for entry in entries if entry["direction"] == schemas.STANCE_FOR),
        schemas.STANCE_AGAINST: sum(1 for entry in entries if entry["direction"] == schemas.STANCE_AGAINST),
    }


def _change_record(gated: weekly_gate.GatedChange, outcome: str, commit: Optional[str]) -> dict[str, Any]:
    change = gated.change
    return {
        "id": gated.id,
        "project_folder": gated.project_folder,
        "memory": change.memory,
        "action": change.action,
        "claim": change.claim,
        "old_text": change.old_text,
        "endorsement": change.endorsement,
        "quote": change.quote,
        "assistant_statement": change.assistant_statement,
        "session": gated.record.window.session_id,
        "source": gated.record.source_json(),
        "new_evidence": gated.new_evidence,
        "outcome": outcome,
        "commit": commit,
        "before": gated.before,
        "after": gated.after,
    }


def _coverage(
    records: Sequence[weekly_notes.NoteRecord], windows: Sequence[weekly_notes.Window], skipped: Sequence[Mapping[str, str]], config: Config
) -> dict[str, Any]:
    first = min((window.after for window in windows), default=None)
    last = max((window.through for window in windows), default=None)
    days = len({record.window.through.astimezone().date() for record in records})
    return {
        "windows": len(windows),
        "sessions": len({window.session_id for window in windows}),
        "notes": len(records),
        "first": None if first is None else first.isoformat(),
        "last": None if last is None else last.isoformat(),
        "days_of_notes": days,
        "windows_skipped": list(skipped),
        "memory_notes": sum(1 for record in records if weekly_notes.is_memory_note(record, config.weekly)),
        "proposal_notes": sum(1 for record in records if weekly_notes.is_proposal_note(record)),
    }


def _run_stages(
    config: Config,
    local: LocalSettings,
    week: str,
    run_id: str,
    caller: pass_support.Caller,
    now: datetime,
    report: dict[str, Any],
    weekly_state: dict[str, Any],
) -> int:
    """Everything after the daily pass. Fills ``report`` as it goes; failures raise. Returns secret
    patterns redacted from the record of applied changes."""
    ledgers_dir = ledger.ledgers_dir_of(config.paths.data_dir)
    problems: list[dict[str, str]] = []
    flags = ledger.write_flags(ledgers_dir, now, config.ledger, problems)
    found = backfill.scan_inventory(config)
    ledger.add_item_problems(ledgers_dir, [*problems, *found.problems])
    decisions = ledger.load_decisions(ledgers_dir)
    state = sessions.load_state(daily.state_path(config))
    consumed = weekly_state["consumed_windows"]
    discovered = sessions.discover_sessions(config.paths.projects_dir)
    records, windows, skipped = weekly_notes.load_windows(config, state, consumed, discovered)
    store = weekly_notes.SourceStore(config)
    records, windows, set_aside = weekly_notes.set_aside_unreadable(records, windows, store, config.weekly)
    skipped = [*skipped, *set_aside]
    failures, procedures = weekly_notes.aggregate_counts(config, weekly_state["consumed_counts"])
    report["coverage"] = _coverage(records, windows, skipped, config)
    report["failures_ranked"] = [failure.to_json() for failure in failures]
    report["before_after"] = before_after_checks(config, week)

    gate_state = weekly_gate.MemoryGateState(one_moment_quotes=weekly_notes.one_moment_quotes(records))
    journal = applied_changes.load(config, week)
    memory_prompt = _read_text(MEMORY_PROMPT)
    groups_dir = os.path.join(report_dir_of(config, week), "groups")

    def read_current(folder: str, name: str) -> Optional[str]:
        return memory_store.read_memory_file(os.path.join(_memory_folder(config, folder), f"{name}.md"))

    for group in weekly_notes.memory_groups(records, store, config.weekly):
        if group.project_folder in journal["folders"]:
            continue  # It holds this week's commit, so it is not written again this week.
        stdin_text, refs = _memory_group_input(group, store, config, decisions)
        reply = _cached_or_called_reply(
            os.path.join(groups_dir, f"memory-{group.name}.json"), memory_prompt, stdin_text, config.weekly.memory_model,
            f"weekly-memory:{group.name}", caller, schemas.parse_memory_reply,
        )
        weekly_gate.gate_memory_reply(reply, group, refs, store, decisions, config, gate_state)
    report["rejected"] = gate_state.rejected
    weekly_gate.check_quote_batch(gate_state, config.weekly.quote_failure_batch_min)
    if gate_state.screened:
        verdicts = _cached_or_called_reply(
            os.path.join(groups_dir, "verification.json"), _read_text(VERIFY_PROMPT), weekly_gate.verification_input(gate_state),
            config.weekly.verification_model, "weekly-verification", caller, schemas.parse_claim_verdicts,
        )
        weekly_gate.apply_verdicts(gate_state, verdicts, read_current, config)

    candidates: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    proposal_notes = [record for record in records if weekly_notes.is_proposal_note(record)]
    if proposal_notes:
        stdin_text, refs = _proposals_input(records, failures, procedures, config, decisions)
        proposals = _cached_or_called_reply(
            os.path.join(groups_dir, "proposals.json"), _read_text(PROPOSALS_PROMPT), stdin_text, config.weekly.proposal_model,
            "weekly-proposals", caller, schemas.parse_proposals,
        )
        failure_refs = {failure.ref: failure for failure in failures}
        procedure_refs = {procedure.ref: procedure for procedure in procedures}
        for proposal in proposals:
            decision = weekly_gate.gate_proposal(proposal, refs, failure_refs, procedure_refs, decisions, config)
            if decision.outcome == weekly_gate.REJECT:
                gate_state.rejected.append({
                    "subject": proposal.title, "project_folder": "", "reason": decision.reason, "detail": decision.detail,
                    "claim": proposal.what, "quote": "", "source": None,
                })
                continue
            record = _proposal_record(proposal, refs, failure_refs, procedure_refs, STATUS_OPEN)
            if decision.outcome == weekly_gate.HOLD:
                held.append({**record, "status": f"{STATUS_HELD_PREFIX}{decision.reason}", "evidence": {**record["evidence"], "held_detail": decision.detail}})
            else:
                candidates.append(record)

    private = _private_material(config, local, windows, discovered)
    kept, over_limit = _research_candidates(candidates, private, caller, week, gate_state.rejected)
    if not local.apply_memory_changes:
        # A dry run proves the research path even if a thin week holds every new item back.
        held, held_over_limit = _research_candidates(held, private, caller, week, gate_state.rejected)
        held.extend(held_over_limit)
    held.extend(over_limit)

    changed = {(gated.project_folder, gated.change.memory) for gated in gate_state.accepted}
    all_proposals = [*kept, *_fact_and_deletion_proposals(gate_state, config.weekly.title_max_chars), *_revision_proposals(flags, config, ledgers_dir, changed, decisions, found)]
    stored, _ = _store_proposals(all_proposals, config, week)
    report["proposals"] = stored
    report["held"] = [{key: value for key, value in item.items() if not key.startswith("_")} for item in held]

    if local.apply_memory_changes:
        waiting = {
            window.key for window in windows
            if window.project_folder in journal["folders"] and window.key not in journal["folders"][window.project_folder]["windows"]
        }
        conflicts, errors, redacted = _apply_changes(gate_state, config, week, run_id, now, windows)
        gate_state.rejected.extend(conflicts)
        if errors:
            raise memory_store.MemoryStoreError(f"{len(errors)} memory folders were not applied: {errors}")
        for window in windows:
            # A window read after its folder got this week's commit waits for next week's pass.
            if window.key not in waiting:
                consumed[window.key] = week
        for key in weekly_notes.counts_files(config):
            weekly_state["consumed_counts"][key] = week
        _write_json(weekly_state_path(config), weekly_state)
        return redacted
    report["memory_changes"] = [_change_record(gated, schemas.OUTCOME_WOULD_APPLY, None) for gated in gate_state.accepted]
    return 0


def _empty_report(week: str, run_id: str, now: datetime, apply_enabled: bool) -> dict[str, Any]:
    return {
        "schema_version": schemas.WEEKLY_REPORT_SCHEMA_VERSION,
        "week": week,
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "status": STATUS_FAILED,
        "stop_reason": None,
        "apply_enabled": apply_enabled,
        "coverage": {},
        "memory_changes": [],
        "rejected": [],
        "proposals": [],
        "held": [],
        "failures_ranked": [],
        "before_after": [],
        "usage": {},
    }


def run_weekly(
    config: Config,
    local: LocalSettings,
    run_id: str,
    now: Optional[datetime] = None,
    call: Callable[..., model_call.ModelResult] = model_call.call_model,
) -> dict[str, Any]:
    """Run the pass and return its result, in the shape the entry point reads."""
    started = time.monotonic()
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must carry a UTC offset")
    local_now = now.astimezone()
    week = iso_week_of(local_now)
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "pass": "weekly",
        "run_id": run_id,
        "week": week,
        "status": STATUS_OK,
        "skipped": False,
        "stop_reason": None,
        "apply_enabled": local.apply_memory_changes,
        "budget_stopped": False,
        "failed_sessions": [],
        "dropped_verdicts": [],
        "item_problems": [],
        "possible_renames": [],
        "backlog_sessions": [],
        "windows_reset": [],
        "secrets_redacted": 0,
        "memory_snapshot": {"errors": []},
        "daily": None,
    }
    if week_already_done(config, week, local.apply_memory_changes):
        result["skipped"] = True
        result["wall_seconds"] = round(time.monotonic() - started, 1)
        return result

    memory_store.remove_partial_files(config.paths.data_dir)
    report_path = os.path.join(report_dir_of(config, week), "report.json")
    earlier_report = _read_json(report_path) if os.path.exists(report_path) else None
    weekly_state = load_weekly_state(config)
    carried_over: list[dict[str, Any]] = []
    try:
        carried_over = _reconcile_applied(config, week, weekly_state, now)
    except (memory_store.MemoryStoreError, ledger.LedgerError) as error:
        result["status"] = STATUS_FAILED
        result["stop_reason"] = f"could not finish what an earlier run left: {type(error).__name__}: {error}"

    daily_cost = 0.0
    if result["status"] == STATUS_OK and not daily_completed_on(config, local_now):
        daily_result = daily.run_daily(config, run_id, call=call)
        with open(os.path.join(config.paths.data_dir, "logs", f"daily-{run_id}.result.json"), "w", encoding="utf-8") as handle:
            json.dump(daily_result, handle, ensure_ascii=False, indent=1)
        daily_cost = daily_result["cost_usd"]
        result["daily"] = {key: daily_result[key] for key in ("status", "stop_reason", "sessions_read", "notes", "cost_usd")}
        result["failed_sessions"] = daily_result["failed_sessions"]
        result["dropped_verdicts"] = daily_result["dropped_verdicts"]
        result["backlog_sessions"] = daily_result["backlog_sessions"]
        result["windows_reset"] = daily_result["windows_reset"]
        result["secrets_redacted"] = daily_result["secrets_redacted"]
        result["memory_snapshot"] = daily_result["memory_snapshot"]
        if daily_result["stop_reason"] is not None:
            result["status"] = STATUS_FAILED
            result["stop_reason"] = f"the daily pass stopped: {daily_result['stop_reason']}"
        elif daily_result["budget_stopped"]:
            result["status"] = STATUS_BUDGET_STOPPED
            result["budget_stopped"] = True

    report = _empty_report(week, run_id, now, local.apply_memory_changes)
    caller = pass_support.Caller(config, report_dir_of(config, week), run_id, daily_cost, call)
    journal_redacted = 0
    if result["status"] == STATUS_OK:
        try:
            journal_redacted = _run_stages(config, local, week, run_id, caller, now, report, weekly_state)
        except model_call.BudgetExhaustedError as error:
            result["status"] = STATUS_BUDGET_STOPPED
            result["budget_stopped"] = True
            result["stop_reason"] = str(error)
        except (
            model_call.ModelCallError,
            research.SearchUnavailableError,
            research.PrivateMaterialError,
            schemas.SchemaError,
            weekly_gate.QuoteBatchError,
            memory_store.MemoryStoreError,
            transcripts.TranscriptFormatError,
            ledger.LedgerError,
        ) as error:
            result["status"] = STATUS_FAILED
            result["stop_reason"] = f"{type(error).__name__}: {error}"
    held_problems = ledger.read_item_problems(ledger.ledgers_dir_of(config.paths.data_dir))
    result["item_problems"] = held_problems["problems"]
    result["possible_renames"] = held_problems["possible_renames"]
    if result["status"] == STATUS_OK and result["dropped_verdicts"]:
        # The pass did its work, and the review page says "did not finish" when it is given no reason.
        result["status"] = STATUS_FAILED
        result["stop_reason"] = f"the daily pass: {stance_check.dropped_line(result['dropped_verdicts'])}"
    if result["status"] == STATUS_OK and (result["failed_sessions"] or result["item_problems"]):
        result["status"] = STATUS_FAILED

    report["status"] = result["status"]
    report["stop_reason"] = result["stop_reason"]
    report["usage"] = {
        "model_calls": caller.totals.calls,
        "tokens": caller.totals.tokens,
        "cost_usd": round(caller.totals.cost_usd, 4),
        "daily_cost_usd": daily_cost,
    }
    applied = [record for _, entry in applied_changes.committed_entries(applied_changes.load(config, week)) for record in entry["changes"]]
    _merge_with_earlier_run(report, earlier_report, applied, carried_over)
    report, redacted = extract.redact_value(report, config)
    schemas.validate_weekly_report(report, "weekly report")
    _write_json(report_path, report)
    result["review_page"] = review_data.write_review(config, report, now)
    _mark_reported(config, week)

    result["secrets_redacted"] += redacted + journal_redacted + caller.secrets_redacted
    result["model_calls"] = caller.totals.calls
    result["tokens"] = caller.totals.tokens
    result["cost_usd"] = round(caller.totals.cost_usd, 4)
    result["report"] = f"reports/{week}/report.json"
    result["counts"] = {
        "memory_changes": len(report["memory_changes"]),
        "rejected": len(report["rejected"]),
        "proposals": len(report["proposals"]),
        "held": len(report["held"]),
    }
    result["data_commit"] = memory_store.commit_all(config.paths.data_dir, config.memory, f"Weekly pass {week}, run {run_id}: {result['status']}")
    result["wall_seconds"] = round(time.monotonic() - started, 1)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("run",))
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--result-file", required=True)
    arguments = parser.parse_args(argv)
    config = load_config(arguments.config)
    local = load_local_settings(config.paths.local_settings)
    result = run_weekly(config, local, arguments.run_id)
    with open(arguments.result_file, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
