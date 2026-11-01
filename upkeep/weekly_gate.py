"""The checks every model suggestion must pass before the weekly pass acts on it.

No model call and no writing here: suggestions go in, and decisions come out.

Memory changes pass claim by claim, in two steps. First, what a script can check: each must have a
quote found verbatim, on word edges, in the user's entries of the cited note's session, long enough
to mean something, and sharing words with the claim. For ``accepted`` or ``relied_on`` the quote must
be the user's next message after an assistant statement that itself shares words with the claim. A
quote the reading of the session marked as a one-moment order backs nothing.

A script cannot judge meaning, so what is left goes to one tool-less model call for the whole pass,
given only each claim and its quotes. Only a claim it clearly supports goes on: ``gate_memory_reply``
screens, ``verification_input`` writes the call's input, and ``apply_verdicts`` decides. File text is
worked out only after that, so that a rejected claim cannot reach the changes after it.

A change failing any check is rejected with its reason. It is not softened into a proposal.

The exception is its siblings. One user statement can be split into claims, and judged one by one the
stricter half can pass while its qualifier fails, which would save something the user did not say. So
when a change is rejected, by a script check or the verdict, each other change quoting the same user
entry becomes a proposal, with the reason. An entry is the nearest thing to a statement a script can
tell, so a long message holding unrelated points ties them too, which costs a reading and no more. A
quote found in no entry ties to nothing. A claim that merely does not fit the file as it stands, such
as one already there, says nothing about what was said, and does not count.

Removing a statement needs a contradiction with such a quote, and past the limit becomes a proposal,
in the order they arrive. Deleting a whole file is always a proposal. Things the user undid or
rejected stay out unless a quote from after that decision backs them.

Proposals pass on one of the routes, and a proposal that misses its threshold is held.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

import ledger
import memory_store
import quotes
import render
import schemas
import weekly_notes
from config import Config, WeeklyConfig

REJECT_UNKNOWN_NOTE = "unknown_note"
REJECT_INVALID_NAME = "invalid_name"
REJECT_NOT_SINGLE_CLAIM = "not_a_single_claim"
REJECT_PATTERN_MATCH = "secret_pattern"
REJECT_QUOTE = "quote_not_found"
REJECT_NOT_NEXT_REACTION = "not_the_next_reaction"
REJECT_QUOTE_UNRELATED = "quote_does_not_state_the_claim"
REJECT_QUOTE_TOO_SHORT = "quote_too_short"
REJECT_NOT_SUPPORTED = "quote_does_not_support_the_claim"
REJECT_ONE_MOMENT = "one_moment_order"
REJECT_DELETION = "deletion_without_contradiction"
REJECT_DECLINED = "previously_declined"
REJECT_EXISTS = "already_exists"
REJECT_MISSING = "target_missing"
REJECT_PRESENT = "already_present"
REJECT_OLD_TEXT = "old_text_not_found"
REJECT_FACT_ENDORSED = "fact_has_an_endorsement"
QUOTE_REASONS = frozenset({REJECT_QUOTE, REJECT_NOT_NEXT_REACTION, REJECT_QUOTE_UNRELATED, REJECT_QUOTE_TOO_SHORT, REJECT_DELETION})

HOLD_RECURRENCE = "below_recurrence_threshold"
HOLD_PROCEDURE = "procedure_not_shown_by_a_note"
HOLD_FAILURE = "failure_below_threshold_or_not_read"
HOLD_RULE = "rule_not_stated_by_the_user"

_REDACTED_RE = re.compile(r"\[REDACTED-[^\]]*\]")
_MEMORY_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_MEMORY_TYPE_OF_NOTE = {"preference": "feedback", "conflict": "feedback"}
_VERB_OF = {"said": "said", "accepted": "accepted", "relied_on": "relied on"}
ACTION_FACT = "fact"
KIND_MEMORY = "memory"


class QuoteBatchError(ValueError):
    """Every memory change in the pass failed its quote check, so something is wrong as a whole."""


@dataclass(frozen=True)
class GatedChange:
    id: str
    project_folder: str
    change: schemas.MemoryChange
    record: weekly_notes.NoteRecord
    new_evidence: bool
    before: Optional[str]
    after: Optional[str]


@dataclass(frozen=True)
class ScreenedChange:
    """A change that passed what a script can check, waiting for the model's verdict."""

    change: schemas.MemoryChange
    record: weekly_notes.NoteRecord
    project_folder: str
    new_evidence: bool
    when: datetime
    statement: frozenset[tuple[str, ...]] = frozenset()


