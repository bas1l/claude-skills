"""The checks every model suggestion must pass before the weekly pass acts on it.

No model call and no writing here: suggestions go in, and decisions come out.

Memory changes pass claim by claim. Each must have a quote found verbatim in the user's own
entries of the cited note's session, and for ``accepted`` or ``relied_on`` it must be the user's
next message after the assistant's statement. A change failing any check is rejected with its
reason. It is not softened into a proposal.

Deletions need a contradiction with such a quote. Past the limit they become proposals, in the
order they arrive. Things the user undid or rejected stay out unless a quote from after that
decision backs them.

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
from config import Config

REJECT_UNKNOWN_NOTE = "unknown_note"
REJECT_INVALID_NAME = "invalid_name"
REJECT_NOT_SINGLE_CLAIM = "not_a_single_claim"
REJECT_SECRET = "secret_pattern"
REJECT_QUOTE = "quote_not_found"
REJECT_NOT_NEXT_REACTION = "not_the_next_reaction"
REJECT_QUOTE_UNRELATED = "quote_does_not_state_the_claim"
REJECT_DELETION = "deletion_without_contradiction"
REJECT_DECLINED = "previously_declined"
REJECT_EXISTS = "already_exists"
REJECT_MISSING = "target_missing"
REJECT_PRESENT = "already_present"
REJECT_OLD_TEXT = "old_text_not_found"
REJECT_FACT_ENDORSED = "fact_has_an_endorsement"
QUOTE_REASONS = frozenset({REJECT_QUOTE, REJECT_NOT_NEXT_REACTION, REJECT_QUOTE_UNRELATED, REJECT_DELETION})

HOLD_RECURRENCE = "below_recurrence_threshold"
HOLD_PROCEDURE = "procedure_not_shown_by_a_note"
HOLD_FAILURE = "failure_below_threshold_or_not_read"
HOLD_RULE = "rule_not_stated_by_the_user"

_MEMORY_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_MEMORY_TYPE_OF_NOTE = {"preference": "feedback", "conflict": "feedback", "one_moment_order": "feedback"}
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


@dataclass
class MemoryGateState:
    """What the gate has decided so far in this pass, across projects."""

    originals: dict[tuple[str, str], Optional[str]] = field(default_factory=dict)
    current: dict[tuple[str, str], Optional[str]] = field(default_factory=dict)
    deletions: int = 0
    accepted: list[GatedChange] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    deletion_proposals: list[GatedChange] = field(default_factory=list)
    fact_proposals: list[tuple[schemas.FactProposal, weekly_notes.NoteRecord, str]] = field(default_factory=list)


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
    return render.redact_counted(text, config.secrets)[1] > 0


def _rejected(subject: str, project_folder: str, reason: str, detail: str, claim: str, quote: str, source: Any) -> dict[str, Any]:
    return {
        "subject": subject, "project_folder": project_folder, "reason": reason, "detail": detail,
        "claim": claim, "quote": quote, "source": source,
    }


def _quote_shares_a_word_with_claim(change: schemas.MemoryChange, letters: int) -> bool:
    """A real quote can sit beside a claim it does not state, such as "keep for now" beside a
    list of names. Saying a thing means using at least one of its longer words. This catches the
    plain mismatch only: it cannot tell that a shared word means the same."""
    claim_words = set(weekly_notes.plain_words(change.claim))
    return any(len(word) >= letters and word in claim_words for word in weekly_notes.plain_words(change.quote))


def _check_evidence(change: schemas.MemoryChange, entries: Sequence[Any], letters: int) -> tuple[Optional[str], Sequence[Any]]:
    """The reason this change's quote fails, and the user's entries that hold it."""
    deleting = change.action in schemas.DELETING_ACTIONS
    holding = quotes.user_entries_holding(change.quote, entries)
    if not holding:
        return (REJECT_DELETION if deleting else REJECT_QUOTE), holding
    if change.endorsement == schemas.ENDORSED_SAID:
        if not _quote_shares_a_word_with_claim(change, letters):
            return REJECT_QUOTE_UNRELATED, holding
        return None, holding
    if deleting and change.endorsement == schemas.ENDORSED_RELIED_ON:
        return REJECT_DELETION, holding
    if not quotes.quote_is_reaction_to(change.quote, change.assistant_statement, entries):
        return REJECT_NOT_NEXT_REACTION, holding
    return None, holding


def _fit_to_file(
    change: schemas.MemoryChange, record: weekly_notes.NoteRecord, current: Optional[str], when: datetime
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
        if action == schemas.ACTION_REPLACE:
            return memory_store.replace_in_memory(current, change.old_text, _text_of_change(change, when)), None
        if action == schemas.ACTION_REMOVE:
            return memory_store.remove_from_memory(current, change.old_text), None
        memory_store.check_old_text(current, change.old_text)
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


def gate_memory_reply(
    reply: schemas.MemoryReply,
    group: weekly_notes.MemoryGroup,
    refs: Mapping[str, weekly_notes.NoteRecord],
    store: weekly_notes.SourceStore,
    read_current: Any,
    decisions: Sequence[Mapping[str, Any]],
    config: Config,
    state: MemoryGateState,
) -> None:
    """Decide each change of one group's reply, adding the outcomes to ``state``."""
    folder = group.project_folder
    scope = ledger.project_scope(folder)
    limit = config.weekly.claim_max_chars

    def reject(change: schemas.MemoryChange, reason: str, detail: str, source: Any) -> None:
        state.rejected.append(_rejected(change.memory, folder, reason, detail, change.claim, change.quote, source))

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
            reject(change, REJECT_SECRET, "a secret pattern matched", source)
            continue
        reason, holding = _check_evidence(change, store.entries(record.window), config.weekly.said_quote_shared_word_letters)
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
        key = (folder, change.memory)
        if key not in state.current:
            state.originals[key] = read_current(folder, change.memory)
            state.current[key] = state.originals[key]
        before = state.current[key]
        when = max(entry.timestamp for entry in holding)
        after, misfit = _fit_to_file(change, record, before, when)
        if misfit is not None:
            reject(change, misfit, "does not fit the memory as it stands", source)
            continue
        gated = GatedChange(change_id(folder, change), folder, change, record, new_evidence, before, after)
        if change.action in schemas.DELETING_ACTIONS:
            if state.deletions >= config.weekly.max_deletions_per_pass:
                state.deletion_proposals.append(gated)
                continue
            state.deletions += 1
        state.current[key] = after
        state.accepted.append(gated)

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
        elif _has_secret(fact.claim, config):
            reject_fact(REJECT_SECRET, "a secret pattern matched")
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
    if failures >= minimum and failures == len(state.accepted) + len(state.deletion_proposals) + failures:
        raise QuoteBatchError(f"all {failures} memory changes failed their quote checks")


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
        return ProposalDecision(REJECT, REJECT_SECRET, "a secret pattern matched")
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
