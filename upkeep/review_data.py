"""review.json: what one review session is about, and the numbers that session uses.

Built by the weekly pass from its report, the previous review and any monthly results, and written
next to the report. The page is rendered from it by ``review_page.py``, and ``review_session.py``
checks every action against it. Knows no git and no model.

    reports/YYYY-Www/review.json    schema version 1, checked by ``schemas.validate_review``
    reports/YYYY-Www/review.html    the page

review.json:

    review_id        a hash of the numbers and keys, so a session can tell if they moved
    week, run_id, built_at, report_status, stop_reason, apply_enabled, coverage, usage
    weeks_overdue    whole ISO weeks from the oldest report with something open that no review
                     action has followed, to now
    last_action_at   when something was last decided in this review, or null
    failures[]       kind, summary: failed or stopped pass, failure marker entries, skipped windows,
                     items that could not be read, and four that fail nothing: possible renames, what
                     the stance check did, rules broken at a cost, and an item's own faults, per item
    items[]          number, key, section memory|proposal, origin weekly|monthly, week (the item's
                     original week), carried, title, allowed[], decision {outcome, at, detail} or
                     null, skipped_at, ledger, record (the report's record, unchanged)
    held[], rejected[], failures_ranked[], before_after[]    shown, not numbered

Numbers run across sections, newest week first in each. They change only when a review is built.

An item stays open until it is decided. A review carries forward the open items of the review
before it with their original week, and a pass offering the same thing again does not add a second
item. A review built again in its own week keeps what it held, because a retry finds nothing new
and a change already applied must stay here to be undone. A change that would have applied in a
trial run is not kept or carried: it never happened, and the next pass works it out again.

How the monthly pass joins: it writes ``reports/monthly/<name>.json``,

    {"schema_version": 1, "source": "monthly", "run_id": "...", "generated_at": "<with offset>",
     "proposals": [<records with the same fields as the weekly report's proposals>]}

and the next review built takes each proposal no earlier review has shown.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

import extract
import ledger
import review_page
import schemas
import weekly_notes
from config import DEFAULT_CONFIG_PATH, Config, load_config

_WEEK_FOLDER_RE = re.compile(r"^\d{4}-W\d{2}$")
REVIEW_FILE = "review.json"
PAGE_FILE = "review.html"
REPORT_FILE = "report.json"
MONTHLY_FOLDER = "monthly"
FEED_SCHEMA_VERSION = 1
FEED_FIELDS = frozenset({"schema_version", "source", "run_id", "generated_at", "proposals"})
MARKER_FILE = "failure-marker.json"
MARKER_SCHEMA_VERSION = 1
LEDGER_LATEST_SHOWN = 3
STATUS_OK = "ok"
KIND_ITEM_PROBLEM = "item_problem"
KIND_POSSIBLE_RENAME = review_page.KIND_POSSIBLE_RENAME
KIND_STANCE_CHECK = review_page.KIND_STANCE_CHECK
KIND_RULE_BROKEN = review_page.KIND_RULE_BROKEN
KIND_MALFUNCTION = review_page.KIND_MALFUNCTION
USAGE_STAMP = "%Y-%m-%dT%H:%M:%S%z"
ALREADY_OPEN = "already_open"
OUTCOME_APPLIED = schemas.OUTCOME_APPLIED
OUTCOME_WOULD_APPLY = schemas.OUTCOME_WOULD_APPLY
KIND_MEMORY_FACT = "memory_fact"
KIND_MEMORY_SPLIT = "memory_split_claim"
KIND_MEMORY_DELETION = "memory_deletion"
KIND_MEMORY_REVISION = "memory_revision"
KIND_ITEM_REVISION = "item_revision"
_MEMORY_PROPOSAL_KINDS = frozenset({KIND_MEMORY_FACT, KIND_MEMORY_SPLIT, KIND_MEMORY_DELETION, KIND_MEMORY_REVISION})
_TITLE_OF_ACTION = {
    schemas.ACTION_CREATE: "New memory",
    schemas.ACTION_ADD: "Added to memory",
    schemas.ACTION_REPLACE: "Changed in memory",
    schemas.ACTION_REMOVE: "Removed from memory",
    schemas.ACTION_DELETE: "Deleted memory",
}
ALLOWED_APPLIED = [schemas.ACTION_UNDO, schemas.ACTION_KEEP, schemas.ACTION_SKIP, schemas.ACTION_WHY]
ALLOWED_WOULD_APPLY = [schemas.ACTION_UNDO, schemas.ACTION_SKIP, schemas.ACTION_WHY]
ALLOWED_PROPOSAL = [schemas.ACTION_APPROVE, schemas.ACTION_REJECT, schemas.ACTION_SKIP, schemas.ACTION_WHY]


# Entries that neither side of the balance reads: their direction, their kind on the page, and what to make of them.
_COUNTED_APART = (
    (schemas.DIRECTION_RULE_BROKEN, KIND_RULE_BROKEN, "If this repeats, the rule may need revising."),
    (schemas.DIRECTION_MALFUNCTION, KIND_MALFUNCTION, "Once in a session looks like nothing. The same fault in many sessions may need fixing."),
)


class ReviewDataError(ValueError):
    """A review or a file it is built from is not what it should be."""


def iso_week_of(moment: datetime) -> str:
    year, week, _ = moment.astimezone().isocalendar()
    return f"{year}-W{week:02d}"


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def reports_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "reports")


def review_path(data_dir: str, week: str) -> str:
    return os.path.join(reports_dir(data_dir), week, REVIEW_FILE)


def page_path(data_dir: str, week: str) -> str:
    return os.path.join(reports_dir(data_dir), week, PAGE_FILE)


def week_folders(data_dir: str) -> list[str]:
    """ISO week folders, oldest first. A folder set aside under another name is not a week."""
    root = reports_dir(data_dir)
    return sorted(name for name in os.listdir(root) if _WEEK_FOLDER_RE.fullmatch(name)) if os.path.isdir(root) else []


def load_review(data_dir: str, week: str) -> dict[str, Any]:
    path = review_path(data_dir, week)
    review = _read_json(path)
    schemas.validate_review(review, path)
    return review


def latest_review(data_dir: str) -> dict[str, Any]:
    """The review of the newest week that has one. None at all raises."""
    weeks = [week for week in week_folders(data_dir) if os.path.isfile(review_path(data_dir, week))]
    if not weeks:
        raise FileNotFoundError(f"no review under {reports_dir(data_dir)}")
    return load_review(data_dir, weeks[-1])


def save_review(data_dir: str, review: Mapping[str, Any]) -> str:
    """Validate, write review.json, render the page. Returns the page's path."""
    schemas.validate_review(review, "review to write")
    extract.write_json_atomic(review_path(data_dir, review["week"]), review)
    target = page_path(data_dir, review["week"])
    temporary = f"{target}.tmp-{os.getpid()}"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(review_page.render_page(review))
    os.replace(temporary, target)
    return target