@dataclass
class MemoryGateState:
    """What the gate has decided so far in this pass, across projects."""

    one_moment_quotes: Mapping[str, Sequence[str]] = field(default_factory=dict)
    screened: list[ScreenedChange] = field(default_factory=list)
    originals: dict[tuple[str, str], Optional[str]] = field(default_factory=dict)
    current: dict[tuple[str, str], Optional[str]] = field(default_factory=dict)
    deletions: int = 0
    accepted: list[GatedChange] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    deletion_proposals: list[GatedChange] = field(default_factory=list)
    fact_proposals: list[tuple[schemas.FactProposal, weekly_notes.NoteRecord, str]] = field(default_factory=list)
    rejected_statements: dict[tuple[str, ...], str] = field(default_factory=dict)
    split_proposals: list[tuple[ScreenedChange, str]] = field(default_factory=list)


def change_id(project_folder: str, change: schemas.MemoryChange) -> str:
    identity = "\n".join((project_folder, change.memory, change.action, change.old_text, change.claim))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


def _text_of_change(change: schemas.MemoryChange, when: datetime) -> str:
    quoted = " ".join(change.quote.split())
    return f'{change.claim} (user {_VERB_OF[change.endorsement]} on {when.strftime("%Y-%m-%d")}: "{quoted}")'


def _new_memory_text(change: schemas.MemoryChange, record: weekly_notes.NoteRecord, when: datetime) -> str:
    memory_type = _MEMORY_TYPE_OF_NOTE.get(record.values["type"], "project")
    return (
        "---\n"
        f"name: {change.memory}\n"
        f"description: {json.dumps(change.claim, ensure_ascii=False)}\n"
        "metadata:\n"
        "  node_type: memory\n"
        f"  type: {memory_type}\n"
        f"  originSessionId: {record.window.session_id}\n"
        "---\n\n"
        f"{_text_of_change(change, when)}\n"
    )


def _has_secret(text: str, config: Config) -> bool:
    # A stored reply is already redacted, so a claim that held a secret arrives holding the mark.
    return memory_store.REDACTED_MARK in text or render.redact_counted(text, config.secrets)[1] > 0


def _rejected(subject: str, project_folder: str, reason: str, detail: str, claim: str, quote: str, source: Any) -> dict[str, Any]:
    return {
        "subject": subject, "project_folder": project_folder, "reason": reason, "detail": detail,
        "claim": claim, "quote": quote, "source": source,
    }


def _content_words(text: str, weekly: WeeklyConfig) -> set[str]:
    return {
        word for word in weekly_notes.plain_words(text)
        if len(word) >= weekly.tied_word_min_letters and word not in weekly.tied_ignored_words
    }


def _tied_to_claim(claim: str, words: str, weekly: WeeklyConfig) -> bool:
    """A real quote can sit beside a claim it does not state, such as "leave it be" beside a list
    of names. Stating a thing means using some of its words. This catches the plain mismatch only:
    what the shared words mean is the verification call's question."""
    return len(_content_words(claim, weekly) & _content_words(words, weekly)) >= weekly.tied_shared_words_min


def _word_count(text: str) -> int:
    return len(weekly_notes.plain_words(text))


