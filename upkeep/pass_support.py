"""What the weekly and monthly passes share: tracked model calls, replies reused within a period,
and what may not reach a search engine. Knows no pass and no prompt."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable, Iterable, Mapping

import daily
import extract
import memory_store
import model_call
import research
import schemas
from config import Config, LocalSettings


def write_json(path: str, document: Mapping[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    extract.write_json_atomic(path, document)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class Caller:
    """Model calls of one pass, tracked, with the pass's remaining budget."""

    def __init__(self, config: Config, report_dir: str, run_id: str, spent_before: float, call: Callable[..., model_call.ModelResult]):
        self.config = config
        self.call = call
        self.spent_before = spent_before
        self.usage_log = os.path.join(report_dir, "usage.jsonl")
        self.totals = daily.RunTotals(os.path.join(config.paths.data_dir, "logs", "usage.jsonl"), run_id)

    def remaining(self) -> float:
        left = self.config.model.run_budget_usd - self.spent_before - self.totals.cost_usd
        if left <= 0:
            raise model_call.BudgetExhaustedError(f"the run budget of {self.config.model.run_budget_usd} is spent")
        return left

    def tracked(self, key: str) -> Callable[..., model_call.ModelResult]:
        return self.totals.wrap(self.call, key)


def cached_or_called_reply(
    path: str, prompt: str, stdin_text: str, model: str, key: str, caller: Caller, parse: Callable[[str], Any]
) -> Any:
    """A tool-less call, or its reply from an earlier run if the input is the same."""
    digest = hashlib.sha256(f"{prompt}\n{stdin_text}".encode("utf-8")).hexdigest()
    if os.path.exists(path):
        cached = read_json(path)
        if cached["input_sha256"] == digest:
            return parse(cached["reply"])
    config = caller.config
    result = caller.tracked(key)(
        prompt=prompt,
        stdin_text=stdin_text,
        tools=(),
        model=model,
        max_budget_usd=caller.remaining(),
        cwd=config.paths.run_dir,
        claude_exe=config.paths.claude_exe,
        model_config=config.model,
        chunking_config=config.chunking,
        usage_log_path=caller.usage_log,
    )
    try:
        parsed = parse(result.text)
    except schemas.SchemaError:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(f"{path}.rejected", "w", encoding="utf-8") as handle:
            handle.write(result.text)
        raise
    write_json(path, {"input_sha256": digest, "reply": result.text})
    return parsed


def private_material(config: Config, local: LocalSettings, project_names: Iterable[str], project_folders: Iterable[str]) -> research.PrivateMaterial:
    """What may not reach a search engine, worked out from what this machine holds."""
    terms = [*local.private_terms, os.path.basename(os.path.expanduser("~")), *project_names, *project_folders]
    texts = []
    for folder in memory_store.memory_folders(config.paths.projects_dir):
        for name in memory_store.list_files(folder):
            if name.endswith(".md") and name != memory_store.INDEX_FILE:
                if "-" in name:
                    terms.append(name[:-3])
                texts.append(memory_store.read_memory_file(os.path.join(folder, name)))
    return research.build_private_material(terms, texts, config.research.memory_shingle_words)
