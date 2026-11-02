"""What the monthly pass reads, measured by script: the setup's files, what each session loads,
paths that are gone, and which memories look alike. No model, and nothing here writes.

What a session loads, as the product's memory documentation states it: the user's ``CLAUDE.md``
and its imports, up to a set number of hops; ``CLAUDE.md``, ``.claude/CLAUDE.md`` and
``CLAUDE.local.md`` in the working folder and above it; rule files in ``.claude/rules``; and the
start of the memory index, up to set limits in lines and bytes. Skill names and descriptions are
listed too. Plugin skills, tool server definitions, the product's own prompt and what session
start hooks print are not measured, and the report says so.

Every line is redacted, and cannot close a tag it is shown in, from the moment it is read: what a
call sees is what a citation is checked against, and a redacted block keeps its lines, so line
numbers stay those of the file.

Duplicates are a comparison first: each memory and each section of an instructions file is a
weighted word vector, and pairs with a cosine at or over a set value become candidates. A candidate
counts for nothing until a reader has compared the texts.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

import backfill
import memory_store
import render
import sessions
from config import Config, SecretsConfig

ROLE_GLOBAL = "global_instructions"
ROLE_PROJECT = "project_instructions"
ROLE_MEMORY = "memory"
ROLE_SKILL = "skill"
ROLE_SETTING = "setting_fact"
FEEDBACK_TYPE = "feedback"
SKILL_FILE = "SKILL.md"
NOT_MEASURED = (
    "plugin skills", "tool server definitions", "the product's own prompt", "what session start hooks print",
)
_INSTRUCTION_NAMES = ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md"), "CLAUDE.local.md")
_CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_IMPORT_RE = re.compile(r"(?:^|(?<=\s))@([^\s`'\"<>]+)", re.M)
_PATH_RE = re.compile(r"(?<![\w/\\])(?:[A-Za-z]:[\\/]|~[\\/])[^\s`'\"<>|*?()\[\],;]+")
_HEADING_RE = re.compile(r"^#{1,6}\s")
_WORD_RE = re.compile(r"[a-z0-9_]{3,}")


@dataclass(frozen=True)
class SourceFile:
    """One file of the setup, or the generated list of setting facts."""

    ref: str
    path: str
    role: str
    project_folder: str
    name: str
    lines: tuple[str, ...]
    feedback: bool = False

    @property
    def chars(self) -> int:
        return sum(len(line) + 1 for line in self.lines)


@dataclass(frozen=True)
class Unit:
    """What is compared for duplicates: a memory, or a section of an instructions file."""

    source: SourceFile
    start: int
    end: int

    @property
    def label(self) -> str:
        return f"{self.source.ref}:{self.start}"

    def text(self) -> str:
        return "\n".join(self.source.lines[self.start - 1:self.end])

    def render(self) -> str:
        numbered = "\n".join(f"{number}: {self.source.lines[number - 1]}" for number in range(self.start, self.end + 1))
        return f'<unit file="{self.source.ref}" role="{self.source.role}" project="{self.source.project_folder}" name="{self.source.name}">\n{numbered}\n</unit>'


@dataclass(frozen=True)
class Candidate:
    """Texts the comparison found alike, for a reader to judge."""

    ref: str
    units: tuple[Unit, ...]
    best_cosine: float
    same_name: bool


@dataclass(frozen=True)
class Comparison:
    """The result of comparing for duplicates, with the texts that were alike and yet are in no
    candidate, because a group of them was too large to show whole."""

    candidates: tuple[Candidate, ...]
    left_out: tuple[str, ...]


@dataclass(frozen=True)
class Group:
    """Files read together in one tool-less call."""

    name: str
    files: tuple[SourceFile, ...]

    @property
    def chars(self) -> int:
        return sum(item.chars for item in self.files)


@dataclass(frozen=True)
class Corpus:
    global_files: tuple[SourceFile, ...]
    project_files: tuple[SourceFile, ...]
    memories: tuple[SourceFile, ...]
    skills: tuple[SourceFile, ...]
    settings: SourceFile
    chain_of_folder: Mapping[str, tuple[str, ...]]
    cwd_of_folder: Mapping[str, Optional[str]]
    unreadable_headers: tuple[dict[str, str], ...] = ()
    pattern_matches: int = 0

    def all_files(self) -> tuple[SourceFile, ...]:
        return (*self.global_files, self.settings, *self.project_files, *self.memories, *self.skills)


def _read_text_safely(path: str, secrets: SecretsConfig) -> tuple[str, int]:
    with open(path, encoding="utf-8") as handle:
        text, matches = render.redact_keeping_lines(handle.read(), secrets)
    return render.neutralise_tags(text), matches


def _read_lines(path: str, secrets: SecretsConfig) -> tuple[str, ...]:
    return tuple(_read_text_safely(path, secrets)[0].splitlines())


def _front_matter(item: SourceFile) -> tuple[dict[str, Any], str]:
    """A file's header and body. One that cannot be read counts as having no header, and
    ``read_corpus`` has listed it for the report."""
    text = "\n".join(item.lines)
    try:
        return backfill.read_front_matter(text, item.path)
    except backfill.InventoryError:
        return {}, text


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def imports_of(path: str, hops_left: int, seen: Optional[set[str]] = None) -> list[str]:
    """This file and what it imports, in loading order. An import that names no file is left out,
    as the product does: ``@word`` in prose is not always an import."""
    seen = set() if seen is None else seen
    if _key(path) in seen:
        return []
    seen.add(_key(path))
    found = [path]
    if hops_left <= 0:
        return found
    with open(path, encoding="utf-8") as handle:
        text = _CODE_RE.sub(" ", handle.read())
    for target in _IMPORT_RE.findall(text):
        expanded = os.path.expanduser(target)
        resolved = expanded if os.path.isabs(expanded) else os.path.join(os.path.dirname(path), expanded)
        if os.path.isfile(resolved):
            found.extend(imports_of(os.path.normpath(resolved), hops_left - 1, seen))
    return found


def _rule_files(rules_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(glob.escape(rules_dir), "**", "*.md"), recursive=True))


def global_chain(config: Config) -> list[str]:
    """The user's instructions. A missing file stops the pass, since nothing else can be compared to them."""
    root = config.monthly.global_claude_file
    if not os.path.isfile(root):
        raise FileNotFoundError(f"global instructions not found: {root}")
    seen: set[str] = set()
    chain = imports_of(root, config.monthly.import_max_hops, seen)
    for rule in _rule_files(config.monthly.global_rules_dir):
        chain.extend(imports_of(rule, config.monthly.import_max_hops, seen))
    return chain