def _check_evidence(change: schemas.MemoryChange, entries: Sequence[Any], weekly: WeeklyConfig) -> tuple[Optional[str], Sequence[Any]]:
    """The reason this change's quote fails, and the user's entries that hold it."""
    deleting = change.action in schemas.DELETING_ACTIONS
    said = change.endorsement == schemas.ENDORSED_SAID
    holding = quotes.user_entries_holding(change.quote, entries, accepted=not said)
    if not holding:
        return (REJECT_DELETION if deleting else REJECT_QUOTE), holding
    if said:
        if _word_count(change.quote) < weekly.said_quote_min_words:
            return REJECT_QUOTE_TOO_SHORT, holding
        if not _tied_to_claim(change.claim, change.quote, weekly):
            return REJECT_QUOTE_UNRELATED, holding
        return None, holding
    if deleting and change.endorsement == schemas.ENDORSED_RELIED_ON:
        return REJECT_DELETION, holding
    if _word_count(change.quote) < weekly.reaction_quote_min_words or _word_count(change.assistant_statement) < weekly.assistant_statement_min_words:
        return REJECT_QUOTE_TOO_SHORT, holding
    if not _tied_to_claim(change.claim, change.assistant_statement, weekly):
        return REJECT_QUOTE_UNRELATED, holding
    if not quotes.quote_is_reaction_to(change.quote, change.assistant_statement, entries):
        return REJECT_NOT_NEXT_REACTION, holding
    return None, holding


def _is_one_moment_quote(quote: str, orders: Sequence[str]) -> bool:
    wanted = " ".join(quote.split()).lower()
    return any(wanted in held or held in wanted for held in (" ".join(order.split()).lower() for order in orders))


def _real_old_text(current: str, old_text: str, config: Config) -> str:
    """The file's own words for ``old_text``. The model reads a memory redacted, so what it quotes
    can hold the mark, and this finds the one place in the file that redacts to those words."""
    if memory_store.REDACTED_MARK not in old_text:
        return old_text
    pattern = ".+?".join(re.escape(part) for part in _REDACTED_RE.split(old_text))
    found = {match.group(0) for match in re.finditer(pattern, current, re.S) if render.redact_secrets(match.group(0), config.secrets) == old_text}
    if len(found) != 1:
        raise memory_store.MemoryEditError(f"redacted old_text matches {len(found)} places in the file, must be exactly one")
    return found.pop()


def _fit_to_file(
    change: schemas.MemoryChange, record: weekly_notes.NoteRecord, current: Optional[str], when: datetime, config: Config
) -> tuple[Optional[str], Optional[str]]:
    """The file's text after this change, and the reason it does not fit if so."""
    action = change.action
    if action == schemas.ACTION_CREATE:
        if current is not None:
            return None, REJECT_EXISTS
        return _new_memory_text(change, record, when), None
    if current is None:
        return None, REJECT_MISSING
    try:
        if action == schemas.ACTION_ADD:
            if change.claim in current:
                return None, REJECT_PRESENT
            return memory_store.add_to_memory(current, _text_of_change(change, when)), None
        old_text = _real_old_text(current, change.old_text, config)
        if action == schemas.ACTION_REPLACE:
            return memory_store.replace_in_memory(current, old_text, _text_of_change(change, when)), None
        if action == schemas.ACTION_REMOVE:
            return memory_store.remove_from_memory(current, old_text), None
        memory_store.check_old_text(current, old_text)
        return None, None
    except memory_store.MemoryEditError:
        return None, REJECT_OLD_TEXT


def _declined_without_new_evidence(
    decision: Optional[Mapping[str, Any]], holding: Sequence[Any]
) -> tuple[bool, bool]:
    """(refuse this, it is backed by new evidence)."""
    if decision is None:
        return False, False
    decided_at = datetime.fromisoformat(decision["decided_at"])
    if any(entry.timestamp > decided_at for entry in holding):
        return False, True
    return True, False


