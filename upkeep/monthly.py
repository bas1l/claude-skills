"""The monthly pass: four audit questions about the whole setup. It only writes proposals.

    1. Setup coherence: contradictions, duplicates, stale memories, and what each session loads.
    2. Upkeep quality: acceptance rate, undone memories, thresholds, once there are enough weeks.
    3. Rule level: memories to move between a project and the global instructions.
    4. Outside replacements for existing skills, a set number a month, in rotation.

Who sees what. Memory text is private, so it goes only to tool-less calls (``tools=()``). A research
call receives one generic description, written by a tool-less call that saw only what the skills
say of themselves, and ``research.py`` checks it for private material before sending it.

Evidence. A script measures what it can. Every finding from a model cites file, line and words, and
a script compares those with the file: a citation that differs rejects that finding. If all of them
fail, the pass fails. A duplicate counts only after a model has read both texts and said so.

Written under the data folder:

    reports/monthly/YYYY-MM.json          the results for the review, in the format review_data.py
                                          reads. Written only by a run that ended ok.
    reports/monthly/YYYY-MM/report.json   the whole report, below
    reports/monthly/YYYY-MM/groups/       model replies by group, with a hash of their input
    reports/monthly/YYYY-MM/research/     research records
    reports/monthly/YYYY-MM/usage.jsonl   one line per model call
    state/monthly.json                    the month each skill was last checked for a replacement

report.json, schema version 1 (checked by ``schemas.validate_monthly_report``):

    month, run_id, generated_at, status ok|failed|budget_stopped, stop_reason
    context               what each session starts with, per project; see monthly_inventory.py
    coverage              files and characters read, groups, skills
    counts                findings by question
    findings[]            the proposals, in the fields of the weekly report's, kind monthly_finding.
                          evidence holds audit_question, category, sides and measured
    rejected[]            subject, question, reason, detail: findings refused by a check
    already_raised[]      subject, question: left out because an earlier month raised them
    duplicate_candidates  candidates, judged_same, judged_different, each with a reason
    quality               status not_enough_data, with a plain statement, or the counts
    replacements          checked, kept (nothing outside does the job), rejected, order for next time
    usage                 model_calls, tokens, cost_usd

Idempotent per calendar month: a run that succeeded does nothing the next time, and a retry after a
failure reuses model replies whose input is unchanged. Applies nothing, and never writes to a memory
folder, a skill, a hook or a setting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

import backfill
import extract
import ledger
import memory_store
import model_call
import monthly_inventory as inventory
import pass_support
import research
import review_data
import schemas
import transcripts
import weekly_notes
from config import Config, LocalSettings, load_config, load_local_settings

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_BUDGET_STOPPED = "budget_stopped"
EXIT_CODES = {STATUS_OK: 0, STATUS_FAILED: 1, STATUS_BUDGET_STOPPED: 3}
RESULT_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 1

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
COHERENCE_PROMPT = os.path.join(PROMPTS_DIR, "monthly_coherence.md")
DUPLICATES_PROMPT = os.path.join(PROMPTS_DIR, "monthly_duplicates.md")
QUALITY_PROMPT = os.path.join(PROMPTS_DIR, "monthly_quality.md")
DESCRIPTIONS_PROMPT = os.path.join(PROMPTS_DIR, "monthly_descriptions.md")

QUESTION_COHERENCE = "coherence"
QUESTION_QUALITY = "quality"
QUESTION_LEVEL = "rule_level"
QUESTION_REPLACEMENT = "replacement"
QUESTIONS = (QUESTION_COHERENCE, QUESTION_QUALITY, QUESTION_LEVEL, QUESTION_REPLACEMENT)
QUESTION_LABEL = {
    QUESTION_COHERENCE: "does the setup agree with itself",
    QUESTION_QUALITY: "how well is the upkeep doing",
    QUESTION_LEVEL: "is each rule kept at the right level",
    QUESTION_REPLACEMENT: "does something outside now do a skill's job",
}
CATEGORY_CONTRADICTION = "contradiction"
CATEGORY_DUPLICATE = "duplicate"
CATEGORY_STALE = "stale"
CATEGORY_CONTEXT = "context"
CATEGORY_SUMMARY = "summary"
CATEGORY_THRESHOLD = "threshold"
CATEGORY_LEVEL = "level"
CATEGORY_REPLACEMENT = "replacement"
QUALITY_NOT_ENOUGH = "not_enough_data"
QUALITY_MEASURED = "measured"
REJECT_CITATION = "citation_failed"
REJECT_FEW_SIDES = "needs_two_sides"
REJECT_GROUND = "ground_not_supported"
REJECT_LEVEL = "wrong_level_for_this_move"
REJECT_SETTING = "setting_not_tunable"
REJECT_RESEARCH = "research_rejected"
REJECT_UNKNOWN_CLUSTER_FILE = "file_outside_the_cluster"
CITATION_REASONS = frozenset({REJECT_CITATION, REJECT_FEW_SIDES})
ADOPTING = frozenset({"adopt", "adapt"})
MERGED_CATEGORIES = frozenset({CATEGORY_CONTRADICTION, CATEGORY_DUPLICATE, CATEGORY_STALE, CATEGORY_LEVEL})


class CitationBatchError(RuntimeError):
    """Every finding of a run failed its citations, so the reader misread the files as a whole."""


def month_of(moment: datetime) -> str:
    return moment.astimezone().strftime("%Y-%m")


def monthly_root(config: Config) -> str:
    return os.path.join(review_data.reports_dir(config.paths.data_dir), review_data.MONTHLY_FOLDER)


def report_dir_of(config: Config, month: str) -> str:
    return os.path.join(monthly_root(config), month)


def feed_path(config: Config, month: str) -> str:
    return os.path.join(monthly_root(config), f"{month}.json")


def state_path(config: Config) -> str:
    return os.path.join(config.paths.data_dir, "state", "monthly.json")


def load_state(config: Config) -> dict[str, Any]:
    """Which month each skill was last checked. No file means none yet: the first pass creates it."""
    path = state_path(config)
    if not os.path.exists(path):
        return {"schema_version": STATE_SCHEMA_VERSION, "replacement_checked": {}}
    state = pass_support.read_json(path)
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(f"{path}: schema_version {state.get('schema_version')!r}")
    return state


def month_already_done(config: Config, month: str) -> bool:
    path = os.path.join(report_dir_of(config, month), "report.json")
    return os.path.exists(path) and pass_support.read_json(path)["status"] == STATUS_OK


@dataclass
class Findings:
    """What this run has found so far, in order."""

    records: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    already_raised: list[dict[str, str]] = field(default_factory=list)

    def reject(self, subject: str, question: str, reason: str, detail: str) -> None:
        self.rejected.append({"subject": subject, "question": question, "reason": reason, "detail": detail})


def _normal(text: str) -> str:
    return " ".join(text.split())


class CitationError(ValueError):
    """A cited file, line or quote is not what the file holds."""


def resolve_side(side: Mapping[str, Any], files: Mapping[str, inventory.SourceFile], quote_min_chars: int) -> dict[str, Any]:
    """The citation as the report records it, or an error saying what does not match."""
    source = files.get(side["file"])
    if source is None:
        raise CitationError(f"{side['file']} was not given to this reader")
    line = side["line"]
    if line > len(source.lines):
        raise CitationError(f"{side['file']} has {len(source.lines)} lines, not {line}")
    quote = _normal(side["quote"])
    if len(quote) < quote_min_chars:
        raise CitationError(f"quote of {len(quote)} characters is too short to identify anything")
    if quote not in _normal(source.lines[line - 1]):
        raise CitationError(f"the quote is not on line {line} of {side['file']}")
    return {
        "file": source.path,
        "ref": source.ref,
        "role": source.role,
        "project_folder": source.project_folder,
        "name": source.name,
        "line": line,
        "quote": side["quote"],
    }


def _resolved_sides(entry: Mapping[str, Any], files: Mapping[str, inventory.SourceFile], config: Config, minimum: int, question: str, found: Findings) -> Optional[list[dict[str, Any]]]:
    subject = entry["title"]
    try:
        sides = [resolve_side(side, files, config.monthly.quote_min_chars) for side in entry["sides"]]
    except CitationError as error:
        found.reject(subject, question, REJECT_CITATION, str(error))
        return None
    if len({(side["ref"], side["line"]) for side in sides}) < minimum:
        found.reject(subject, question, REJECT_FEW_SIDES, f"{len(entry['sides'])} sides given, {minimum} distinct places needed")
        return None
    return sides


def finding(
    question: str, category: str, title: str, what: str, why: str, target: str,
    sides: Sequence[Mapping[str, Any]] = (), exact_change: str = "", measured: Sequence[str] = (),
    record_research: Optional[Mapping[str, Any]] = None, distinct: str = "",
) -> dict[str, Any]:
    """A record in the fields of a weekly proposal. Its id rests on where it is and what is quoted,
    not on how the model happened to word it."""
    places = sorted({side["file"] for side in sides})
    quotes = sorted(_normal(side["quote"]) for side in sides)
    digest = hashlib.sha256("\n".join((category, target, distinct, *places, *quotes)).encode("utf-8")).hexdigest()[:10]
    return {
        "id": f"monthly-{digest}",
        "kind": schemas.KIND_MONTHLY_FINDING,
        "change_type": schemas.CHANGE_EXISTING,
        "title": title,
        "what": what,
        "why": why,
        "target": target,
        "basis": "",
        "evidence": {
            "audit_question": QUESTION_LABEL[question],
            "question": question,
            "category": category,
            "sides": [dict(side) for side in sides],
            "measured": list(measured),
        },
        "exact_change": exact_change,
        "draft_path": None,
        "research": record_research,
        "status": "open",
        "project_folder": "",
    }


def same_finding(first: Mapping[str, Any], second: Mapping[str, Any], overlap: float) -> bool:
    """The same matter raised twice: in two readings of one month, or in two months. Every place the
    first cites is among the second's, in much the same words. Changed text is something new, so it
    may be raised again."""
    one, other = first["evidence"], second["evidence"]
    if one["category"] != other["category"]:
        return False
    if one["category"] == CATEGORY_SUMMARY:
        return first["id"] == second["id"]
    if one["category"] == CATEGORY_THRESHOLD:
        return first["target"] == second["target"] and first["exact_change"] == second["exact_change"]
    if one["category"] == CATEGORY_REPLACEMENT:
        tools = {tool["url"] for tool in first["research"]["existing_tools"]}
        return first["target"] == second["target"] and bool(tools & {tool["url"] for tool in second["research"]["existing_tools"]})
    if one["category"] == CATEGORY_CONTEXT:
        return {side["file"] for side in one["sides"]} == {side["file"] for side in other["sides"]}
    return bool(one["sides"]) and all(
        any(side["file"] == place["file"] and weekly_notes.word_overlap(side["quote"], place["quote"]) >= overlap for place in other["sides"])
        for side in one["sides"]
    )


def earlier_findings(config: Config, month: str) -> list[dict[str, Any]]:
    """What earlier months raised, whatever became of it. Decided or still open, it is not raised
    again: an open item carries forward by itself, and a rejected one stays out."""
    root = monthly_root(config)
    found = []
    if not os.path.isdir(root):
        return found
    for name in sorted(os.listdir(root)):
        if name.endswith(".json") and name != f"{month}.json":
            found.extend(pass_support.read_json(os.path.join(root, name))["proposals"])
    return found


def _add(record: dict[str, Any], question: str, found: Findings, earlier: Sequence[Mapping[str, Any]], overlap: float) -> None:
    if any(same_finding(record, other, overlap) for other in earlier):
        entry = {"subject": record["title"], "question": question}
        if entry not in found.already_raised:
            found.already_raised.append(entry)
    elif not any(same_finding(record, other, overlap) for other in found.records):
        found.records.append(record)


def merge_overlapping(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Findings of one kind that cite the same line are one matter seen from several readings, so
    that one setting at odds with five rules is one item to decide. The fullest stays the main text,
    and what the others said is kept beside it."""
    merged = []
    groups: dict[str, list[list[dict[str, Any]]]] = {}
    for record in records:
        if record["evidence"]["category"] not in MERGED_CATEGORIES:
            merged.append(record)
            continue
        groups.setdefault(record["evidence"]["category"], []).append([record])
    for clusters in groups.values():
        joined: list[tuple[set[tuple[str, int]], list[dict[str, Any]]]] = []
        for (record,) in clusters:
            places = {(side["file"], side["line"]) for side in record["evidence"]["sides"]}
            members = [record]
            for entry in [entry for entry in joined if entry[0] & places]:
                joined.remove(entry)
                places |= entry[0]
                members = [*entry[1], *members]
            joined.append((places, members))
        merged.extend(_merged_record(members) for _, members in joined)
    return merged


