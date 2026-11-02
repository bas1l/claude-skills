"""Daylight saving scenarios. Not collected by name: test_edge_cases.py runs this file in a child
process with TZ=EST5EDT, because the time zone can only be set at process start on Windows.

That zone changes at 2030-03-10 07:00 UTC, from 01:59 straight to 03:00 local, and at 2030-11-03
06:00 UTC, when 01:00 to 01:59 local happens twice. The zone's rules are the C library's, and the
date of the change differs from Europe's. What is shown does not depend on which zone it is: a local
hour that happens twice, or not at all, loses or repeats no record.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from conftest import assistant_text, human
from test_weekly import PROJECT, SESSION_ID, add_session  # noqa: F401
from test_weekly import tree  # noqa: F401 (a fixture)
from test_edge_cases import Notes, append, session_file, state_of

import daily
import monthly
import weekly


def at(record, moment):
    return {**record, "timestamp": moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")}


def utc(month, day, hour, minute):
    return datetime(2030, month, day, hour, minute, tzinfo=timezone.utc)


def test_the_zone_is_in_force():
    assert utc(11, 3, 5, 30).astimezone().utcoffset() != utc(11, 3, 6, 30).astimezone().utcoffset()
    assert utc(11, 3, 5, 30).astimezone().strftime("%H:%M") == utc(11, 3, 6, 30).astimezone().strftime("%H:%M") == "01:30"
    assert utc(3, 10, 6, 30).astimezone().strftime("%H:%M") == "01:30"
    assert utc(3, 10, 7, 30).astimezone().strftime("%H:%M") == "03:30"


def windows_on_disk(config):
    return sorted(path.relative_to(Path(config.paths.data_dir) / "notes").parent.as_posix() for path in (Path(config.paths.data_dir) / "notes").rglob("window.json"))


def test_a_local_hour_that_happens_twice_loses_and_repeats_nothing(tree):  # noqa: F811
    moments = [utc(11, 3, 5, 10), utc(11, 3, 5, 50), utc(11, 3, 6, 10), utc(11, 3, 6, 50)]
    add_session(tree, SESSION_ID, [at(human("said at one ten, first time", 0), moments[0]), at(assistant_text("Fine.", 0), moments[1])])
    path = session_file(tree)

    first = Notes()
    assert daily.run_daily(tree, "first", call=first)["status"] == daily.STATUS_OK
    assert state_of(tree)["processed_through"] == moments[1].isoformat()

    # Next night's records carry the same local clock times as those already read.
    append(path, at(human("said at one ten, second time", 0), moments[2]))
    append(path, at(assistant_text("Noted.", 0), moments[3]))
    second = Notes()
    assert daily.run_daily(tree, "second", call=second)["status"] == daily.STATUS_OK
    assert state_of(tree)["processed_through"] == moments[3].isoformat()
    assert "first time" in first.calls[0]["stdin_text"] and "second time" not in first.calls[0]["stdin_text"]
    assert "second time" in second.calls[0]["stdin_text"] and "first time" not in second.calls[0]["stdin_text"]

    # Two windows, both dated by the local day, under different names.
    found = windows_on_disk(tree)
    assert len(found) == 2 and len(set(found)) == 2
    assert all(name.startswith("2030-11-03/") for name in found)

    third = Notes()
    assert daily.run_daily(tree, "third", call=third)["sessions_selected"] == 0


def test_a_local_hour_that_never_happens_loses_nothing(tree):  # noqa: F811
    moments = [utc(3, 10, 6, 50), utc(3, 10, 7, 10)]
    assert moments[0].astimezone().strftime("%H:%M") == "01:50" and moments[1].astimezone().strftime("%H:%M") == "03:10"
    add_session(tree, SESSION_ID, [at(human("just before the change", 0), moments[0]), at(human("just after the change", 0), moments[1])])
    reader = Notes()
    assert daily.run_daily(tree, "first", call=reader)["status"] == daily.STATUS_OK
    assert "just before the change" in reader.calls[0]["stdin_text"] and "just after the change" in reader.calls[0]["stdin_text"]
    assert state_of(tree)["processed_through"] == moments[1].isoformat()
    assert windows_on_disk(tree)[0].startswith("2030-03-10/")


def test_the_week_and_month_and_daily_check_go_by_the_local_date(tree):  # noqa: F811
    # Late on Saturday 2 November local, after midnight UTC: the local date counts.
    late = utc(11, 3, 3, 30)
    assert late.astimezone().strftime("%Y-%m-%d") == "2030-11-02"
    # Tuesday evening local is already Wednesday in UTC.
    assert weekly.iso_week_of(utc(10, 28, 3, 0).astimezone()) == "2030-W43"
    assert monthly.month_of(utc(11, 1, 3, 0)) == "2030-10"

    logs = Path(tree.paths.data_dir) / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "daily-20301103-013000.result.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    assert weekly.daily_completed_on(tree, utc(11, 3, 6, 30).astimezone())
    assert not weekly.daily_completed_on(tree, utc(11, 4, 6, 30).astimezone())