def _statement_of(change: schemas.MemoryChange, record: weekly_notes.NoteRecord, entries: Sequence[Any]) -> frozenset[tuple[str, ...]]:
    """What ties a change to its source statement: each user entry holding its quote."""
    holding = {id(entry) for entry in quotes.user_entries_holding(change.quote, entries, accepted=True)}
    return frozenset(("entry", record.window.key, str(position)) for position, entry in enumerate(entries) if id(entry) in holding)


def _note_rejected_statement(state: MemoryGateState, statement: frozenset[tuple[str, ...]], claim: str, reason: str) -> None:
    for part in statement:
        state.rejected_statements.setdefault(part, f"{claim} ({reason})")


def gate_memory_reply(
    reply: schemas.MemoryReply,
    group: weekly_notes.MemoryGroup,
    refs: Mapping[str, weekly_notes.NoteRecord],
    store: weekly_notes.SourceStore,
    decisions: Sequence[Mapping[str, Any]],
    config: Config,
    state: MemoryGateState,
) -> None:
    """Screen each change of one group's reply, adding the outcomes to ``state``."""
    folder = group.project_folder
    scope = ledger.project_scope(folder)
    limit = config.weekly.claim_max_chars

    def reject(change: schemas.MemoryChange, reason: str, detail: str, source: Any) -> None:
        state.rejected.append(_rejected(change.memory, folder, reason, detail, change.claim, change.quote, source))
        if record is not None:
            _note_rejected_statement(state, _statement_of(change, record, store.entries(record.window)), change.claim, reason)

    for change in reply.changes:
        record = refs.get(change.note)
        if record is None:
            reject(change, REJECT_UNKNOWN_NOTE, f"note {change.note} is not among this group's notes", None)
            continue
        source = record.source_json()
        if not _MEMORY_NAME_RE.fullmatch(change.memory) or change.memory.upper() == "MEMORY":
            reject(change, REJECT_INVALID_NAME, "the name is not a plain memory name", source)
            continue
        if "\n" in change.claim or len(change.claim) > limit:
            reject(change, REJECT_NOT_SINGLE_CLAIM, f"a claim is one line of at most {limit} characters", source)
            continue
        if _has_secret(f"{change.claim}\n{change.quote}", config):
            reject(change, REJECT_PATTERN_MATCH, "a secret pattern matched", source)
            continue
        orders = state.one_moment_quotes.get(record.window.key, ())
        if record.values["type"] == weekly_notes.ONE_MOMENT_ORDER or _is_one_moment_quote(change.quote, orders):
            reject(change, REJECT_ONE_MOMENT, "the reading of this session marked these words as an order tied to the task at hand", source)
            continue
        reason, holding = _check_evidence(change, store.entries(record.window), config.weekly)
        if reason is not None:
            reject(change, reason, "checked against the user's own entries of the cited session", source)
            continue
        decision = weekly_notes.latest_decision_for(
            decisions, scope, KIND_MEMORY, change.memory, change.action, change.claim, config.weekly.reproposal_word_overlap
        )
        refuse, new_evidence = _declined_without_new_evidence(decision, holding)
        if refuse:
            reject(change, REJECT_DECLINED, f"{decision['decision']} on {decision['decided_at']}, with nothing new since", source)
            continue
        statement = _statement_of(change, record, store.entries(record.window))
        state.screened.append(ScreenedChange(change, record, folder, new_evidence, max(entry.timestamp for entry in holding), statement))

    for fact in reply.fact_proposals:
        record = refs.get(fact.note)
        source = None if record is None else record.source_json()
        def reject_fact(reason: str, detail: str) -> None:
            state.rejected.append(_rejected(fact.memory, folder, reason, detail, fact.claim, "", source))
        if record is None:
            reject_fact(REJECT_UNKNOWN_NOTE, f"note {fact.note} is not among this group's notes")
        elif not _MEMORY_NAME_RE.fullmatch(fact.memory):
            reject_fact(REJECT_INVALID_NAME, "the name is not a plain memory name")
        elif "\n" in fact.claim or len(fact.claim) > limit:
            reject_fact(REJECT_NOT_SINGLE_CLAIM, f"a claim is one line of at most {limit} characters")
        elif record.values["type"] == weekly_notes.ONE_MOMENT_ORDER:
            reject_fact(REJECT_ONE_MOMENT, "the reading of this session marked this as an order tied to the task at hand")
        elif _has_secret(fact.claim, config):
            reject_fact(REJECT_PATTERN_MATCH, "a secret pattern matched")
        elif record.values["endorsement"] in schemas.ENDORSEMENTS_WITH_QUOTE:
            reject_fact(REJECT_FACT_ENDORSED, "the note holds an endorsement, so a quoted change is the route")
        elif weekly_notes.latest_decision_for(
            decisions, scope, KIND_MEMORY, fact.memory, ACTION_FACT, fact.claim, config.weekly.reproposal_word_overlap
        ) is not None:
            reject_fact(REJECT_DECLINED, "the user rejected this before, and a fact the user never reacted to is nothing new")
        else:
            state.fact_proposals.append((fact, record, folder))


