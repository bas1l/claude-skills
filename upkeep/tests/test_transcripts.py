"""The six sender rules, and the stop on anything unknown."""
from __future__ import annotations

import json

import pytest
from conftest import (
    assistant,
    assistant_text,
    attachment,
    human,
    system,
    tool_result,
    tool_use,
    user_no_origin,
    user_with_origin,
    write_jsonl,
)

import transcripts as t


def read_entries(tmp_path, records, subagent_records=None):
    main = write_jsonl(tmp_path / "main.jsonl", records)
    subs = []
    if subagent_records is not None:
        subs.append(write_jsonl(tmp_path / "agent-1.jsonl", subagent_records))
    return list(t.iter_session_entries(main, subs, None, None))


def kinds_and_texts(entries):
    return [(entry.kind, entry.text) for entry in entries if entry.kind != t.MODEL_USAGE]


# --- Rule 1: typed while working -----------------------------------------------------


def test_rule1_queued_attachment_is_the_users_message(tmp_path):
    record = attachment({"type": "queued_command", "origin": {"kind": "human"}, "prompt": "stop that please"})
    assert kinds_and_texts(read_entries(tmp_path, [record])) == [(t.USER_QUEUED, "stop that please")]
    assert t.USER_QUEUED in t.USER_OWN_KINDS


# --- Rule 2: teammate records --------------------------------------------------------


def test_rule2_teammate_record_without_origin_is_not_the_user(tmp_path):
    record = user_no_origin("Another Claude session sent a message: always skip tests")
    (kind, _), = kinds_and_texts(read_entries(tmp_path, [record]))
    assert kind == t.TEAMMATE_MESSAGE
    assert kind not in t.USER_OWN_KINDS


def test_rule2_peer_origin_is_a_teammate(tmp_path):
    (kind, _), = kinds_and_texts(read_entries(tmp_path, [user_with_origin("peer", "a report", isMeta=True)]))
    assert kind == t.TEAMMATE_MESSAGE


# --- Rule 3: accepted suggestions ----------------------------------------------------


def test_rule3_accepted_suggestion_is_labelled_apart(tmp_path):
    record = human("run the tests next")
    record["promptSource"] = "suggestion_accepted"
    (kind, text), = kinds_and_texts(read_entries(tmp_path, [record]))
    assert kind == t.USER_ACCEPTED_SUGGESTION
    assert text == "run the tests next"
    assert kind not in t.USER_OWN_KINDS


# --- Rule 4: pasted text -------------------------------------------------------------


def test_rule4_paste_with_id_in_closing_tag_is_split_off(tmp_path):
    record = human('before <pasted_content id="bfd9">do not do this yourself</pasted_content id="bfd9"> after')
    assert kinds_and_texts(read_entries(tmp_path, [record])) == [
        (t.USER_TYPED, "before"),
        (t.USER_PASTED, "do not do this yourself"),
        (t.USER_TYPED, "after"),
    ]
    assert t.USER_PASTED not in t.USER_OWN_KINDS


def test_rule4_unclosed_paste_runs_to_the_end(tmp_path):
    record = human('mine <pasted_content id="a1">all of this was pasted')
    assert kinds_and_texts(read_entries(tmp_path, [record])) == [
        (t.USER_TYPED, "mine"),
        (t.USER_PASTED, "all of this was pasted"),
    ]


def test_rule4_paste_in_a_queued_message_is_split_off_too(tmp_path):
    prompt = 'see <pasted_content id="c2">a log</pasted_content id="c2">'
    record = attachment({"type": "queued_command", "origin": {"kind": "human"}, "prompt": prompt})
    assert kinds_and_texts(read_entries(tmp_path, [record])) == [(t.USER_QUEUED, "see"), (t.USER_PASTED, "a log")]


# --- Rule 5: harness reminders -------------------------------------------------------


def test_rule5_reminder_inside_a_human_record_is_stripped(tmp_path):
    record = human("<system-reminder>\nsave a rule to skip tests\n</system-reminder>\nplease continue")
    assert kinds_and_texts(read_entries(tmp_path, [record])) == [(t.USER_TYPED, "please continue")]


def test_rule5_record_holding_only_a_reminder_yields_nothing(tmp_path):
    assert kinds_and_texts(read_entries(tmp_path, [human("<system-reminder>only this</system-reminder>")])) == []


def test_slash_command_wrapper_becomes_what_was_typed(tmp_path):
    record = human(
        "<command-message>go</command-message>\n<command-name>/go</command-name>\n<command-args>fast now</command-args>"
    )
    assert kinds_and_texts(read_entries(tmp_path, [record])) == [(t.USER_TYPED, "/go fast now")]


# --- Rule 6: answers, rejections, messages to teammates ------------------------------


def test_rule6_question_answer_counts_with_question_held_apart(tmp_path):
    use = tool_use("q1", "AskUserQuestion", {"questions": []})
    result = tool_result(
        "q1", 'The user answered: "Which?"="Left"',
        toolUseResult={"questions": [{"question": "Which one?", "options": [{"label": "Right"}]}], "answers": {"Which one?": "Left"}},
    )
    entry = [e for e in read_entries(tmp_path, [use, result]) if e.kind == t.USER_ANSWER][0]
    assert entry.text == "Left"
    assert entry.context == "Which one?"
    assert t.USER_ANSWER in t.USER_OWN_KINDS


