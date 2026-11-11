"""Sort a review: rate every open item, so that a person with little time sees first what needs them.

    python review_sort.py plan [--week W] [--config C]    what a sort would send, calling nothing
    python review_sort.py sort [--week W] [--config C]    sort a review already built

The weekly pass runs this step right after it writes the review. The rating of an item is
importance, clarity, a one-line reason, a recommended action from that item's allowed actions, and
for an unclear item 2 to 4 short option labels. Before any model call, a script reads each file and
line a monthly finding cites, and records whether the quote still matches.

    reports/YYYY-Www/sort.json    checked by ``schemas.validate_sort_document``

It is keyed by item key and holds no number, so sorting cannot move a number or change the review's
id. It lives beside review.json, so ``review_data.py refresh`` and every session action leave it as
it is. A rating is reused while what the model was shown stays the same, so a retry or a carried
item costs nothing. A decided item has no decision left to sort, and is not rated.

An item without a usable rating is unrated, with the reason, and the page lists it under Unsorted.
Nothing here gives an item a default rating. A failure here stops only the sort: the review is
already written, and the failure goes in its failures. It also adds an entry to the failure marker, so
that the next session starts with an ``Upkeep warning:`` line. A later sort of that week or a later one,
by this command or by a weekly pass, with every open item rated, takes the entry out.

What is sent is data and the prompt says so. It is redacted on the way, as in every model step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

import finding_citations
import memory_store
import model_call
import pass_support
import review_data
import schemas
from config import DEFAULT_CONFIG_PATH, Config, load_config

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "review_sort.md")
USAGE_KEY = "review-sort"
LOCK_FILE = "upkeep.lock"
EXIT_SORT_INCOMPLETE = 1
EXIT_REFUSED = 2
LIST_ITEMS_SENT = 8
FIELDS_NOT_SENT = frozenset({"source", "session", "ref", "role", "identity", "file", "date", "commit", "before", "after", "searched", "fetched", "sources", "existing_tools", "id"})
_CALL_FAULTS = (model_call.ModelCallError, schemas.SchemaError, subprocess.TimeoutExpired, UnicodeDecodeError, ValueError, OSError)


@dataclass(frozen=True)
class _Prepared:
    item: Mapping[str, Any]
    line: str
    digest: str
    citations: list[dict[str, Any]]


def _clipped(value: Any, limit: int) -> Any:
    """A value small enough to send: long text cut, long lists cut, and fields of no use to the rating left out."""
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]} [cut]"
    if isinstance(value, list):
        return [_clipped(entry, limit) for entry in value[:LIST_ITEMS_SENT]]
    if isinstance(value, dict):
        return {key: _clipped(entry, limit) for key, entry in value.items() if key not in FIELDS_NOT_SENT}
    return value


def _details_of(item: Mapping[str, Any], limit: int) -> dict[str, Any]:
    details = {"record": _clipped(item["record"], limit)}
    if item["ledger"] is not None:
        details["ledger"] = _clipped(item["ledger"], limit)
    return details


def _prepare(item: Mapping[str, Any], config: Config, prompt: str) -> _Prepared:
    citations = finding_citations.check_finding_citations(item["record"], config.secrets)
    shown = {
        "section": item["section"],
        "origin": item["origin"],
        "kind": item["record"].get("kind", ""),
        "title": item["title"],
        "allowed": item["allowed"],
        "details": _details_of(item, config.review.sort_field_chars),
        "citations": [{key: citation[key] for key in ("line", "status", "found_line")} for citation in citations],
    }
    # The number stays out of the digest, because a carried item's number changes and its content does not.
    digest = hashlib.sha256(f"{prompt}\n{json.dumps(shown, ensure_ascii=False, sort_keys=True)}".encode("utf-8")).hexdigest()
    line = json.dumps({"id": f"n{item['number']}", **shown}, ensure_ascii=False)
    return _Prepared(item, line, digest, citations)


def _batches(prepared: Sequence[_Prepared], max_items: int, max_chars: int) -> list[list[_Prepared]]:
    """In order, none over either limit. An item over the character limit goes alone."""
    batches: list[list[_Prepared]] = []
    size = 0
    for entry in prepared:
        if not batches or len(batches[-1]) >= max_items or size + len(entry.line) > max_chars:
            batches.append([])
            size = 0
        batches[-1].append(entry)
        size += len(entry.line)
    return batches


def _unrated(digest: str, reason: str, citations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "status": schemas.SORT_ENTRY_UNRATED, "digest": digest, "importance": "", "clarity": "", "reason": "", "recommended": "",
        "options": [], "unrated_reason": reason, "citations": [dict(citation) for citation in citations],
    }


def _rated(prepared: _Prepared, rating: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": schemas.SORT_ENTRY_RATED, "digest": prepared.digest, "importance": rating["importance"], "clarity": rating["clarity"],
        "reason": rating["reason"].strip(), "recommended": rating["recommended"], "options": [option.strip() for option in rating["options"]],
        "unrated_reason": "", "citations": prepared.citations,
    }


def _rate_one(prepared: _Prepared, answers: Sequence[Any], config: Config) -> dict[str, Any]:
    """The entry an item gets from a reply: rated only if answered once, by a rating that holds up."""
    if len(answers) != 1:
        return _unrated(prepared.digest, f"The reply answered this item {len(answers)} times, not once.", prepared.citations)
    try:
        schemas.validate_sort_rating(
            answers[0], prepared.item["allowed"], config.review.sort_reason_max_chars, config.review.sort_option_max_chars, f"item {prepared.item['number']}",
        )
    except schemas.SchemaError as error:
        return _unrated(prepared.digest, f"The reply did not hold up: {error}", prepared.citations)
    return _rated(prepared, answers[0])


def _answers_by_id(reply: Sequence[Any]) -> dict[str, list[Any]]:
    answers: dict[str, list[Any]] = {}
    for rating in reply:
        if isinstance(rating, dict) and isinstance(rating.get("id"), str):
            answers.setdefault(rating["id"], []).append(rating)
    return answers


def _earlier_entries(data_dir: str, week: str) -> dict[str, Mapping[str, Any]]:
    """Ratings that may still hold: this week's, over those of the last week that had a sort."""
    entries: dict[str, Mapping[str, Any]] = {}
    earlier = [name for name in review_data.week_folders(data_dir) if name < week and review_data.read_sort(data_dir, name)[0] is not None]
    for name in [*earlier[-1:], week]:
        document = review_data.read_sort(data_dir, name)[0]
        if document is not None:
            entries.update(document["items"])
    return entries