def _merged_record(members: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if len(members) == 1:
        return members[0]
    main = max(members, key=lambda record: len(record["evidence"]["sides"]))
    others = [record for record in members if record is not main]
    sides: dict[tuple[str, int], dict[str, Any]] = {}
    for record in (main, *others):
        for side in record["evidence"]["sides"]:
            sides.setdefault((side["file"], side["line"]), side)
    evidence = main["evidence"]
    measured = [*evidence["measured"], *[f"Also seen as {record['title']}: {record['what']} {record['why']}" for record in others]]
    exact = next((record["exact_change"] for record in (main, *others) if record["exact_change"]), "")
    return finding(evidence["question"], evidence["category"], main["title"], main["what"], main["why"], main["target"], list(sides.values()), exact, measured, distinct="merged")


def _gate_coherence(reply: Mapping[str, Any], group: inventory.Group, config: Config, found: Findings, earlier: Sequence[Mapping[str, Any]]) -> None:
    """Apply the checks that need the files to one reading's reply."""
    files = {item.ref: item for item in group.files}
    overlap = config.weekly.reproposal_word_overlap
    for entry in reply["contradictions"]:
        sides = _resolved_sides(entry, files, config, 2, QUESTION_COHERENCE, found)
        if sides is not None:
            _add(finding(QUESTION_COHERENCE, CATEGORY_CONTRADICTION, entry["title"], entry["what"], entry["why"], sides[0]["name"], sides), QUESTION_COHERENCE, found, earlier, overlap)
    for entry in reply["stale"]:
        sides = _resolved_sides(entry, files, config, 2 if entry["ground"] == schemas.STALE_SUPERSEDED else 1, QUESTION_COHERENCE, found)
        if sides is None:
            continue
        problem = _stale_ground_problem(entry["ground"], sides, files, config)
        if problem:
            found.reject(entry["title"], QUESTION_COHERENCE, REJECT_GROUND, problem)
            continue
        _add(finding(QUESTION_COHERENCE, CATEGORY_STALE, entry["title"], entry["question"], entry["why"], sides[0]["name"], sides, measured=[f"Grounds: {entry['ground']}"]), QUESTION_COHERENCE, found, earlier, overlap)
    for entry in reply["level_moves"]:
        sides = _resolved_sides(entry, files, config, 1, QUESTION_LEVEL, found)
        if sides is None:
            continue
        wanted = inventory.ROLE_GLOBAL if entry["direction"] == schemas.LEVEL_TO_PROJECT else None
        roles = {side["role"] for side in sides}
        if (wanted and wanted not in roles) or (not wanted and not roles & {inventory.ROLE_MEMORY, inventory.ROLE_PROJECT}):
            found.reject(entry["title"], QUESTION_LEVEL, REJECT_LEVEL, f"{entry['direction']} cites roles {sorted(roles)}")
            continue
        _add(finding(QUESTION_LEVEL, CATEGORY_LEVEL, entry["title"], entry["what"], entry["why"], sides[0]["name"], sides, entry["exact_change"], measured=[f"Direction: {entry['direction']}"]), QUESTION_LEVEL, found, earlier, overlap)


def _stale_ground_problem(ground: str, sides: Sequence[Mapping[str, Any]], files: Mapping[str, inventory.SourceFile], config: Config) -> str:
    """A ground a script can check is checked. ``superseded`` is a reading, and stays a question."""
    if ground == schemas.STALE_PATH_GONE:
        if not any(side["line"] in inventory.missing_paths(files[side["ref"]]) for side in sides):
            return "no cited line names a path that is gone"
    if ground == schemas.STALE_STATED_LIMIT:
        patterns = config.ledger.stated_limit_patterns
        if not any(side["line"] in inventory.stated_limit_lines(files[side["ref"]], patterns) for side in sides):
            return "no cited line states a limit"
    return ""


def _duplicate_finding(entry: Mapping[str, Any], sides: Sequence[Mapping[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Across projects it is a question of level. Otherwise it is plain repetition."""
    memory_folders = {side["project_folder"] for side in sides if side["role"] == inventory.ROLE_MEMORY}
    if len(memory_folders) >= 2:
        question, category = QUESTION_LEVEL, CATEGORY_LEVEL
    else:
        question, category = QUESTION_COHERENCE, CATEGORY_DUPLICATE
    return question, finding(question, category, entry["title"], entry["what"], entry["why"], sides[0]["name"], sides, entry["exact_change"], distinct="duplicate")


def _gate_duplicates(replies: Sequence[Mapping[str, Any]], candidates: Mapping[str, inventory.Candidate], config: Config, found: Findings, earlier: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Count only what a reader judged, after its citations hold. A candidate left unanswered raises."""
    answered = [entry["cluster"] for entry in replies]
    if sorted(answered) != sorted(candidates):
        raise schemas.SchemaError(f"verdicts for {sorted(answered)} do not match the clusters {sorted(candidates)}")
    judged_same = []
    judged_different = []
    for entry in replies:
        candidate = candidates[entry["cluster"]]
        if entry["verdict"] == schemas.VERDICT_DIFFERENT:
            judged_different.append({"cluster": entry["cluster"], "units": [unit.label for unit in candidate.units], "reason": entry["reason"]})
            continue
        files = {unit.source.ref: unit.source for unit in candidate.units}
        sides = _resolved_sides(entry, files, config, 2, QUESTION_COHERENCE, found)
        if sides is None:
            continue
        if len({side["ref"] for side in sides}) < 2:
            found.reject(entry["title"], QUESTION_COHERENCE, REJECT_FEW_SIDES, "a duplicate needs two different files")
            continue
        question, record = _duplicate_finding(entry, sides)
        judged_same.append({"cluster": entry["cluster"], "reason": entry["reason"], "question": question})
        _add(record, question, found, earlier, config.weekly.reproposal_word_overlap)
    return {"candidates": len(candidates), "judged_same": judged_same, "judged_different": judged_different}


def _check_citation_batch(found: Findings, minimum: int) -> None:
    """One citation failing is that finding's problem. All of them failing is the pass's."""
    failures = sum(1 for item in found.rejected if item["reason"] in CITATION_REASONS)
    if failures >= minimum and not found.records and not found.already_raised:
        raise CitationBatchError(f"all {failures} findings failed their citations")


def _context_findings(context: Mapping[str, Any], config: Config, month: str, found: Findings, earlier: Sequence[Mapping[str, Any]]) -> None:
    """An index longer than what loads is measured, not judged: its last lines are never read."""
    settings = config.monthly
    for project in context["projects"]:
        first_cut = project["index_first_line_cut"]
        if first_cut is None:
            continue
        side = {"file": project["index_path"], "ref": "", "role": inventory.ROLE_MEMORY, "project_folder": project["project_folder"], "name": "MEMORY", "line": first_cut, "quote": ""}
        _add(finding(
            QUESTION_COHERENCE, CATEGORY_CONTEXT,
            "A memory index is longer than what sessions load",
            f"Shorten this index. Sessions load its first {project['index_lines_loaded']} of {project['index_lines']} lines, so memories listed from line {first_cut} on are not seen at session start.",
            f"The product loads the first {settings.index_lines_loaded} lines or {settings.index_bytes_loaded} bytes.",
            project["project_folder"], [side],
        ), QUESTION_COHERENCE, found, earlier, config.weekly.reproposal_word_overlap)


def _tokens(chars: int, ratio: float) -> int:
    return int(chars / ratio)


def _summary_finding(context: Mapping[str, Any], quality: Mapping[str, Any], replacements: Mapping[str, Any], duplicates: Mapping[str, Any], month: str) -> dict[str, Any]:
    """What was measured this month, for reading: it holds what has no decision of its own."""
    ratio = context["tokens_estimate_ratio"]
    measured = [
        f"Global instructions: {context['global_chars']} characters. Skill listing: {context['skill_listing_chars']} characters for {context['skills_listed']} skills.",
        f"Per project, median {context['median_chars']} characters, largest {context['max_chars']} (about {_tokens(context['max_chars'] or 0, ratio)} tokens at {ratio} characters a token, an estimate).",
        *[f"Large: {entry['what']}, {entry['chars']} characters." for entry in context["largest"]],
        f"Not measured: {', '.join(context['not_measured'])}.",
        quality["statement"],
        f"Duplicates: {duplicates['candidates']} candidates compared by script, {len(duplicates['judged_same'])} judged the same after reading, {len(duplicates['judged_different'])} judged different.",
        f"Replacements: checked {len(replacements['checked'])} of {replacements['skills_total']} skills this month; {len(replacements['kept'])} have nothing outside that does the job.",
    ]
    return finding(
        QUESTION_COHERENCE, CATEGORY_SUMMARY, f"What the monthly check measured, {month}",
        f"Each session starts with about {context['median_chars']} characters of setup in a typical project, and {context['max_chars']} in the largest.",
        "For reading. It holds what has no decision of its own. Say what you want trimmed, or reject it to close it.",
        month, measured=measured, distinct=month,
    )


def quality_counts(config: Config) -> dict[str, Any]:
    """Decisions across every review, each item once. A week counts if something was decided in it."""
    data_dir = config.paths.data_dir
    items: dict[str, Mapping[str, Any]] = {}
    for week in review_data.week_folders(data_dir):
        if os.path.isfile(review_data.review_path(data_dir, week)):
            for item in review_data.load_review(data_dir, week)["items"]:
                if item["decision"] is not None:
                    items[item["key"]] = item
    decided = list(items.values())
    outcomes: dict[str, int] = {}
    by_kind: dict[str, dict[str, int]] = {}
    by_basis: dict[str, dict[str, int]] = {}
    undone = []
    weeks = set()
    for item in decided:
        outcome = item["decision"]["outcome"]
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        weeks.add(review_data.iso_week_of(datetime.fromisoformat(item["decision"]["at"])))
        record = item["record"]
        kind = record["kind"] if item["section"] == schemas.SECTION_PROPOSAL else f"memory_{record['action']}"
        by_kind.setdefault(kind, {}).setdefault(outcome, 0)
        by_kind[kind][outcome] += 1
        if item["section"] == schemas.SECTION_PROPOSAL and record["basis"]:
            by_basis.setdefault(record["basis"], {}).setdefault(outcome, 0)
            by_basis[record["basis"]][outcome] += 1
        if outcome == schemas.OUTCOME_UNDONE:
            undone.append({"memory": record["memory"], "project_folder": record["project_folder"], "week": item["week"]})
    accepted = outcomes.get(schemas.OUTCOME_APPROVED, 0) + outcomes.get(schemas.OUTCOME_KEPT, 0)
    return {
        "weeks_with_decisions": len(weeks),
        "decided": len(decided),
        "outcomes": outcomes,
        "acceptance_rate": round(accepted / len(decided), 3) if decided else None,
        "by_kind": by_kind,
        "by_basis": by_basis,
        "undone_memories": undone,
    }


def _setting_value(config: Config, dotted: str) -> Any:
    section, _, name = dotted.partition(".")
    return getattr(getattr(config, section), name)


def _run_quality(config: Config, caller: pass_support.Caller, groups_dir: str, found: Findings, earlier: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Too few weeks is said plainly, and the model is not asked to guess."""
    settings = config.monthly
    counts = quality_counts(config)
    if counts["weeks_with_decisions"] < settings.quality_min_weeks:
        return {
            "status": QUALITY_NOT_ENOUGH,
            "statement": f"Upkeep quality: not enough data. Decisions in {counts['weeks_with_decisions']} weeks, and {settings.quality_min_weeks} are needed.",
            **counts,
        }
    tunable = {name: _setting_value(config, name) for name in settings.tunable_settings}
    stdin_text = json.dumps({"counts": counts, "settings": tunable}, ensure_ascii=False, indent=1)
    suggestions = pass_support.cached_or_called_reply(
        os.path.join(groups_dir, "quality.json"), pass_support.read_text(QUALITY_PROMPT), stdin_text, settings.quality_model,
        "monthly-quality", caller, schemas.parse_monthly_quality,
    )
    rate = counts["acceptance_rate"]
    measured = [
        f"Acceptance rate: {rate}, over {counts['decided']} decisions in {counts['weeks_with_decisions']} weeks.",
        f"Outcomes: {json.dumps(counts['outcomes'], ensure_ascii=False)}. Memories undone: {len(counts['undone_memories'])}.",
    ]
    for entry in suggestions:
        setting = entry["setting"]
        if setting not in tunable:
            found.reject(setting, QUESTION_QUALITY, REJECT_SETTING, "this setting is not on the list that may be tuned")
            continue
        if entry["suggested"] == tunable[setting]:
            continue
        _add(finding(
            QUESTION_QUALITY, CATEGORY_THRESHOLD, f"Consider changing {setting}",
            f"Change {setting} from {tunable[setting]} to {entry['suggested']}. A proposal only: the setting stays as it is unless you change it.",
            entry["why"], setting, exact_change=f"config.json {setting}: {tunable[setting]} -> {entry['suggested']}", measured=measured,
        ), QUESTION_QUALITY, found, earlier, config.weekly.reproposal_word_overlap)
    return {"status": QUALITY_MEASURED, "statement": f"Upkeep quality: {measured[0]}", **counts}


def choose_skills(names: Sequence[str], checked: Mapping[str, str], budget: int) -> list[str]:
    """The skills checked longest ago, never-checked first, so that all are covered over time."""
    return sorted(names, key=lambda name: (checked.get(name, ""), name))[:budget]


def _project_names(corpus: inventory.Corpus, config: Config) -> list[str]:
    """Names of working folders that identify a project. A generic folder name would refuse every
    description holding that word, and says nothing private."""
    public = {name.lower() for name in config.monthly.public_project_names}
    names = {os.path.basename(os.path.normpath(cwd)) for cwd in corpus.cwd_of_folder.values() if cwd}
    return sorted(name for name in names if name.lower() not in public)


def _run_replacements(
    corpus: inventory.Corpus, local: LocalSettings, config: Config, caller: pass_support.Caller, report_dir: str, state: Mapping[str, Any], found: Findings, earlier: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Research a few skills. Search being unavailable raises, and the pass writes no results."""
    settings = config.monthly
    skills = {item.name: item for item in corpus.skills}
    chosen = choose_skills(sorted(skills), state["replacement_checked"], settings.replacement_skills_per_month)
    outcome: dict[str, Any] = {"skills_total": len(skills), "checked": [], "kept": [], "rejected": []}
    if not chosen:
        return outcome
    stdin_text = json.dumps([inventory.skill_opening(skills[name], settings.skill_opening_chars) for name in chosen], ensure_ascii=False, indent=1)
    descriptions = pass_support.cached_or_called_reply(
        os.path.join(report_dir, "groups", "descriptions.json"), pass_support.read_text(DESCRIPTIONS_PROMPT), stdin_text, settings.description_model,
        "monthly-descriptions", caller, schemas.parse_monthly_descriptions,
    )
    if set(descriptions) != set(chosen):
        raise schemas.SchemaError(f"descriptions for {sorted(descriptions)} do not match the skills {chosen}")
    private = pass_support.private_material(config, local, _project_names(corpus, config), inventory.discovered_projects(config))
    for name in chosen:
        description = descriptions[name]
        digest = hashlib.sha256(description.encode("utf-8")).hexdigest()
        cache = os.path.join(report_dir, "research", f"{name}.json")
        if os.path.exists(cache) and pass_support.read_json(cache)["description_sha256"] == digest:
            record = pass_support.read_json(cache)["research"]
        else:
            try:
                record = research.research_description(description, private, config, caller.usage_log, caller.remaining(), caller.tracked(f"research:{name}"))
            except research.ResearchRejectedError as error:
                found.reject(name, QUESTION_REPLACEMENT, REJECT_RESEARCH, str(error))
                outcome["rejected"].append(name)
                continue
            pass_support.write_json(cache, {"description_sha256": digest, "research": record})
        outcome["checked"].append(name)
        tools = record["existing_tools"]
        if record["recommendation"] not in ADOPTING or not tools:
            outcome["kept"].append({"skill": name, "reason": record["recommendation_reason"]})
            continue
        names = ", ".join(tool["name"] for tool in tools)
        _add(finding(
            QUESTION_REPLACEMENT, CATEGORY_REPLACEMENT, f"Something outside may do the job of skill {name}",
            f"Consider whether to {record['recommendation']} instead of keeping skill {name} as it is: {names}.",
            record["recommendation_reason"], name, record_research=record,
        ), QUESTION_REPLACEMENT, found, earlier, config.weekly.reproposal_word_overlap)
    return outcome


def _counts_by_question(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {question: {} for question in QUESTIONS}
    for record in records:
        evidence = record["evidence"]
        place = counts[evidence["question"]]
        place[evidence["category"]] = place.get(evidence["category"], 0) + 1
    return counts


def _run_stages(config: Config, local: LocalSettings, month: str, caller: pass_support.Caller, report: dict[str, Any], state: dict[str, Any]) -> None:
    """Everything of a run. Fills ``report`` as it goes; failures raise."""
    settings = config.monthly
    report_dir = report_dir_of(config, month)
    groups_dir = os.path.join(report_dir, "groups")
    found = Findings()
    earlier = earlier_findings(config, month)
    corpus = inventory.read_corpus(config)
    context = inventory.measure_context(corpus, config)
    report["context"] = context
    groups = inventory.coherence_groups(corpus, settings.group_chars)
    report["coverage"] = {
        "files": len(corpus.all_files()),
        "chars": sum(item.chars for item in corpus.all_files()),
        "memories": len(corpus.memories),
        "skills": len(corpus.skills),
        "project_instruction_files": len(corpus.project_files),
        "groups": [{"name": group.name, "files": len(group.files), "chars": group.chars} for group in groups],
    }

    _context_findings(context, config, month, found, earlier)
    prompt = pass_support.read_text(COHERENCE_PROMPT)
    for group in groups:
        signals = inventory.render_signals(group, config.ledger.stated_limit_patterns)
        stdin_text = f"<files>\n{inventory.render_group(group)}\n</files>\n\n<signals>\n{signals}\n</signals>\n"
        reply = pass_support.cached_or_called_reply(
            os.path.join(groups_dir, f"coherence-{group.name}.json"), prompt, stdin_text, settings.coherence_model,
            f"monthly-coherence:{group.name}", caller, schemas.parse_monthly_coherence,
        )
        _gate_coherence(reply, group, config, found, earlier)

    candidates = inventory.duplicate_candidates(corpus, config)
    verdicts: list[dict[str, Any]] = []
    duplicates_prompt = pass_support.read_text(DUPLICATES_PROMPT)
    for position, batch in enumerate(inventory.pack_candidates(candidates, settings.group_chars), 1):
        stdin_text = "\n\n".join(inventory.render_candidate(candidate) for candidate in batch)
        verdicts.extend(pass_support.cached_or_called_reply(
            os.path.join(groups_dir, f"duplicates-{position}.json"), duplicates_prompt, stdin_text, settings.duplicates_model,
            f"monthly-duplicates:{position}", caller, schemas.parse_monthly_duplicates,
        ))
    duplicates = _gate_duplicates(verdicts, {candidate.ref: candidate for candidate in candidates}, config, found, earlier)
    report["duplicate_candidates"] = duplicates
    _check_citation_batch(found, config.weekly.quote_failure_batch_min)

    quality = _run_quality(config, caller, groups_dir, found, earlier)
    report["quality"] = quality
    replacements = _run_replacements(corpus, local, config, caller, report_dir, state, found, earlier)
    report["replacements"] = replacements

    records = merge_overlapping(found.records)
    records.append(_summary_finding(context, quality, replacements, duplicates, month))
    report["findings"] = records
    report["rejected"] = found.rejected
    report["already_raised"] = found.already_raised
    report["counts"] = _counts_by_question(records)


def _empty_report(month: str, run_id: str, now: datetime) -> dict[str, Any]:
    return {
        "schema_version": schemas.MONTHLY_REPORT_SCHEMA_VERSION,
        "month": month,
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "status": STATUS_FAILED,
        "stop_reason": None,
        "context": {},
        "coverage": {},
        "counts": {},
        "findings": [],
        "rejected": [],
        "already_raised": [],
        "duplicate_candidates": {},
        "quality": {},
        "replacements": {},
        "usage": {},
    }


def run_monthly(
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
    month = month_of(now)
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "pass": "monthly",
        "run_id": run_id,
        "month": month,
        "status": STATUS_OK,
        "skipped": False,
        "stop_reason": None,
        "budget_stopped": False,
        "failed_sessions": [],
        "backlog_sessions": [],
        "windows_reset": [],
        "secrets_redacted": 0,
        "memory_snapshot": {"errors": []},
    }
    if month_already_done(config, month):
        result["skipped"] = True
        result["wall_seconds"] = round(time.monotonic() - started, 1)
        return result

    report = _empty_report(month, run_id, now)
    report_dir = report_dir_of(config, month)
    caller = pass_support.Caller(config, report_dir, run_id, 0.0, call)
    state = load_state(config)
    try:
        _run_stages(config, local, month, caller, report, state)
    except model_call.BudgetExhaustedError as error:
        result["status"] = STATUS_BUDGET_STOPPED
        result["budget_stopped"] = True
        result["stop_reason"] = str(error)
    except (
        model_call.ModelCallError,
        research.SearchUnavailableError,
        research.PrivateMaterialError,
        schemas.SchemaError,
        CitationBatchError,
        backfill.InventoryError,
        memory_store.MemoryStoreError,
        transcripts.TranscriptFormatError,
        ledger.LedgerError,
    ) as error:
        result["status"] = STATUS_FAILED
        result["stop_reason"] = f"{type(error).__name__}: {error}"

    report["status"] = result["status"]
    report["stop_reason"] = result["stop_reason"]
    report["usage"] = {"model_calls": caller.totals.calls, "tokens": caller.totals.tokens, "cost_usd": round(caller.totals.cost_usd, 4)}
    report, redacted = extract.redact_value(report, config)
    schemas.validate_monthly_report(report, "monthly report")
    if result["status"] == STATUS_OK:
        # The results for the review, and the rotation, count only for a run that finished.
        pass_support.write_json(feed_path(config, month), {
            "schema_version": review_data.FEED_SCHEMA_VERSION,
            "source": schemas.ORIGIN_MONTHLY,
            "run_id": run_id,
            "generated_at": now.isoformat(),
            "proposals": report["findings"],
        })
        for name in report["replacements"]["checked"]:
            state["replacement_checked"][name] = month
        pass_support.write_json(state_path(config), state)
    pass_support.write_json(os.path.join(report_dir, "report.json"), report)

    result["secrets_redacted"] = redacted
    result["model_calls"] = caller.totals.calls
    result["tokens"] = caller.totals.tokens
    result["cost_usd"] = round(caller.totals.cost_usd, 4)
    result["report"] = f"reports/{review_data.MONTHLY_FOLDER}/{month}/report.json"
    result["counts"] = {"findings": len(report["findings"]), "rejected": len(report["rejected"]), "already_raised": len(report["already_raised"])}
    result["data_commit"] = memory_store.commit_all(config.paths.data_dir, config.memory, f"Monthly pass {month}, run {run_id}: {result['status']}")
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
    result = run_monthly(config, local, arguments.run_id)
    with open(arguments.result_file, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
