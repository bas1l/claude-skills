"""Load and validate the upkeep configuration.

Every section and key in ``config.json`` is required, and unknown keys raise, so a
typo cannot silently fall back to a value in code. Paths beginning with ``~`` are
resolved against the home directory of whoever runs the job.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Mapping

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


@dataclass(frozen=True)
class PathsConfig:
    projects_dir: str
    data_dir: str
    run_dir: str
    claude_exe: str
    local_settings: str


@dataclass(frozen=True)
class SessionsConfig:
    start_date: datetime
    excluded_cwd_prefixes: tuple[str, ...]
    excluded_cwd_globs: tuple[str, ...]
    count_only_cwd_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class CutsConfig:
    tool_chars: int
    report_chars: int
    pasted_chars: int
    compact_summary_chars: int
    system_chars: int
    hook_chars: int
    report_tools: tuple[str, ...]
    hook_repeat_prefix_chars: int


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_chars: int
    stdin_limit_bytes: int


@dataclass(frozen=True)
class ModelConfig:
    extract_model: str
    run_budget_usd: float
    call_timeout_seconds: int
    scrub_env_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class CountsConfig:
    error_classes: tuple[tuple[str, str], ...]
    class_scan_chars: int
    signature_chars: int
    shell_tools: tuple[str, ...]


@dataclass(frozen=True)
class MemoryConfig:
    author_name: str
    author_email: str


@dataclass(frozen=True)
class SecretsConfig:
    patterns: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class InventoryConfig:
    skills_dir: str
    settings_file: str
    optional_settings_files: tuple[str, ...]
    plugins_manifest: str
    user_config: str


@dataclass(frozen=True)
class LedgerConfig:
    direct_against_entries: int
    inferred_against_entries: int
    inferred_window_days: int
    stated_limit_patterns: tuple[str, ...]
    origin_tools: tuple[str, ...]


@dataclass(frozen=True)
class WeeklyConfig:
    memory_model: str
    proposal_model: str
    recurrence_sessions: int
    costly_once_tool_calls: int
    failure_min_commands_lost: int
    failures_shown: int
    max_deletions_per_pass: int
    quote_failure_batch_min: int
    said_quote_shared_word_letters: int
    group_chars: int
    source_assistant_chars: int
    claim_max_chars: int
    title_max_chars: int
    index_hook_chars: int
    reproposal_word_overlap: float
    memory_excluded_origins: tuple[str, ...]


@dataclass(frozen=True)
class ResearchConfig:
    model: str
    budget_per_candidate_usd: float
    max_per_pass: int
    description_max_chars: int
    memory_shingle_words: int
    public_path_fragments: tuple[str, ...]


@dataclass(frozen=True)
class ReviewConfig:
    skills_base_branch: str
    skills_branch_prefix: str
    failures_shown: int


@dataclass(frozen=True)
class LocalSettings:
    """What differs per machine and stays out of this public repository."""

    python_exe: str
    apply_memory_changes: bool
    private_terms: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    paths: PathsConfig
    sessions: SessionsConfig
    cuts: CutsConfig
    chunking: ChunkingConfig
    model: ModelConfig
    counts: CountsConfig
    memory: MemoryConfig
    secrets: SecretsConfig
    inventory: InventoryConfig
    ledger: LedgerConfig
    weekly: WeeklyConfig
    research: ResearchConfig
    review: ReviewConfig


def _expand_path(value: str) -> str:
    return os.path.normpath(os.path.expanduser(value))


def _check_keys(section: str, values: Mapping[str, Any], dataclass_type: type) -> None:
    expected = {field.name for field in fields(dataclass_type)}
    actual = set(values)
    if actual != expected:
        raise ValueError(
            f"config section {section!r}: missing {sorted(expected - actual)}, unknown {sorted(actual - expected)}"
        )


def _parse_utc_aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"config start_date must carry a UTC offset: {value!r}")
    return parsed


def config_from_mapping(raw: Mapping[str, Any]) -> Config:
    """Build a validated Config from the parsed JSON document."""
    _check_keys("<root>", raw, Config)
    for section, section_type in (
        ("paths", PathsConfig),
        ("sessions", SessionsConfig),
        ("cuts", CutsConfig),
        ("chunking", ChunkingConfig),
        ("model", ModelConfig),
        ("counts", CountsConfig),
        ("memory", MemoryConfig),
        ("secrets", SecretsConfig),
        ("inventory", InventoryConfig),
        ("ledger", LedgerConfig),
        ("weekly", WeeklyConfig),
        ("research", ResearchConfig),
        ("review", ReviewConfig),
    ):
        _check_keys(section, raw[section], section_type)

    sessions = raw["sessions"]
    cuts = raw["cuts"]
    model = raw["model"]
    counts = raw["counts"]
    inventory = raw["inventory"]
    ledger = raw["ledger"]
    return Config(
        paths=PathsConfig(**{key: _expand_path(value) for key, value in raw["paths"].items()}),
        sessions=SessionsConfig(
            start_date=_parse_utc_aware(sessions["start_date"]),
            excluded_cwd_prefixes=tuple(_expand_path(p) for p in sessions["excluded_cwd_prefixes"]),
            excluded_cwd_globs=tuple(_expand_path(p) for p in sessions["excluded_cwd_globs"]),
            count_only_cwd_prefixes=tuple(_expand_path(p) for p in sessions["count_only_cwd_prefixes"]),
        ),
        cuts=CutsConfig(**{**cuts, "report_tools": tuple(cuts["report_tools"])}),
        chunking=ChunkingConfig(**raw["chunking"]),
        model=ModelConfig(**{**model, "scrub_env_prefixes": tuple(model["scrub_env_prefixes"])}),
        counts=CountsConfig(
            error_classes=tuple((name, pattern) for name, pattern in counts["error_classes"]),
            class_scan_chars=counts["class_scan_chars"],
            signature_chars=counts["signature_chars"],
            shell_tools=tuple(counts["shell_tools"]),
        ),
        memory=MemoryConfig(**raw["memory"]),
        secrets=SecretsConfig(patterns=tuple((name, pattern) for name, pattern in raw["secrets"]["patterns"])),
        inventory=InventoryConfig(
            skills_dir=_expand_path(inventory["skills_dir"]),
            settings_file=_expand_path(inventory["settings_file"]),
            optional_settings_files=tuple(_expand_path(p) for p in inventory["optional_settings_files"]),
            plugins_manifest=_expand_path(inventory["plugins_manifest"]),
            user_config=_expand_path(inventory["user_config"]),
        ),
        ledger=LedgerConfig(
            **{
                **ledger,
                "stated_limit_patterns": tuple(ledger["stated_limit_patterns"]),
                "origin_tools": tuple(ledger["origin_tools"]),
            }
        ),
        weekly=WeeklyConfig(**{**raw["weekly"], "memory_excluded_origins": tuple(raw["weekly"]["memory_excluded_origins"])}),
        research=ResearchConfig(**{**raw["research"], "public_path_fragments": tuple(raw["research"]["public_path_fragments"])}),
        review=ReviewConfig(**raw["review"]),
    )


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Config:
    """Read ``config.json`` from ``path``; any missing or unknown key raises."""
    with open(path, encoding="utf-8") as handle:
        return config_from_mapping(json.load(handle))


def load_local_settings(path: str) -> LocalSettings:
    """Read the machine's settings file. ``apply_memory_changes`` must be there and literally
    true or false, so that nothing but a deliberate ``true`` lets a pass change a memory."""
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    _check_keys(path, raw, LocalSettings)
    if not isinstance(raw["apply_memory_changes"], bool):
        raise ValueError(f"{path}: apply_memory_changes must be true or false")
    terms = raw["private_terms"]
    if not isinstance(terms, list) or not all(isinstance(term, str) and term.strip() for term in terms):
        raise ValueError(f"{path}: private_terms must be a list of non-empty strings")
    return LocalSettings(raw["python_exe"], raw["apply_memory_changes"], tuple(terms))