def _write_sort(data_dir: str, week: str, run_id: str, model: str, cost_usd: float, entries: Mapping[str, Any], now: datetime) -> None:
    document = {
        "schema_version": schemas.SORT_SCHEMA_VERSION, "week": week, "sorted_at": now.isoformat(), "run_id": run_id, "model": model,
        "cost_usd": round(cost_usd, 4), "items": dict(entries),
    }
    schemas.validate_sort_document(document, "sort to write")
    pass_support.write_json(review_data.sort_path(data_dir, week), document)


def _input_of(batch: Sequence[_Prepared], config: Config) -> str:
    lines = "\n".join(entry.line for entry in batch)
    return (
        f"Limits: reason at most {config.review.sort_reason_max_chars} characters, each option at most {config.review.sort_option_max_chars} characters.\n\n"
        f"<items>\n{lines}\n</items>"
    )


def _reply_path(config: Config, week: str, batch: Sequence[_Prepared]) -> str:
    name = hashlib.sha256("\n".join(entry.item["key"] for entry in batch).encode("utf-8")).hexdigest()[:16]
    return os.path.join(config.paths.data_dir, "reports", week, "groups", f"sort-{name}.json")


def _prepared_and_reused(review: Mapping[str, Any], config: Config, prompt: str, entries: dict[str, Any]) -> tuple[list[_Prepared], int]:
    """The open items that need a call. The rest get their entry in ``entries`` here."""
    earlier = _earlier_entries(config.paths.data_dir, review["week"])
    waiting = []
    reused = 0
    for item in review["items"]:
        if item["decision"] is not None:
            continue
        try:
            prepared = _prepare(item, config, prompt)
        except (KeyError, TypeError, AttributeError) as error:
            entries[item["key"]] = _unrated("", f"The item could not be prepared for sorting: {type(error).__name__}: {error}", [])
            continue
        kept = earlier.get(item["key"])
        if kept is not None and kept["status"] == schemas.SORT_ENTRY_RATED and kept["digest"] == prepared.digest:
            entries[item["key"]] = {**kept, "citations": prepared.citations}
            reused += 1
        else:
            waiting.append(prepared)
    return waiting, reused