def deletion_parts(exact_change: str) -> tuple[str, str, str]:
    """(action, memory, old text) of a deletion proposal, from "<action> <memory>: <old text>"."""
    head, separator, old_text = exact_change.partition(": ")
    action, _, memory = head.partition(" ")
    if not separator or not memory or action not in schemas.DELETING_ACTIONS or (action == schemas.ACTION_REMOVE and not old_text):
        raise ReviewDataError(f"deletion proposal with an unreadable change: {exact_change[:80]!r}")
    return action, memory, old_text


def item_of(section: str, record: Mapping[str, Any]) -> Optional[ledger.ItemId]:
    """The ledger item a record is about, if it names one that can have a ledger."""
    if section == schemas.SECTION_MEMORY:
        return ledger.ItemId(ledger.project_scope(record["project_folder"]), ledger.KIND_MEMORY, record["memory"])
    kind = record["kind"]
    if kind == KIND_MEMORY_DELETION:
        return ledger.ItemId(ledger.project_scope(record["project_folder"]), ledger.KIND_MEMORY, deletion_parts(record["exact_change"])[1])
    if kind in _MEMORY_PROPOSAL_KINDS:
        return ledger.ItemId(ledger.project_scope(record["project_folder"]), ledger.KIND_MEMORY, record["target"])
    if kind == KIND_ITEM_REVISION:
        return ledger.ItemId(**record["evidence"]["identity"])
    if kind in schemas.ITEM_KINDS and record["target"]:
        return ledger.ItemId(ledger.SCOPE_GLOBAL, kind, record["target"])
    return None


