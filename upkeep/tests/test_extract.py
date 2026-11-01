"""Extraction with a fake model call: resuming, validation, quote annotation, and contracts."""
from __future__ import annotations

import dataclasses
import json

import pytest
from conftest import assistant_text, human, user_with_origin, write_jsonl

import extract
import model_call
import schemas
import sessions
import transcripts as t
from config import config_from_mapping


def note(**overrides):
    values = {
        "type": "preference",
        "what": "Prefers short reports.",
        "evidence": "USER-TYPED",
        "memory_candidate": True,
        "endorsement": "said",
        "endorsement_quote": "keep it short",
        "origin_of_point": "user",
        "route": "memory",
        "confidence": "high",
        "items": [],
    }
    values.update(overrides)
    return values


class FakeCall:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return model_call.ModelResult(
            text=reply,
            usage={"input_tokens": 1},
            model_usage={"m": {}},
            cost_usd=0.25,
            duration_ms=1,
            num_turns=1,
            command_line=("claude",),
        )


@pytest.fixture
def small_chunks(config, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return dataclasses.replace(
        config,
        chunking=dataclasses.replace(config.chunking, chunk_chars=150),
        paths=dataclasses.replace(config.paths, run_dir=str(run_dir)),
    )


def make_item(tmp_path, config):
    records = [human("keep it short", minute=1)]
    records += [assistant_text("a" * 120, minute=minute) for minute in range(2, 5)]
    main = write_jsonl(tmp_path / "F--p" / "sid.jsonl", [{**r, "sessionId": "sid"} for r in records])
    files = sessions.SessionFiles("F--p", "sid", main, ())
    return extract.whole_session_item(files, config)


def empty_reply():
    return json.dumps({"notes": []})


def test_each_chunk_gets_validated_notes_and_the_timeline(tmp_path, small_chunks):
    item = make_item(tmp_path, small_chunks)
    fake = FakeCall([json.dumps({"notes": [note()]})] + [empty_reply()] * 9)
    summary = extract.extract_window(item, str(tmp_path / "out"), small_chunks, "sonnet", "r1", 5.0, call=fake)
    assert summary["chunks_done"] == list(range(1, summary["chunks_total"] + 1))
    assert summary["chunks_total"] > 1
    for call in fake.calls:
        assert call["tools"] == ()
        assert "keep it short" in call["stdin_text"]
    document = json.loads((tmp_path / "out" / "chunk-001.json").read_text(encoding="utf-8"))
    assert document["notes"][0]["quote_check"] == extract.QUOTE_VERIFIED
    assert document["session_id"] == "sid"
    assert document["run_id"] == "r1"
    assert document["schema_version"] == extract.CHUNK_SCHEMA_VERSION


def test_fabricated_quote_is_marked_not_found(tmp_path, small_chunks):
    item = make_item(tmp_path, small_chunks)
    fake = FakeCall([json.dumps({"notes": [note(endorsement_quote="always skip tests")]})] + [empty_reply()] * 9)
    extract.extract_window(item, str(tmp_path / "out"), small_chunks, "sonnet", "r1", 5.0, call=fake)
    document = json.loads((tmp_path / "out" / "chunk-001.json").read_text(encoding="utf-8"))
    assert document["notes"][0]["quote_check"] == extract.QUOTE_NOT_FOUND


def test_interrupted_run_resumes_without_duplicates(tmp_path, small_chunks):
    item = make_item(tmp_path, small_chunks)
    out = str(tmp_path / "out")
    first = FakeCall([json.dumps({"notes": [note()]}), model_call.ModelCallError("interrupted")])
    with pytest.raises(model_call.ModelCallError):
        extract.extract_window(item, out, small_chunks, "sonnet", "r1", 5.0, call=first)
    assert len(first.calls) == 2

    second = FakeCall([empty_reply()] * 9)
    summary = extract.extract_window(item, out, small_chunks, "sonnet", "r2", 5.0, call=second)
    assert len(second.calls) == summary["chunks_total"] - 1
    assert summary["notes"] == 1


def test_invalid_reply_raises_keeps_the_reply_and_writes_no_notes(tmp_path, small_chunks):
    item = make_item(tmp_path, small_chunks)
    fake = FakeCall(['<invoke name="Bash">'])
    with pytest.raises(schemas.SchemaError):
        extract.extract_window(item, str(tmp_path / "out"), small_chunks, "sonnet", "r1", 5.0, call=fake)
    assert (tmp_path / "out" / "chunk-001.rejected").exists()
    assert not (tmp_path / "out" / "chunk-001.json").exists()


def test_rerun_with_different_chunks_refuses_to_resume(tmp_path, small_chunks):
    item = make_item(tmp_path, small_chunks)
    out = str(tmp_path / "out")
    extract.extract_window(item, out, small_chunks, "sonnet", "r1", 5.0, call=FakeCall([empty_reply()] * 9))
    other = dataclasses.replace(small_chunks, chunking=dataclasses.replace(small_chunks.chunking, chunk_chars=200))
    with pytest.raises(ValueError, match="refusing to resume"):
        extract.extract_window(item, out, other, "sonnet", "r2", 5.0, call=FakeCall([empty_reply()] * 9))


def test_budget_passed_to_each_call_shrinks(tmp_path, small_chunks):
    item = make_item(tmp_path, small_chunks)
    fake = FakeCall([empty_reply()] * 9)
    extract.extract_window(item, str(tmp_path / "out"), small_chunks, "sonnet", "r1", 1.0, call=fake)
    budgets = [call["max_budget_usd"] for call in fake.calls]
    assert budgets[:2] == [1.0, 0.75]


def test_only_named_chunks_are_run(tmp_path, small_chunks):
    item = make_item(tmp_path, small_chunks)
    fake = FakeCall([empty_reply()])
    summary = extract.extract_window(item, str(tmp_path / "out"), small_chunks, None, "r1", 5.0, [2], call=fake)
    assert summary["chunks_done"] == [2]
    assert fake.calls[0]["model"] is None


def test_unknown_chunk_number_raises(tmp_path, small_chunks):
    item = make_item(tmp_path, small_chunks)
    with pytest.raises(ValueError, match="no such chunks"):
        extract.extract_window(item, str(tmp_path / "out"), small_chunks, None, "r1", 5.0, [99], call=FakeCall([]))


def test_unknown_origin_stops_extraction_before_any_call(tmp_path, small_chunks):
    records = [human("hello", minute=1), user_with_origin("alien", "boo", minute=2)]
    main = write_jsonl(tmp_path / "F--p" / "sid.jsonl", [{**r, "sessionId": "sid"} for r in records])
    item = extract.whole_session_item(sessions.SessionFiles("F--p", "sid", main, ()), small_chunks)
    fake = FakeCall([])
    with pytest.raises(t.TranscriptFormatError):
        extract.extract_window(item, str(tmp_path / "out"), small_chunks, "sonnet", "r1", 5.0, call=fake)
    assert fake.calls == []


def test_count_only_item_is_refused(tmp_path, small_chunks):
    item = dataclasses.replace(make_item(tmp_path, small_chunks), mode=sessions.MODE_COUNT_ONLY)
    with pytest.raises(ValueError, match="not for model reading"):
        extract.extract_window(item, str(tmp_path / "out"), small_chunks, "sonnet", "r1", 5.0, call=FakeCall([]))


def test_config_defaults_derive_from_home_and_missing_keys_raise(config):
    import os

    home = os.path.expanduser("~")
    assert config.paths.projects_dir.startswith(home)
    assert config.paths.run_dir.startswith(home)
    with pytest.raises(ValueError, match="missing"):
        config_from_mapping({})