def _rate_batches(
    batches: Sequence[Sequence[_Prepared]], prompt: str, config: Config, week: str, caller: pass_support.Caller, entries: dict[str, Any],
) -> Optional[str]:
    """Fill in ``entries`` from the model. A batch that fails unrates its own items. A spent budget or
    a reached limit would only fail again, so it unrates what is left. Returns that reason, if any."""
    stopped: Optional[str] = None
    for batch in batches:
        if stopped is not None:
            entries.update({entry.item["key"]: _unrated(entry.digest, stopped, entry.citations) for entry in batch})
            continue
        path = _reply_path(config, week, batch)
        try:
            os.makedirs(config.paths.run_dir, exist_ok=True)
            reply = pass_support.cached_or_called_reply(path, prompt, _input_of(batch, config), config.review.sort_model, USAGE_KEY, caller, schemas.parse_sort_reply)
        except (model_call.BudgetExhaustedError, model_call.LimitReachedError) as error:
            stopped = f"The sort stopped: {error}"
            entries.update({entry.item["key"]: _unrated(entry.digest, stopped, entry.citations) for entry in batch})
            continue
        except _CALL_FAULTS as error:
            reason = f"The model call for this batch failed: {type(error).__name__}: {error}"
            entries.update({entry.item["key"]: _unrated(entry.digest, reason, entry.citations) for entry in batch})
            continue
        answers = _answers_by_id(reply)
        rated = {entry.item["key"]: _rate_one(entry, answers.get(f"n{entry.item['number']}", []), config) for entry in batch}
        entries.update(rated)
        if any(entry["status"] != schemas.SORT_ENTRY_RATED for entry in rated.values()) and os.path.exists(path):
            os.remove(path)  # A retry should ask again, and not read the same answer back.
    return stopped


def _marker_entries_without_sort_warning(path: str, week: str) -> list[Any]:
    """The marker's entries, less the sort's for this week or an earlier one. A marker that cannot
    be read raises, and stays as it is: the session-start hook reports it as broken."""
    if not os.path.exists(path):
        return []
    marker = pass_support.read_json(path)
    if marker["schema_version"] != review_data.MARKER_SCHEMA_VERSION:
        raise ValueError(f"schema_version {marker['schema_version']!r}")
    return [
        entry for entry in marker["entries"]
        if not (entry.get("pass") == review_data.MARKER_PASS_REVIEW and entry.get("kind") == review_data.KIND_SORT_FAILED and entry.get("week", "") <= week)
    ]