def project_chain(cwd: Optional[str], config: Config, skip: set[str]) -> list[str]:
    """Instructions from the working folder up to the root. A folder since removed loads nothing."""
    if cwd is None or not os.path.isdir(cwd):
        return []
    # The user's own file is the global instructions, wherever the walk up from a project passes it.
    seen = {*skip, _key(os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md"))}
    chain: list[str] = []
    current = os.path.abspath(cwd)
    while True:
        for name in _INSTRUCTION_NAMES:
            path = os.path.join(current, name)
            if os.path.isfile(path):
                chain.extend(imports_of(path, config.monthly.import_max_hops, seen))
        for rule in _rule_files(os.path.join(current, ".claude", "rules")):
            chain.extend(imports_of(rule, config.monthly.import_max_hops, seen))
        parent = os.path.dirname(current)
        if parent == current:
            return chain
        current = parent


def cwd_of_project(project_dir: str) -> Optional[str]:
    """The working folder of a project, from its newest session that records one, because folder
    names are lossy. None if no transcript remains."""
    transcripts = [os.path.join(project_dir, name) for name in os.listdir(project_dir) if name.endswith(".jsonl")]
    for path in sorted(transcripts, key=os.path.getmtime, reverse=True):
        with open(path, "rb") as handle:
            for line in handle:
                if b'"cwd"' not in line:
                    continue
                cwd = json.loads(line).get("cwd")
                if cwd:
                    return cwd
    return None


def _setting_facts(config: Config, ref: str) -> SourceFile:
    """Whether settings that change what sessions are told are set, one fact a line, so that a
    finding can cite them like any other text."""
    documents = [config.inventory.settings_file, *[path for path in config.inventory.optional_settings_files if os.path.isfile(path)]]
    lines = []
    for path in documents:
        with open(path, encoding="utf-8") as handle:
            values = json.load(handle)
        for key in config.monthly.setting_fact_keys:
            state = f"is set to {json.dumps(values[key], ensure_ascii=False)}" if key in values else "is not set"
            lines.append(f"The setting {key} {state} in {os.path.basename(path)}.")
    safe = render.neutralise_tags(render.redact_keeping_lines("\n".join(lines), config.secrets)[0])
    return SourceFile(ref, config.inventory.settings_file, ROLE_SETTING, "", "setting facts", tuple(safe.splitlines()))


def _is_feedback(lines: Sequence[str], name: str, path: str) -> bool:
    front, _ = _front_matter(SourceFile("", path, ROLE_MEMORY, "", name, tuple(lines)))
    metadata = front.get("metadata")
    kind = front.get("type") or (metadata.get("type") if isinstance(metadata, dict) else None)
    return kind == FEEDBACK_TYPE or name.startswith(FEEDBACK_TYPE)


def _unreadable_headers(files: Iterable[SourceFile]) -> tuple[dict[str, str], ...]:
    found = []
    for item in files:
        try:
            backfill.read_front_matter("\n".join(item.lines), item.path)
        except backfill.InventoryError as error:
            found.append({"what": item.path, "detail": str(error)})
    return tuple(found)


def read_corpus(config: Config) -> Corpus:
    """Every file of the setup, numbered in a stable order."""
    counter = 0

    def next_ref() -> str:
        nonlocal counter
        counter += 1
        return f"f{counter}"

    secrets = config.secrets
    global_paths = global_chain(config)
    global_files = tuple(SourceFile(next_ref(), path, ROLE_GLOBAL, "", os.path.basename(path), _read_lines(path, secrets)) for path in global_paths)
    settings = _setting_facts(config, next_ref())
    chain_of_folder: dict[str, tuple[str, ...]] = {}
    cwd_of_folder: dict[str, Optional[str]] = {}
    project_files: dict[str, SourceFile] = {}
    memories = []
    skip = {_key(path) for path in global_paths}
    for folder in memory_store.memory_folders(config.paths.projects_dir):
        if not any(name.endswith(".md") for name in memory_store.list_files(folder)):
            continue
        project = os.path.basename(os.path.dirname(folder))
        cwd = cwd_of_project(os.path.dirname(folder))
        cwd_of_folder[project] = cwd
        chain = project_chain(cwd, config, skip)
        chain_of_folder[project] = tuple(_key(path) for path in chain)
        for path in chain:
            if _key(path) not in project_files:
                project_files[_key(path)] = SourceFile(next_ref(), path, ROLE_PROJECT, project, os.path.basename(path), _read_lines(path, secrets))
        for relative in memory_store.list_files(folder):
            if relative == memory_store.INDEX_FILE or not relative.endswith(".md"):
                continue
            path = os.path.join(folder, relative)
            lines = _read_lines(path, secrets)
            name = relative[: -len(".md")]
            memories.append(SourceFile(next_ref(), path, ROLE_MEMORY, project, name, lines, _is_feedback(lines, name, path)))
    skills = []
    root = config.inventory.skills_dir
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name, SKILL_FILE)
        if os.path.isfile(path):
            skills.append(SourceFile(next_ref(), path, ROLE_SKILL, "", name, _read_lines(path, secrets)))
    every_file = (*global_files, *project_files.values(), *memories, *skills)
    matches = sum(_read_text_safely(item.path, secrets)[1] for item in every_file)
    return Corpus(
        global_files, tuple(project_files.values()), tuple(memories), tuple(skills), settings, chain_of_folder, cwd_of_folder,
        _unreadable_headers((*memories, *skills)), matches,
    )


def _pack(name: str, shared: Sequence[SourceFile], blocks: Iterable[Sequence[SourceFile]], limit: int) -> list[Group]:
    """Blocks in order into as few groups as fit, each with ``shared``. A block is never split."""
    groups: list[list[SourceFile]] = []
    shared_chars = sum(item.chars for item in shared)
    room = 0
    for block in blocks:
        size = sum(item.chars for item in block)
        if size + shared_chars > limit:
            raise ValueError(f"group {name}: a block of {size} characters with {shared_chars} shared is over the {limit} limit")
        if not groups or size > room:
            groups.append([])
            room = limit - shared_chars
        groups[-1].extend(block)
        room -= size
    return [
        Group(f"{name}-{index}", tuple(_distinct([*shared, *members])))
        for index, members in enumerate(groups, 1)
    ]


def _distinct(files: Iterable[SourceFile]) -> list[SourceFile]:
    seen: set[str] = set()
    kept = []
    for item in files:
        if item.ref not in seen:
            seen.add(item.ref)
            kept.append(item)
    return kept


def coherence_groups(corpus: Corpus, limit: int) -> list[Group]:
    """Three readings, so that a contradiction across folders can be seen without one huge call:
    every rule-like text together; the other memories folder by folder; each skill against the rules."""
    shared = [*corpus.global_files, corpus.settings]
    feedback = [item for item in corpus.memories if item.feedback]
    by_path = {_key(item.path): item for item in corpus.project_files}
    groups = _pack("rules", shared, [[item] for item in (*corpus.project_files, *feedback)], limit)
    blocks = []
    for folder in sorted(corpus.chain_of_folder):
        rest = [item for item in corpus.memories if item.project_folder == folder and not item.feedback]
        if rest:
            blocks.append([*[by_path[path] for path in corpus.chain_of_folder[folder]], *rest])
    groups.extend(_pack("memories", shared, blocks, limit))
    groups.extend(_pack("skills", [*shared, *feedback], [[item] for item in corpus.skills], limit))
    return groups


def render_group(group: Group) -> str:
    parts = []
    for item in group.files:
        numbered = "\n".join(f"{number}: {line}" for number, line in enumerate(item.lines, 1))
        parts.append(f'<file ref="{item.ref}" role="{item.role}" project="{item.project_folder}" name="{item.name}">\n{numbered}\n</file>')
    return "\n\n".join(parts)


def missing_paths(item: SourceFile) -> dict[int, list[str]]:
    """By line, paths named that no longer exist. A path on a drive that is not mounted says
    nothing, so it is left out. A path with spaces may be cut short here: this is a signal for a
    reader, never a finding by itself."""
    found: dict[int, list[str]] = {}
    for number, line in enumerate(item.lines, 1):
        for raw in _PATH_RE.findall(line):
            path = raw.rstrip(".:'\"")
            expanded = os.path.expanduser(path)
            drive = os.path.splitdrive(expanded)[0]
            if drive and not os.path.isdir(f"{drive}{os.sep}"):
                continue
            if not os.path.exists(expanded):
                found.setdefault(number, []).append(path)
    return found


def stated_limit_lines(item: SourceFile, patterns: Sequence[str]) -> list[int]:
    """Lines where the text says it holds only for a while, such as "for now"."""
    return [number for number, line in enumerate(item.lines, 1) if any(re.search(pattern, line) for pattern in patterns)]


def render_signals(group: Group, patterns: Sequence[str]) -> str:
    """What scripts found in these files, for the reader to weigh."""
    lines = []
    for item in group.files:
        if item.role == ROLE_SKILL:
            continue
        for number, paths in sorted(missing_paths(item).items()):
            lines.append(json.dumps({"file": item.ref, "line": number, "signal": "path not found", "paths": paths}, ensure_ascii=False))
        for number in stated_limit_lines(item, patterns):
            lines.append(json.dumps({"file": item.ref, "line": number, "signal": "states a limit"}, ensure_ascii=False))
    return "\n".join(lines)


def _skill_listing_chars(corpus: Corpus) -> list[dict[str, Any]]:
    listing = []
    for item in corpus.skills:
        front, _ = _front_matter(item)
        description = front.get("description")
        listing.append({"skill": item.name, "chars": len(item.name) + (len(description) if isinstance(description, str) else 0)})
    return listing


def _loaded_index(lines: Sequence[str], max_lines: int, max_bytes: int) -> tuple[int, int, Optional[int]]:
    """(lines loaded, characters loaded, number of the first line not loaded fully, or None)."""
    used_bytes = 0
    used_chars = 0
    for number, line in enumerate(lines, 1):
        if number > max_lines:
            return number - 1, used_chars, number
        size = len(line.encode("utf-8")) + 1
        if used_bytes + size > max_bytes:
            return number - 1, used_chars, number
        used_bytes += size
        used_chars += len(line) + 1
    return len(lines), used_chars, None


def _folder_known(cwd: Optional[str]) -> bool:
    return cwd is not None and os.path.isdir(cwd)


def measure_context(corpus: Corpus, config: Config) -> dict[str, Any]:
    """Characters each session starts with, per project. Tokens are an estimate at a set ratio."""
    settings = config.monthly
    global_entries = [{"path": item.path, "chars": item.chars} for item in corpus.global_files]
    global_chars = sum(entry["chars"] for entry in global_entries)
    listing = _skill_listing_chars(corpus)
    listing_chars = sum(entry["chars"] for entry in listing)
    by_path = {_key(item.path): item for item in corpus.project_files}
    projects = []
    for folder in sorted(corpus.chain_of_folder):
        index_path = os.path.join(config.paths.projects_dir, folder, "memory", memory_store.INDEX_FILE)
        lines = _read_lines(index_path, config.secrets) if os.path.isfile(index_path) else ()
        loaded_lines, loaded_chars, first_cut = _loaded_index(lines, settings.index_lines_loaded, settings.index_bytes_loaded)
        instructions = sum(by_path[path].chars for path in corpus.chain_of_folder[folder])
        projects.append({
            "project_folder": folder,
            "cwd": corpus.cwd_of_folder[folder],
            "folder_known": _folder_known(corpus.cwd_of_folder[folder]),
            "instructions_chars": instructions,
            "index_path": index_path,
            "index_lines": len(lines),
            "index_lines_loaded": loaded_lines,
            "index_chars_loaded": loaded_chars,
            "index_first_line_cut": first_cut,
            "total_chars": global_chars + listing_chars + instructions + loaded_chars,
        })
    # With no known folder, its instructions cannot be found, and 0 would pull the typical figure down.
    totals = [project["total_chars"] for project in projects if project["folder_known"]]
    largest = sorted(
        [
            *({"what": f"global instructions: {entry['path']}", "chars": entry["chars"]} for entry in global_entries),
            *({"what": f"instructions: {item.path}", "chars": item.chars} for item in corpus.project_files),
            *({"what": f"skill listing: {entry['skill']}", "chars": entry["chars"]} for entry in listing),
            *({"what": f"memory index: {project['project_folder']}", "chars": project["index_chars_loaded"]} for project in projects),
        ],
        key=lambda entry: -entry["chars"],
    )[: settings.context_largest_shown]
    return {
        "global_chars": global_chars,
        "global_files": global_entries,
        "skill_listing_chars": listing_chars,
        "skills_listed": len(listing),
        "projects": projects,
        "projects_without_a_known_folder": sum(1 for project in projects if not project["folder_known"]),
        "median_chars": int(statistics.median(totals)) if totals else None,
        "max_chars": max(totals) if totals else None,
        "tokens_estimate_ratio": settings.chars_per_token_estimate,
        "largest": largest,
        "not_measured": list(NOT_MEASURED),
    }


def _units(corpus: Corpus, min_words: int) -> list[Unit]:
    units = [Unit(item, 1, len(item.lines)) for item in corpus.memories if item.lines]
    for item in (*corpus.global_files, *corpus.project_files):
        starts = [number for number, line in enumerate(item.lines, 1) if _HEADING_RE.match(line)]
        bounds = sorted({1, *starts})
        for position, start in enumerate(bounds):
            end = bounds[position + 1] - 1 if position + 1 < len(bounds) else len(item.lines)
            if end >= start:
                unit = Unit(item, start, end)
                if len(_WORD_RE.findall(unit.text().lower())) >= min_words:
                    units.append(unit)
    return units


def _body_words(unit: Unit) -> list[str]:
    """Words of the text. A memory's bookkeeping lines (stamps, ids, node types) would make every
    memory look alike, so its frontmatter counts only for its description."""
    text = unit.text()
    if unit.source.role == ROLE_MEMORY:
        front, body = _front_matter(unit.source)
        description = front.get("description")
        text = f"{description if isinstance(description, str) else ''}\n{body}"
    return _WORD_RE.findall(text.lower())


def _vectors(units: Sequence[Unit]) -> list[dict[str, float]]:
    counts = [Counter(_body_words(unit)) for unit in units]
    frequency: Counter[str] = Counter()
    for count in counts:
        frequency.update(count.keys())
    total = len(units)
    vectors = []
    for count in counts:
        weights = {word: (1 + math.log(number)) * math.log(total / frequency[word]) for word, number in count.items() if frequency[word] < total}
        size = math.sqrt(sum(value * value for value in weights.values()))
        vectors.append({word: value / size for word, value in weights.items()} if size else {})
    return vectors


def _similar_pairs(vectors: Sequence[Mapping[str, float]]) -> dict[tuple[int, int], float]:
    postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for index, vector in enumerate(vectors):
        for word, value in vector.items():
            postings[word].append((index, value))
    scores: dict[tuple[int, int], float] = defaultdict(float)
    for entries in postings.values():
        for position, (first, first_value) in enumerate(entries):
            for second, second_value in entries[position + 1:]:
                scores[(first, second)] += first_value * second_value
    return scores


def _clusters(size: int, edges: Sequence[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(size))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for first, second in edges:
        parent[find(first)] = find(second)
    members: dict[int, list[int]] = defaultdict(list)
    for node in {node for edge in edges for node in edge}:
        members[find(node)].append(node)
    return [sorted(group) for group in members.values()]


def duplicate_candidates(corpus: Corpus, config: Config) -> list[Candidate]:
    return list(compare_for_duplicates(corpus, config).candidates)


def compare_for_duplicates(corpus: Corpus, config: Config) -> Comparison:
    """Groups of texts alike by cosine, or memories of one name in two folders. Two sections of one
    file are not compared. A group over the size limit is split by raising the bar inside it, which
    can leave texts in no group: those are named in the result."""
    settings = config.monthly
    units = _units(corpus, settings.duplicate_section_min_words)
    scores = _similar_pairs(_vectors(units))
    same_name: set[tuple[int, int]] = set()
    by_name: dict[str, list[int]] = defaultdict(list)
    for index, unit in enumerate(units):
        if unit.source.role == ROLE_MEMORY:
            by_name[unit.source.name].append(index)
    for members in by_name.values():
        for position, first in enumerate(members):
            same_name.update((first, second) for second in members[position + 1:])

    def comparable(pair: tuple[int, int]) -> bool:
        return units[pair[0]].source.ref != units[pair[1]].source.ref

    edges = {pair: score for pair, score in scores.items() if score >= settings.duplicate_cosine_min and comparable(pair)}
    named = {pair: scores.get(pair, 0.0) for pair in same_name}

    def split(nodes: Sequence[int], bar: float) -> list[list[int]]:
        inside = set(nodes)
        kept = [pair for pair, score in edges.items() if pair[0] in inside and pair[1] in inside and score >= bar]
        kept += [pair for pair in named if pair[0] in inside and pair[1] in inside]
        result = []
        for group in _clusters(len(units), kept):
            if len(group) <= settings.duplicate_cluster_max_members or bar >= 1.0:
                result.append(group[: settings.duplicate_cluster_max_members])
            else:
                result.extend(split(group, bar + 0.05))
        return result

    every = sorted({node for pair in [*edges, *named] for node in pair})
    candidates = []
    chosen = sorted(split(every, settings.duplicate_cosine_min), key=lambda nodes: nodes[0])
    for position, group in enumerate(chosen, 1):
        inside = set(group)
        best = max((score for pair, score in {**named, **edges}.items() if pair[0] in inside and pair[1] in inside), default=0.0)
        candidates.append(Candidate(
            f"c{position}", tuple(units[node] for node in group), round(best, 3),
            any(pair[0] in inside and pair[1] in inside for pair in named),
        ))
    shown = {node for group in chosen for node in group}
    return Comparison(tuple(candidates), tuple(units[node].label for node in every if node not in shown))


def render_candidate(candidate: Candidate) -> str:
    units = "\n".join(unit.render() for unit in candidate.units)
    return f'<cluster ref="{candidate.ref}" same_memory_name="{str(candidate.same_name).lower()}" best_cosine="{candidate.best_cosine}">\n{units}\n</cluster>'


def pack_candidates(candidates: Sequence[Candidate], limit: int) -> list[list[Candidate]]:
    """Candidates into calls of at most ``limit`` characters."""
    batches: list[list[Candidate]] = []
    room = 0
    for candidate in candidates:
        size = len(render_candidate(candidate))
        if size > limit:
            raise ValueError(f"candidate {candidate.ref} of {size} characters is over the {limit} limit")
        if not batches or size > room:
            batches.append([])
            room = limit
        batches[-1].append(candidate)
        room -= size
    return batches


def skill_opening(item: SourceFile, chars: int) -> dict[str, str]:
    """What a skill says it is, for writing a general description of the need it meets."""
    front, body = _front_matter(item)
    description = front.get("description")
    return {"skill": item.name, "description": description if isinstance(description, str) else "", "opening": body[:chars]}


def discovered_projects(config: Config) -> list[str]:
    return sorted({files.project_folder for files in sessions.discover_sessions(config.paths.projects_dir)})