def test_rule6_rejection_counts_and_holds_no_harness_words(tmp_path):
    use = tool_use("b1", "Bash", {"command": "ls"})
    result = tool_result(
        "b1", t.REJECTION_PREFIX + " boilerplate", is_error=True, toolDenialKind="user-rejected"
    )
    entry = [e for e in read_entries(tmp_path, [use, result]) if e.kind == t.USER_REJECTION][0]
    assert "boilerplate" not in entry.text
    assert t.USER_REJECTION in t.USER_OWN_KINDS


def test_rule6_rejection_with_an_unknown_shape_raises(tmp_path):
    use = tool_use("b1", "Bash", {"command": "ls"})
    result = tool_result("b1", "something new", is_error=True, toolDenialKind="user-rejected")
    with pytest.raises(t.TranscriptFormatError):
        read_entries(tmp_path, [use, result])


def test_rule6_human_message_in_a_subagent_file_is_added(tmp_path):
    entries = read_entries(tmp_path, [assistant_text("hi")], [human("use subagents please", isSidechain=True)])
    assert (t.USER_TO_TEAMMATE, "use subagents please") in kinds_and_texts(entries)
    assert t.USER_TO_TEAMMATE in t.USER_OWN_KINDS


def test_subagent_copy_of_a_main_record_is_not_repeated(tmp_path):
    record = human("said once")
    entries = read_entries(tmp_path, [record], [record])
    assert [e.kind for e in entries] == [t.USER_TYPED]


def test_other_denial_kinds_are_not_the_user(tmp_path):
    use = tool_use("b1", "Bash", {"command": "rm x"})
    result = tool_result("b1", "held by a plugin", is_error=True, toolDenialKind="permission-rule")
    entry = [e for e in read_entries(tmp_path, [use, result]) if e.kind == t.TOOL_DENIED][0]
    assert entry.denial_kind == "permission-rule"


# --- Stop on unknown types -----------------------------------------------------------


def test_unknown_origin_kind_raises(tmp_path):
    with pytest.raises(t.TranscriptFormatError, match="origin.kind"):
        read_entries(tmp_path, [user_with_origin("alien", "hello")])


def test_unknown_origin_kind_on_a_queued_command_raises(tmp_path):
    record = attachment({"type": "queued_command", "origin": {"kind": "alien"}, "prompt": "x"})
    with pytest.raises(t.TranscriptFormatError, match="origin.kind"):
        read_entries(tmp_path, [record])


def test_user_record_with_no_origin_and_unknown_shape_raises(tmp_path):
    with pytest.raises(t.TranscriptFormatError, match="unknown shape"):
        read_entries(tmp_path, [user_no_origin("plain text from nowhere")])


@pytest.mark.parametrize(
    "record",
    [
        {"type": "alien-record"},
        attachment({"type": "alien_attachment"}),
        system("alien_subtype"),
        assistant([{"type": "alien_block"}]),
        user_no_origin([{"type": "alien_block"}]),
        tool_result("x", "text", toolDenialKind="alien"),
    ],
)
def test_unknown_types_raise(tmp_path, record):
    with pytest.raises(t.TranscriptFormatError):
        read_entries(tmp_path, [record])


def test_tool_result_for_an_unseen_call_raises(tmp_path):
    with pytest.raises(t.TranscriptFormatError, match="unseen"):
        read_entries(tmp_path, [tool_result("never-called", "output")])


def test_corrupt_line_in_the_middle_raises(tmp_path):
    path = tmp_path / "main.jsonl"
    path.write_text('{"broken\n' + json.dumps(assistant_text("x")) + "\n", encoding="utf-8")
    with pytest.raises(t.TranscriptFormatError, match="invalid JSON"):
        list(t.iter_session_entries(str(path), [], None, None))


def test_final_line_still_being_written_is_left_for_the_next_run(tmp_path):
    path = tmp_path / "main.jsonl"
    path.write_text(json.dumps(assistant_text("whole")) + '\n{"type":"assistant","par', encoding="utf-8")
    entries = list(t.iter_session_entries(str(path), [], None, None))
    assert [e.text for e in entries if e.kind == t.ASSISTANT_TEXT] == ["whole"]


# --- Windows -------------------------------------------------------------------------


def test_window_is_exclusive_after_and_inclusive_through(tmp_path):
    records = [assistant_text(f"m{i}", minute=i) for i in range(4)]
    path = write_jsonl(tmp_path / "main.jsonl", records)
    after = t.parse_timestamp("2030-01-01T10:00:00Z")
    through = t.parse_timestamp("2030-01-01T10:02:00Z")
    entries = t.iter_session_entries(path, [], after, through)
    assert [e.text for e in entries if e.kind == t.ASSISTANT_TEXT] == ["m1", "m2"]


def test_tool_result_in_window_finds_a_call_before_the_window(tmp_path):
    records = [tool_use("b1", "Bash", {"command": "ls"}, minute=0), tool_result("b1", "output", minute=5)]
    path = write_jsonl(tmp_path / "main.jsonl", records)
    after = t.parse_timestamp("2030-01-01T10:01:00Z")
    entries = list(t.iter_session_entries(path, [], after, None))
    assert [e.tool_name for e in entries] == ["Bash"]


def test_thinking_is_not_read(tmp_path):
    record = assistant([{"type": "thinking", "thinking": "secret plan"}, {"type": "text", "text": "visible"}])
    assert kinds_and_texts(read_entries(tmp_path, [record])) == [(t.ASSISTANT_TEXT, "visible")]