def check_quote_batch(state: MemoryGateState, minimum: int) -> None:
    """A single failed quote is that change's problem. All of them failing is the pass's."""
    failures = sum(1 for item in state.rejected if item["reason"] in QUOTE_REASONS)
    if failures >= minimum and not state.screened:
        raise QuoteBatchError(f"all {failures} memory changes failed their quote checks")


def verification_input(state: MemoryGateState) -> str:
    """What the verification call reads: one line per claim, holding only the claim and its quotes."""
    return "\n".join(
        json.dumps({
            "id": f"c{position}",
            "claim": item.change.claim,
            "endorsement": item.change.endorsement,
            "user_quote": item.change.quote,
            "assistant_statement": item.change.assistant_statement,
        }, ensure_ascii=False)
        for position, item in enumerate(state.screened, 1)
    )


def apply_verdicts(state: MemoryGateState, verdicts: Sequence[schemas.ClaimVerdict], read_current: Any, config: Config) -> None:
    """Take the model's verdict on each screened change, then fit what is left to the files."""
    by_id = {verdict.id: verdict for verdict in verdicts}
    wanted = {f"c{position}" for position in range(1, len(state.screened) + 1)}
    if len(verdicts) != len(by_id) or set(by_id) != wanted:
        raise schemas.SchemaError(f"the verification reply must answer each claim once: expected {len(wanted)}, got ids {sorted(by_id)}")
    standing = []
    for position, item in enumerate(state.screened, 1):
        verdict = by_id[f"c{position}"]
        if verdict.verdict == schemas.VERDICT_SUPPORTS:
            standing.append(item)
            continue
        reason = REJECT_ONE_MOMENT if verdict.verdict == schemas.VERDICT_ONE_MOMENT else REJECT_NOT_SUPPORTED
        state.rejected.append(_rejected(item.change.memory, item.project_folder, reason, verdict.reason, item.change.claim, item.change.quote, item.record.source_json()))
        _note_rejected_statement(state, item.statement, item.change.claim, reason)
    for item in standing:
        change, record, folder = item.change, item.record, item.project_folder
        source = record.source_json()

        def reject(reason: str, detail: str) -> None:
            state.rejected.append(_rejected(change.memory, folder, reason, detail, change.claim, change.quote, source))

        sibling = next((state.rejected_statements[part] for part in sorted(item.statement) if part in state.rejected_statements), None)
        if sibling is not None:
            state.split_proposals.append((item, sibling))
            continue
        key = (folder, change.memory)
        if key not in state.current:
            state.originals[key] = read_current(folder, change.memory)
            state.current[key] = state.originals[key]
        before = state.current[key]
        after, misfit = _fit_to_file(change, record, before, item.when, config)
        if misfit is not None:
            reject(misfit, "does not fit the memory as it stands")
            continue
        gated = GatedChange(change_id(folder, change), folder, change, record, item.new_evidence, before, after)
        if change.action == schemas.ACTION_DELETE:
            state.deletion_proposals.append(gated)
            continue
        if change.action in schemas.DELETING_ACTIONS:
            if state.deletions >= config.weekly.max_deletions_per_pass:
                state.deletion_proposals.append(gated)
                continue
            state.deletions += 1
        state.current[key] = after
        state.accepted.append(gated)


