"""Tool-less model calls, on whether the stances the notes took on items hold, in either direction.

The reading of a session sees only the session and a short description of each item, so it can credit
an item with something the item has no part in, and it can miss what the item's contents would show.
Each stance, no bearing included, goes here with its note and the item's real description and contents,
redacted. The check may keep it, raise a no bearing to for or against, lower or refuse a for or against,
or reverse it, with a reason, and it says three things only it can tell: whether the user's quote is about
this item, which decides what counts as direct, whether a rule of the item was broken at a cost, and whether
a hook, tool server or plugin went wrong by itself once in the session.
Every verdict is listed in ``ledgers/stance-verdicts.json``, and its counts and cost reach the review.

An item's stances go in one call, so that like cases are seen together, and with its latest verdicts from
earlier passes, so that they stay alike across passes. A long list is split by ``item_check.group_chars``.

Verdicts stay in ``stance-checks.json`` beside the notes of their window, so discarding a window takes
them along, and a stance judged once is not judged again. A stance with no verdict yet makes no entry
and waits for the next pass. A call that fails, or a reply that does not answer each stance sent exactly
once, leaves its stances waiting, and what earlier calls settled stays. A verdict that does not fit its
stance is dropped alone: a script cannot tell which half of it was meant, so its stance waits too, the rest
of the reply is stored, and the run ends failed with the verdict listed.

The model comes from config: ``item_check.model``. See ``docs/verification.md`` for the two compared.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

import backfill
import ledger
import model_call
import render
import schemas
from config import DEFAULT_CONFIG_PATH, Config, load_config

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "stance_check.md")
USAGE_LOG = "stance-check-usage.jsonl"
REJECTED_REPLY = "stance-check.rejected"
_STANCES_WITH_ENTRY = (schemas.STANCE_FOR, schemas.STANCE_AGAINST)
GONE = "This item is no longer installed, so only its name is known."


def _read_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as handle:
        return handle.read()


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\n...[CUT {len(text) - limit} chars]"


def _ruling_line(ruling: Mapping[str, str]) -> str:
    broken = ", rule broken at a cost" if ruling["rule_broken"] else ""
    fault = ", a fault of its own, once" if ruling["malfunction"] else ""
    return f"- {ruling['final']}{broken}{fault}. Note: {ruling['what']} Reason: {ruling['reason']}"


def _item_block(ref: str, identity: ledger.ItemId, known: Optional[backfill.Item], rulings: Sequence[Mapping[str, str]], config: Config) -> str:
    if known is None:
        description, contents = "", GONE
    else:
        description, contents = known.description, backfill.contents_of(known)
    body = f"description: {description}\ncontents:\n{_cut(contents, config.item_check.item_chars)}"
    if rulings:
        body += "\nearlier rulings on this item:\n" + "\n".join(_ruling_line(ruling) for ruling in rulings)
    return f'<item ref="{ref}" kind="{identity.kind}" name="{identity.name}">\n{render.neutralise_tags(body)}\n</item>'


def _stance_line(position: int, ref: str, mention: ledger.StanceMention) -> str:
    note = mention.note
    return json.dumps({
        "id": f"s{position}",
        "item": ref,
        "kind": mention.item.kind,
        "name": mention.item.name,
        "stance": mention.reference.stance,
        "note_type": note["type"],
        "what": note["what"],
        "evidence": note["evidence"],
        "endorsement": note["endorsement"],
        "user_quote": note["endorsement_quote"] if note["quote_check"] == schemas.QUOTE_VERIFIED else "",
        "origin": note["origin_of_point"],
    }, ensure_ascii=False)


def stance_input(pending: Sequence[ledger.StanceMention], known: Mapping[ledger.ItemId, backfill.Item], rulings: Mapping[ledger.ItemId, Sequence[Mapping[str, str]]], config: Config) -> str:
    """Each item once, then one line per stance naming it."""
    refs: dict[ledger.ItemId, str] = {}
    for mention in pending:
        refs.setdefault(mention.item, f"i{len(refs) + 1}")
    items = "\n".join(_item_block(ref, item, known.get(item), rulings.get(item, ()), config) for item, ref in refs.items())
    lines = render.neutralise_tags("\n".join(_stance_line(position, refs[mention.item], mention) for position, mention in enumerate(pending, 1)))
    return f"<items>\n{items}\n</items>\n\n<stances>\n{lines}\n</stances>\n"


def _groups(pending: Sequence[ledger.StanceMention], known: Mapping[ledger.ItemId, backfill.Item], rulings: Mapping[ledger.ItemId, Sequence[Mapping[str, str]]], config: Config) -> list[list[ledger.StanceMention]]:
    """The stances split for separate calls, each item's together. One item over the limit is a group
    of its own, and whether it fits is the call's question."""
    by_item: dict[ledger.ItemId, list[ledger.StanceMention]] = {}
    for mention in pending:
        by_item.setdefault(mention.item, []).append(mention)
    groups: list[list[ledger.StanceMention]] = []
    current: list[ledger.StanceMention] = []
    held = 0
    for mentions in by_item.values():
        size = len(stance_input(mentions, known, rulings, config))
        if current and held + size > config.item_check.group_chars:
            groups.append(current)
            current, held = [], 0
        current = [*current, *mentions]
        held += size
    return [*groups, current] if current else groups