def update_sort_warning(data_dir: str, week: str, run_id: str, failure: Optional[str], now: datetime) -> Optional[str]:
    """Raise or clear the session-start warning, in the marker the passes use. ``failure`` is in the
    words the marker keeps: it names counts and no text from a model. Returns what went wrong
    doing this, if anything, since a warning that cannot be written must not cost the sort."""
    path = os.path.join(data_dir, review_data.MARKER_FILE)
    try:
        entries = _marker_entries_without_sort_warning(path, week)
        if failure is not None:
            entries.append({
                "kind": review_data.KIND_SORT_FAILED, "pass": review_data.MARKER_PASS_REVIEW, "run_id": run_id, "at": now.astimezone().isoformat(), "exit_code": EXIT_SORT_INCOMPLETE,
                "summary": failure, "failed_sessions": [], "backlog_sessions": 0, "secrets_redacted": 0, "details": review_data.sort_path(data_dir, week), "week": week,
            })
        if entries:
            pass_support.write_json(path, {"schema_version": review_data.MARKER_SCHEMA_VERSION, "entries": entries})
        elif os.path.exists(path):
            os.remove(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return f"{type(error).__name__}: {error}"
    return None


def sort_review(config: Config, week: str, caller: pass_support.Caller, run_id: str, now: datetime) -> dict[str, Any]:
    """Rate the open items of a review already written, store the ratings, and show them on its page.
    Raises only on a fault of this code or its files; a model call that fails unrates its batch."""
    data_dir = config.paths.data_dir
    review = review_data.load_review(data_dir, week)
    prompt = pass_support.read_text(PROMPT_PATH)
    earlier_document = review_data.read_sort(data_dir, week)[0]
    cost_before = earlier_document["cost_usd"] if earlier_document else 0.0
    spent_at_start = caller.totals.cost_usd
    entries: dict[str, Any] = {}
    waiting, reused = _prepared_and_reused(review, config, prompt, entries)
    batches = _batches(waiting, config.review.sort_batch_items, config.review.sort_batch_chars)
    stopped = _rate_batches(batches, prompt, config, week, caller, entries)
    spent = caller.totals.cost_usd - spent_at_start
    _write_sort(data_dir, week, run_id, config.review.sort_model, cost_before + spent, entries, now)
    review_data.save_with_sort_failures(data_dir, review)
    unrated = sum(1 for entry in entries.values() if entry["status"] != schemas.SORT_ENTRY_RATED)
    failure = f"{unrated} of {len(entries)} open items in the review of {week} could not be sorted, and show under Unsorted. To retry: review_sort.py sort --week {week}." if unrated else None
    return {
        "rated": len(entries) - unrated, "unrated": unrated, "reused": reused, "batches": len(batches), "cost_usd": round(spent, 4), "problem": stopped,
        "warning_problem": update_sort_warning(data_dir, week, run_id, failure, now),
    }


def sort_review_safely(config: Config, week: str, caller: pass_support.Caller, run_id: str, now: datetime) -> dict[str, Any]:
    """For a pass: whatever goes wrong here, the pass goes on and the review says so. A fault of any
    kind is caught on purpose, because the review is written and a sort is not worth losing the rest."""
    try:
        return sort_review(config, week, caller, run_id, now)
    except Exception as error:  # noqa: BLE001 (see above)
        reason = f"The sort step stopped: {type(error).__name__}: {error}"
        try:
            review = review_data.load_review(config.paths.data_dir, week)
            entries = {item["key"]: _unrated("", reason, []) for item in review["items"] if item["decision"] is None}
            _write_sort(config.paths.data_dir, week, run_id, config.review.sort_model, 0.0, entries, now)
            review_data.save_with_sort_failures(config.paths.data_dir, review)
        except Exception as second:  # noqa: BLE001 (see above)
            reason = f"{reason} It could not be recorded either: {type(second).__name__}: {second}"
        failure = f"The sort step of the review of {week} stopped on a fault of {type(error).__name__}. To retry: review_sort.py sort --week {week}."
        return {
            "rated": 0, "unrated": None, "reused": 0, "batches": 0, "cost_usd": 0.0, "problem": reason,
            "warning_problem": update_sort_warning(config.paths.data_dir, week, run_id, failure, now),
        }


def plan_sort(config: Config, week: str) -> dict[str, Any]:
    """What a sort would send now. Writes nothing and calls nothing."""
    prompt = pass_support.read_text(PROMPT_PATH)
    review = review_data.load_review(config.paths.data_dir, week)
    entries: dict[str, Any] = {}
    waiting, reused = _prepared_and_reused(review, config, prompt, entries)
    batches = _batches(waiting, config.review.sort_batch_items, config.review.sort_batch_chars)
    return {
        "week": week,
        "items_open": sum(1 for item in review["items"] if item["decision"] is None),
        "to_rate": len(waiting),
        "reused": reused,
        "could_not_prepare": len(entries) - reused,
        "batches": len(batches),
        "chars_per_batch": [len(_input_of(batch, config)) + len(prompt) for batch in batches],
        "model": config.review.sort_model,
    }


def run_sort_command(config: Config, week: str, call: Callable[..., model_call.ModelResult] = model_call.call_model, now: Optional[datetime] = None) -> dict[str, Any]:
    """Sort a review already built, on its own budget, and commit the data folder as a session action does."""
    moment = now if now is not None else datetime.now(timezone.utc)
    run_id = f"sort-{moment.strftime('%Y%m%d-%H%M%S')}"
    report_dir = os.path.join(config.paths.data_dir, "reports", week)
    caller = pass_support.Caller(config, report_dir, run_id, 0.0, call)
    summary = sort_review_safely(config, week, caller, run_id, moment)
    memory_store.commit_all(config.paths.data_dir, config.memory, f"Sort review {week}, run {run_id}")
    return {"week": week, "run_id": run_id, **summary}


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("plan", "sort"))
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--week", help="the week whose review to sort. The default is the latest")
    arguments = parser.parse_args(argv)
    config = load_config(arguments.config)
    week = arguments.week if arguments.week else review_data.latest_review(config.paths.data_dir)["week"]
    if arguments.action == "plan":
        result = plan_sort(config, week)
    else:
        lock = os.path.join(config.paths.data_dir, LOCK_FILE)
        if os.path.exists(lock):
            print(f"Refused: an upkeep run holds {lock}. Nothing was changed.", file=sys.stderr)
            return EXIT_REFUSED
        result = run_sort_command(config, week)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return EXIT_SORT_INCOMPLETE if arguments.action == "sort" and (result["unrated"] != 0 or result["problem"]) else 0


if __name__ == "__main__":
    sys.exit(main())