@dataclass(frozen=True)
class ProposalDecision:
    outcome: str
    reason: str
    detail: str
    new_evidence: bool = False


ACCEPT = "accept"
HOLD = "hold"
REJECT = "reject"


def gate_proposal(
    proposal: schemas.Proposal,
    refs: Mapping[str, weekly_notes.NoteRecord],
    failures: Mapping[str, weekly_notes.FailureCount],
    procedures: Mapping[str, weekly_notes.ProcedureCount],
    decisions: Sequence[Mapping[str, Any]],
    config: Config,
) -> ProposalDecision:
    """Whether a proposal goes ahead, is held for a later week, or is refused."""
    unknown = [ref for ref in proposal.notes if ref not in refs]
    if unknown:
        return ProposalDecision(REJECT, REJECT_UNKNOWN_NOTE, f"unknown notes: {unknown}")
    cited = [refs[ref] for ref in proposal.notes]
    if _has_secret("\n".join((proposal.what, proposal.why, proposal.exact_change, proposal.draft)), config):
        return ProposalDecision(REJECT, REJECT_PATTERN_MATCH, "a secret pattern matched")
    decision = weekly_notes.latest_decision_for(
        decisions, ledger.SCOPE_GLOBAL, proposal.kind, proposal.target or proposal.title, proposal.change_type,
        f"{proposal.title} {proposal.what}", config.weekly.reproposal_word_overlap,
    )
    new_evidence = False
    if decision is not None:
        decided_at = datetime.fromisoformat(decision["decided_at"])
        new_evidence = any(
            record.values["quote_check"] == schemas.QUOTE_VERIFIED and record.last > decided_at for record in cited
        )
        if not new_evidence:
            return ProposalDecision(REJECT, REJECT_DECLINED, f"{decision['decision']} on {decision['decided_at']}, with nothing new since")
    sessions_cited = {record.window.session_id for record in cited}
    weekly = config.weekly
    if proposal.basis == schemas.BASIS_RECURRENCE:
        if len(sessions_cited) < weekly.recurrence_sessions:
            return ProposalDecision(HOLD, HOLD_RECURRENCE, f"{len(sessions_cited)} of {weekly.recurrence_sessions} sessions")
    elif proposal.basis == schemas.BASIS_COSTLY_ONCE:
        procedure = procedures.get(proposal.procedure)
        if procedure is None or procedure.session_id not in sessions_cited:
            return ProposalDecision(HOLD, HOLD_PROCEDURE, f"procedure {proposal.procedure!r} has no note from its session")
    elif proposal.basis == schemas.BASIS_FAILURE_COST:
        failure = failures.get(proposal.failure)
        if failure is None or failure.commands_lost < weekly.failure_min_commands_lost or not sessions_cited & set(failure.sessions):
            return ProposalDecision(HOLD, HOLD_FAILURE, f"failure {proposal.failure!r} needs {weekly.failure_min_commands_lost} commands lost and a note from one of its sessions")
    else:
        stated = any(
            record.values["endorsement"] == schemas.ENDORSED_SAID and record.values["quote_check"] == schemas.QUOTE_VERIFIED
            for record in cited
        )
        if proposal.kind != "global_rule" or not stated:
            return ProposalDecision(HOLD, HOLD_RULE, "this ground needs a global rule and a verified quote of the user saying it")
    return ProposalDecision(ACCEPT, "", "", new_evidence)