def _known_by_identity(found: backfill.InventoryScan) -> dict[ledger.ItemId, backfill.Item]:
    return {item.id: item for item in found.items}


def _verdict_problem(verdict: schemas.StanceVerdict, mention: ledger.StanceMention) -> Optional[str]:
    """What is wrong with a verdict, given the stance it answers."""
    before, after = mention.reference.stance, verdict.stance
    fits = {
        schemas.VERDICT_KEPT: after == before,
        schemas.VERDICT_RAISED: before == schemas.STANCE_NO_BEARING and after in _STANCES_WITH_ENTRY,
        schemas.VERDICT_LOWERED: before in _STANCES_WITH_ENTRY and after == schemas.STANCE_NO_BEARING,
        schemas.VERDICT_REFUSED: before in _STANCES_WITH_ENTRY and after == schemas.STANCE_NO_BEARING,
        schemas.VERDICT_REVERSED: before in _STANCES_WITH_ENTRY and after in _STANCES_WITH_ENTRY and after != before,
    }
    if not fits[verdict.verdict]:
        return f"verdict {verdict.verdict!r} does not fit {before!r} becoming {after!r}"
    if verdict.rule_broken and after != schemas.STANCE_NO_BEARING:
        return f"a rule broken counts neither way, but the stance is {after!r}"
    if verdict.malfunction and after != schemas.STANCE_NO_BEARING:
        return f"a fault of its own counts neither way, but the stance is {after!r}"
    if verdict.malfunction and verdict.rule_broken:
        return "a fault of the item itself cannot also be a rule of it the assistant broke"
    if verdict.malfunction and mention.item.kind not in schemas.KINDS_THAT_ACT:
        return f"a {mention.item.kind} is followed, it does not act, so it has no fault of its own"
    if verdict.quote_about_item and mention.note["quote_check"] != schemas.QUOTE_VERIFIED:
        return "quote_about_item is true for a stance with no verified quote"
    return None


def _checked_verdicts(text: str, group: Sequence[ledger.StanceMention]) -> tuple[dict[str, schemas.StanceVerdict], dict[str, str]]:
    """The verdicts that fit, by id, and what is wrong with each that does not. Raises if the reply is
    not one answer to each stance sent."""
    verdicts = schemas.parse_stance_verdicts(text)
    by_id = {verdict.id: verdict for verdict in verdicts}
    wanted = {f"s{position}" for position in range(1, len(group) + 1)}
    if len(verdicts) != len(by_id) or set(by_id) != wanted:
        raise schemas.SchemaError(f"the stance check must answer each stance once: expected {len(wanted)}, got ids {sorted(by_id)}")
    problems: dict[str, str] = {}
    for position, mention in enumerate(group, 1):
        problem = _verdict_problem(by_id[f"s{position}"], mention)
        if problem is not None:
            problems[f"s{position}"] = problem
    return {key: verdict for key, verdict in by_id.items() if key not in problems}, problems


def dropped_line(dropped: Sequence[Mapping[str, Any]]) -> str:
    """How many, which and why, in one line. An id means something only within its call."""
    return f"{len(dropped)} stance verdicts dropped: " + "; ".join(f"call {item['call']} {item['id']}: {item['problem']}" for item in dropped)


