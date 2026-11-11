"""A one-off check that web research works where the scheduled passes run.

Runs one real research call, through the same code and flags as the weekly pass, on a fixed generic
description. It passes only if a search returned something, a page was fetched, the reply met its
rules and ``git`` can be found. Run it through ``Invoke-Upkeep.ps1 -Pass research_check``, which
adds the failure marker. ``Register-UpkeepTasks.ps1 -CheckResearch`` does that under S4U.

Result file, read by Invoke-Upkeep.ps1:
    pass, run_id, status ok|failed, stop_reason, searches, fetches, cost_usd, wall_seconds, and the
    keys that script reads from any pass: failed_sessions, backlog_sessions, secrets_redacted,
    windows_reset, memory_snapshot.errors
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Optional, Sequence

import model_call
import pass_support
import research
from config import Config, LocalSettings, load_config, load_local_settings

PASS_NAME = "research_check"
STATUS_OK = "ok"
STATUS_FAILED = "failed"
EXIT_CODES = {STATUS_OK: 0, STATUS_FAILED: 1}
DESCRIPTION = "Automatically aligning the columns of Markdown tables in text files before committing them."
REQUIRED_PROGRAM = "git"


class ResearchCheckError(RuntimeError):
    """The call ran, but the check did not see what it has to see."""


def run_check(config: Config, local: LocalSettings, run_id: str, call: Callable[..., model_call.ModelResult] = model_call.call_model) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "pass": PASS_NAME,
        "run_id": run_id,
        "status": STATUS_OK,
        "stop_reason": None,
        "searches": 0,
        "fetches": 0,
        "cost_usd": 0.0,
        "failed_sessions": [],
        "backlog_sessions": [],
        "secrets_redacted": 0,
        "windows_reset": [],
        "memory_snapshot": {"errors": []},
    }
    try:
        if shutil.which(REQUIRED_PROGRAM) is None:
            raise ResearchCheckError(f"{REQUIRED_PROGRAM} is not on the PATH of this process")
        record = research.research_description(
            DESCRIPTION,
            pass_support.private_material(config, local, (), ()),
            config,
            os.path.join(config.paths.data_dir, "logs", f"{PASS_NAME}-{run_id}.usage.jsonl"),
            config.research.budget_per_candidate_usd,
            call,
        )
        result["searches"] = len(record["searched"])
        result["fetches"] = len(record["fetched"])
        result["cost_usd"] = record["cost_usd"]
        if not any(fetch["worked"] for fetch in record["fetched"]):
            raise ResearchCheckError(f"no page was fetched: {len(record['fetched'])} fetches tried, none worked")
    except (
        ResearchCheckError,
        research.SearchUnavailableError,
        research.PrivateMaterialError,
        research.ResearchRejectedError,
        model_call.ModelCallError,
        subprocess.TimeoutExpired,
    ) as error:
        result["status"] = STATUS_FAILED
        result["stop_reason"] = f"{type(error).__name__}: {error}"
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
    result = run_check(config, load_local_settings(config.paths.local_settings), arguments.run_id)
    with open(arguments.result_file, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