def ledger_summary(ledgers_dir: str, section: str, record: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """What the page shows of an item's ledger. One that cannot be read is listed for the review,
    and the page says only that nothing is recorded."""
    item = item_of(section, record)
    if item is None or not ledger.item_exists(ledgers_dir, item):
        return None
    try:
        document = ledger.load_ledger(ledgers_dir, item)
    except ledger.UNREADABLE as error:
        ledger.add_item_problems(ledgers_dir, [{"what": f"{item.kind} {item.name}", "detail": f"{type(error).__name__}: {error}"}])
        return None
    entries = document["entries"]
    latest = sorted(entries, key=lambda entry: datetime.fromisoformat(entry["date"]), reverse=True)[:LEDGER_LATEST_SHOWN]
    return {
        "identity": item.to_json(),
        "file": os.path.relpath(ledger.ledger_path(ledgers_dir, item), os.path.dirname(ledgers_dir)).replace(os.sep, "/"),
        "founding_reason": document["founding"]["reason"],
        "founding_status": document["founding"]["status"],
        "entries_for": sum(1 for entry in entries if entry["direction"] == schemas.STANCE_FOR),
        "entries_against": sum(1 for entry in entries if entry["direction"] == schemas.STANCE_AGAINST),
        "latest": [{key: entry[key] for key in ("date", "direction", "who", "basis", "what")} for entry in latest],
    }


def _memory_item(change: Mapping[str, Any], week: str, ledgers_dir: str) -> dict[str, Any]:
    applied = change["outcome"] == OUTCOME_APPLIED
    return {
        "number": 0,
        "key": f"memory:{change['id']}",
        "section": schemas.SECTION_MEMORY,
        "origin": schemas.ORIGIN_WEEKLY,
        "week": week,
        "carried": False,
        "title": f"{_TITLE_OF_ACTION[change['action']]}: {change['memory']}",
        "allowed": list(ALLOWED_APPLIED if applied else ALLOWED_WOULD_APPLY),
        "decision": None,
        "skipped_at": None,
        "ledger": ledger_summary(ledgers_dir, schemas.SECTION_MEMORY, change),
        "record": dict(change),
    }


def _proposal_item(proposal: Mapping[str, Any], week: str, origin: str, ledgers_dir: str) -> dict[str, Any]:
    wording = hashlib.sha256(f"{proposal['title']}\n{proposal['what']}".encode("utf-8")).hexdigest()[:10]
    return {
        "number": 0,
        "key": f"proposal:{proposal['id']}:{wording}",
        "section": schemas.SECTION_PROPOSAL,
        "origin": origin,
        "week": week,
        "carried": False,
        "title": proposal["title"],
        "allowed": list(ALLOWED_PROPOSAL),
        "decision": None,
        "skipped_at": None,
        "ledger": ledger_summary(ledgers_dir, schemas.SECTION_PROPOSAL, proposal),
        "record": dict(proposal),
    }


def _monthly_items(data_dir: str, ledgers_dir: str, seen: set[str]) -> list[dict[str, Any]]:
    items = []
    pattern = os.path.join(glob.escape(reports_dir(data_dir)), MONTHLY_FOLDER, "*.json")
    for path in sorted(glob.glob(pattern)):
        feed = _read_json(path)
        if set(feed) != FEED_FIELDS or feed["schema_version"] != FEED_SCHEMA_VERSION or feed["source"] != schemas.ORIGIN_MONTHLY:
            raise ReviewDataError(f"{path}: not a monthly result")
        generated = datetime.fromisoformat(feed["generated_at"])
        if generated.tzinfo is None:
            raise ReviewDataError(f"{path}: generated_at has no UTC offset")
        for proposal in feed["proposals"]:
            if set(proposal) != schemas.WEEKLY_PROPOSAL_FIELDS:
                raise ReviewDataError(f"{path}: proposal {proposal.get('id')!r} does not have the report's fields")
            item = _proposal_item(proposal, iso_week_of(generated), schemas.ORIGIN_MONTHLY, ledgers_dir)
            if item["key"] not in seen:
                items.append(item)
    return items


def _keys_in_reviews_before(data_dir: str, week: str) -> set[str]:
    return {
        item["key"]
        for earlier in week_folders(data_dir)
        if earlier < week and os.path.isfile(review_path(data_dir, earlier))
        for item in load_review(data_dir, earlier)["items"]
    }


def _monday_of(week: str) -> date:
    year, number = week.split("-W")
    return date.fromisocalendar(int(year), int(number), 1)


def weeks_overdue(data_dir: str, now: datetime, last_action_here: Optional[str] = None, building: Optional[tuple[str, bool]] = None) -> int:
    """Whole ISO weeks from the oldest report with something open that no review action has
    followed, to now. An action is only ever taken on an item, so a week with nothing to act on
    cannot be overdue. ``building`` is the week of a review not yet on disk, and whether it holds
    anything open."""
    actions = [last_action_here] if last_action_here else []
    reports = []
    for week in week_folders(data_dir):
        has_open = False
        if os.path.isfile(review_path(data_dir, week)):
            review = _read_json(review_path(data_dir, week))
            has_open = any(item["decision"] is None for item in review["items"])
            action = review["last_action_at"]
            if action:
                actions.append(action)
        if building is not None and building[0] == week:
            has_open = building[1]
        path = os.path.join(reports_dir(data_dir), week, REPORT_FILE)
        if has_open and os.path.isfile(path):
            reports.append((week, datetime.fromisoformat(_read_json(path)["generated_at"])))
    last_action = max(map(datetime.fromisoformat, actions)) if actions else None
    waiting = [week for week, generated in reports if last_action is None or generated > last_action]
    if not waiting:
        return 0
    return max(0, (_monday_of(iso_week_of(now)) - _monday_of(waiting[0])).days // 7)


def _stance_cost(data_dir: str, since: datetime) -> float:
    """What the stance check cost since then, from the run-wide usage log. No log means no call yet.
    A line a one-off call wrote there names no session, so it is not the check's."""
    path = os.path.join(data_dir, "logs", "usage.jsonl")
    if not os.path.exists(path):
        return 0.0
    with open(path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    return sum(
        record["cost_usd"] for record in records
        if record.get("session") == ledger.STANCE_USAGE_KEY and datetime.strptime(record["at"], USAGE_STAMP) > since
    )


def _signals(data_dir: str, window_days: int, now: datetime) -> list[dict[str, str]]:
    """Inside the window: what the stance check did and cost, each item with a rule broken at a cost, and
    each item with a fault of its own. They fail nothing, and are shown only if there is something to show."""
    since = now - timedelta(days=window_days)
    ledgers_dir = ledger.ledgers_dir_of(data_dir)
    signals = []
    path = os.path.join(ledgers_dir, ledger.VERDICTS_FILE)
    if os.path.exists(path):
        recent = [mention for mention in _read_json(path)["mentions"] if datetime.fromisoformat(mention["date"]) > since]
        if recent:
            counts = ", ".join(f"{sum(1 for mention in recent if mention['verdict'] == verdict)} {verdict}" for verdict in schemas.STANCE_VERDICTS)
            signals.append({
                "kind": KIND_STANCE_CHECK,
                "summary": f"In the last {window_days} days the check judged {len(recent)} stances: {counts}. It cost ${_stance_cost(data_dir, since):.2f}. "
                           f"Each verdict and its reason is in ledgers/{ledger.VERDICTS_FILE}.",
            })
    for document in ledger.iter_ledgers(ledgers_dir, []):  # What cannot be read is listed by the pass that writes item-problems.json.
        for direction, kind, closing in _COUNTED_APART:
            found = sorted(
                (entry for entry in document["entries"] if entry["direction"] == direction and datetime.fromisoformat(entry["date"]) > since),
                key=lambda entry: entry["date"],
            )
            if found:
                identity = document["identity"]
                times = f"{len(found)} time{'' if len(found) == 1 else 's'}"
                sessions = len({entry["session"] for entry in found})
                signals.append({
                    "kind": kind,
                    "summary": f"{identity['kind']} {identity['name']}: {times} in {sessions} session{'' if sessions == 1 else 's'} in the last {window_days} days, not counted for or against. "
                               f"Latest: {found[-1]['what']} {closing}",
                })
    return signals


def _failures(data_dir: str, status: str, stop_reason: Optional[str], coverage: Mapping[str, Any], window_days: int, now: datetime) -> list[dict[str, str]]:
    failures = []
    held = ledger.read_item_problems(ledger.ledgers_dir_of(data_dir))
    if status != STATUS_OK:
        unfinished = "the pass went through to the end, and is marked failed because of what is listed here" if held["problems"] else "the last weekly pass did not finish"
        failures.append({"kind": status, "summary": stop_reason if stop_reason else unfinished})
    skipped = coverage.get("windows_skipped", [])
    if skipped:
        failures.append({"kind": "windows_skipped", "summary": f"{len(skipped)} conversation windows could not be read this week"})
    marker_path = os.path.join(data_dir, MARKER_FILE)
    if os.path.exists(marker_path):
        marker = _read_json(marker_path)
        if marker.get("schema_version") != MARKER_SCHEMA_VERSION:
            raise ReviewDataError(f"{marker_path}: schema_version {marker.get('schema_version')!r}")
        failures.extend({"kind": entry["kind"], "summary": entry["summary"]} for entry in marker["entries"])
    failures.extend({"kind": KIND_ITEM_PROBLEM, "summary": f"{problem['what']} could not be read. {problem['detail']}"} for problem in held["problems"])
    failures.extend({"kind": KIND_POSSIBLE_RENAME, "summary": f"{rename['what']}. {rename['detail']}"} for rename in held["possible_renames"])
    failures.extend(_signals(data_dir, window_days, now))
    return failures


def _review_id(items: Sequence[Mapping[str, Any]]) -> str:
    lines = "\n".join(f"{item['number']}:{item['key']}" for item in items)
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()[:12]


def _number(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Memory first, then proposals; newest week first in each, otherwise in the order given."""
    ordered = []
    for section in (schemas.SECTION_MEMORY, schemas.SECTION_PROPOSAL):
        ordered.extend(sorted((item for item in items if item["section"] == section), key=lambda item: item["week"], reverse=True))
    return [{**item, "number": position} for position, item in enumerate(ordered, 1)]


def _repeats_a_carried_proposal(proposal: Mapping[str, Any], carried: Sequence[Mapping[str, Any]], overlap: float) -> bool:
    """True if this is an open item offered again: the pass says so, or it is the same kind on the
    same target in much the same words, since a model does not reword the same way twice."""
    for record in carried:
        if proposal["status"] == ALREADY_OPEN and proposal["id"] == record["id"]:
            return True
        same_target = all(proposal[key] == record[key] for key in ("kind", "target", "project_folder"))
        if same_target and weekly_notes.word_overlap(proposal["what"], record["what"]) >= overlap:
            return True
    return False


def build_review(config: Config, report: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """The review of a report. A review already built this week keeps its decisions and skips."""
    data_dir = config.paths.data_dir
    ledgers_dir = ledger.ledgers_dir_of(data_dir)
    week = report["week"]
    same_week = load_review(data_dir, week) if os.path.isfile(review_path(data_dir, week)) else None
    earlier_weeks = [name for name in week_folders(data_dir) if name < week and os.path.isfile(review_path(data_dir, name))]
    earlier = load_review(data_dir, earlier_weeks[-1]) if earlier_weeks else None

    by_key: dict[str, dict[str, Any]] = {}
    earlier_seen = {item["key"]: item for item in (same_week["items"] if same_week else [])}
    if same_week:
        for item in same_week["items"]:
            trial = item["section"] == schemas.SECTION_MEMORY and item["record"]["outcome"] == OUTCOME_WOULD_APPLY
            if item["decision"] is not None or not trial:
                by_key[item["key"]] = item
    if earlier:
        for item in earlier["items"]:
            if item["decision"] is not None or item["key"] in by_key:
                continue
            if item["section"] == schemas.SECTION_MEMORY and item["record"]["outcome"] == OUTCOME_WOULD_APPLY:
                continue
            kept = earlier_seen.get(item["key"], item)
            refreshed = ledger_summary(ledgers_dir, item["section"], item["record"])
            by_key[item["key"]] = {**item, "carried": True, "skipped_at": kept["skipped_at"], "ledger": refreshed}
    carried_proposals = [item["record"] for item in by_key.values() if item["section"] == schemas.SECTION_PROPOSAL]

    fresh = [_memory_item(change, week, ledgers_dir) for change in report["memory_changes"]]
    for proposal in report["proposals"]:
        if not _repeats_a_carried_proposal(proposal, carried_proposals, config.weekly.reproposal_word_overlap):
            fresh.append(_proposal_item(proposal, week, schemas.ORIGIN_WEEKLY, ledgers_dir))
    fresh.extend(_monthly_items(data_dir, ledgers_dir, _keys_in_reviews_before(data_dir, week)))
    for item in fresh:
        if item["key"] in by_key:
            continue
        previous = earlier_seen.get(item["key"])
        by_key[item["key"]] = item if previous is None else {**item, "skipped_at": previous["skipped_at"]}

    items = _number(list(by_key.values()))
    last_action = same_week["last_action_at"] if same_week else None
    coverage = report["coverage"]
    return {
        "schema_version": schemas.REVIEW_SCHEMA_VERSION,
        "review_id": _review_id(items),
        "week": week,
        "run_id": report["run_id"],
        "built_at": now.isoformat(),
        "report_status": report["status"],
        "stop_reason": report["stop_reason"],
        "apply_enabled": report["apply_enabled"],
        "weeks_overdue": weeks_overdue(data_dir, now, last_action, (week, any(item["decision"] is None for item in items))),
        "last_action_at": last_action,
        "failures": _failures(data_dir, report["status"], report["stop_reason"], coverage, config.ledger.inferred_window_days, now),
        "coverage": coverage,
        "usage": report["usage"],
        "items": items,
        "held": report["held"],
        "rejected": report["rejected"],
        "failures_ranked": report["failures_ranked"][: config.review.failures_shown],
        "before_after": report["before_after"],
    }


def write_review(config: Config, report: Mapping[str, Any], now: datetime) -> str:
    """Build the review of this report and render its page. Returns the page's path."""
    return save_review(config.paths.data_dir, build_review(config, report, now))


def refresh_review(config: Config, now: datetime) -> str:
    """Bring the overdue count and the failures of the latest review up to now, and render it
    again. Numbers and items stay as they are. Returns the page's path."""
    data_dir = config.paths.data_dir
    review = latest_review(data_dir)
    review["weeks_overdue"] = weeks_overdue(data_dir, now, review["last_action_at"])
    review["failures"] = _failures(data_dir, review["report_status"], review["stop_reason"], review["coverage"], config.ledger.inferred_window_days, now)
    return save_review(data_dir, review)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("build", "refresh"))
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--week", help="for build: the week whose report to read")
    arguments = parser.parse_args(argv)
    config = load_config(arguments.config)
    now = datetime.now(timezone.utc)
    if arguments.action == "build":
        if not arguments.week:
            parser.error("build needs --week")
        report_path = os.path.join(reports_dir(config.paths.data_dir), arguments.week, REPORT_FILE)
        report = _read_json(report_path)
        schemas.validate_weekly_report(report, report_path)
        print(write_review(config, report, now))
    else:
        print(refresh_review(config, now))
    return 0


if __name__ == "__main__":
    sys.exit(main())