def check_pending(
    config: Config, run_id: str, budget_usd: float, call: Callable[..., model_call.ModelResult], dropped: list[dict[str, Any]],
) -> dict[str, Any]:
    """Judge every stance with no verdict yet. A verdict that does not fit its stance goes on ``dropped``,
    which holds it even if a later call raises, and the rest of its reply is stored. Raises if a call or
    its reply fails: what that call was given stays unjudged, and what earlier calls settled stays."""
    data_dir = config.paths.data_dir
    ledgers_dir = ledger.ledgers_dir_of(data_dir)
    synced = backfill.sync_items(config, datetime.now(timezone.utc))  # An item new today needs its ledger to be resolved.
    found = backfill.scan_inventory(config)
    notes_dir = os.path.join(data_dir, "notes")
    pending = list(ledger.pending_stances(notes_dir, ledgers_dir, backfill.display_names(found)))
    summary = {
        "stances_checked": len(pending), "calls": 0, "cost_usd": 0.0, "input_chars": 0, "rule_broken": 0, "malfunction": 0, "dropped": 0,
        **dict.fromkeys(schemas.STANCE_VERDICTS, 0),
        ledger.OUTCOME_CREATED: synced[ledger.OUTCOME_CREATED], ledger.OUTCOME_CASE_RENAMED: synced[ledger.OUTCOME_CASE_RENAMED],
    }
    if not pending:
        return summary
    known = _known_by_identity(found)
    rulings = ledger.earlier_rulings(notes_dir, config.item_check.earlier_rulings_shown)
    prompt = _read_prompt()
    rejected_written = False

    def log_rejected(text: str) -> None:
        """A run's rejected replies stay together, and replace those of an earlier run."""
        nonlocal rejected_written
        mode, start = ("a", "\n") if rejected_written else ("w", "")
        with open(os.path.join(data_dir, "logs", REJECTED_REPLY), mode, encoding="utf-8") as handle:
            handle.write(start + render.redact_secrets(text, config.secrets))
        rejected_written = True

    for group in _groups(pending, known, rulings, config):
        sent, _ = render.redact_counted(stance_input(group, known, rulings, config), config.secrets)
        summary["input_chars"] += len(sent)
        result = call(
            prompt=prompt,
            stdin_text=sent,
            tools=(),
            model=config.item_check.model,
            max_budget_usd=budget_usd - summary["cost_usd"],
            cwd=config.paths.run_dir,
            claude_exe=config.paths.claude_exe,
            model_config=config.model,
            chunking_config=config.chunking,
            usage_log_path=os.path.join(data_dir, "logs", USAGE_LOG),
        )
        summary["cost_usd"] += result.cost_usd
        summary["calls"] += 1
        try:
            by_id, problems = _checked_verdicts(result.text, group)
        except schemas.SchemaError:
            log_rejected(result.text)
            raise
        if problems:
            log_rejected(result.text)
        by_window: dict[str, dict[str, dict[str, Any]]] = {}
        for position, mention in enumerate(group, 1):
            stance_id = f"s{position}"
            if stance_id in problems:
                summary["dropped"] += 1
                dropped.append({
                    "call": summary["calls"],
                    "id": stance_id,
                    "kind": mention.item.kind,
                    "name": mention.item.name,
                    "stance_at": f"{os.path.relpath(mention.window_dir, notes_dir).replace(os.sep, '/')}/{mention.key}",
                    "problem": problems[stance_id],
                })
                continue
            verdict = by_id[stance_id]
            summary[verdict.verdict] += 1
            summary["rule_broken"] += verdict.rule_broken
            summary["malfunction"] += verdict.malfunction
            by_window.setdefault(mention.window_dir, {})[mention.key] = {
                "stance": mention.reference.stance,
                "final": verdict.stance,
                "verdict": verdict.verdict,
                "quote_about_item": verdict.quote_about_item,
                "rule_broken": verdict.rule_broken,
                "malfunction": verdict.malfunction,
                "reason": render.redact_secrets(verdict.reason, config.secrets),
                "item": mention.item.to_json(),
                "what": mention.note["what"],
                "run_id": run_id,
            }
        for window_dir, checks in by_window.items():
            ledger.add_stance_checks(window_dir, checks)
    return summary


def rejudge_old(config: Config) -> dict[str, int]:
    """Forget verdicts from before this version of the check, and the ledger entries they let through,
    so that the next pass judges those stances again under today's rules. Nothing else is touched."""
    data_dir = config.paths.data_dir
    ledgers_dir = ledger.ledgers_dir_of(data_dir)
    outcome = {"verdict_files_removed": 0, "ledger_entries_removed": 0}
    for path in glob.glob(os.path.join(glob.escape(data_dir), "notes", "*", "*", ledger.STANCE_CHECKS_FILE)):
        with open(path, encoding="utf-8") as handle:
            version = json.load(handle)["schema_version"]
        if version == ledger.STANCE_CHECKS_SCHEMA_VERSION:
            continue
        window = os.path.dirname(path)
        prefix = f"notes/{os.path.basename(os.path.dirname(window))}/{os.path.basename(window)}/"
        outcome["ledger_entries_removed"] += ledger.discard_entries_from_notes(ledgers_dir, prefix)
        os.remove(path)
        outcome["verdict_files_removed"] += 1
    stale = os.path.join(ledgers_dir, ledger.OLD_REFUSED_FILE)
    if os.path.exists(stale):
        os.remove(stale)
    return outcome


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("rejudge-old",))
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    arguments = parser.parse_args(argv)
    print(json.dumps(rejudge_old(load_config(arguments.config))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
