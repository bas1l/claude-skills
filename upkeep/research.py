"""Tool-limited internet research for a generic description of a need.

The description is checked for private material before anything is sent, and the queries and
fetched links the model actually used are checked after. What was searched comes from the record of the run, not
from the model's account, and each link must appear in what the tools returned.

Outcomes:

    SearchUnavailableError   search did not work; the pass fails and writes no proposal
    PrivateMaterialError     private material in a description or a query; the pass fails
    ResearchRejectedError    the reply is malformed or names links nobody saw; this proposal
                             is rejected and the pass goes on

Web text ends up only in the research record of a proposal. Nothing here touches a memory.
Knows nothing of transcripts or projects: the caller supplies what counts as private.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit

import model_call
import schemas
from config import Config

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "research.md")
SCHEMA_VERSION = 1
WEB_SEARCH, WEB_FETCH = model_call.RESEARCH_TOOLS

_WORD_RE = re.compile(r"[a-z0-9]+")
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_PATH_RE = re.compile(
    r"(?:\b[A-Za-z]:[\\/])|(?:~[\\/])|(?:\\\\[A-Za-z0-9])|(?:(?:^|\s)/(?:home|users|mnt|var|etc|tmp|opt|srv)\b)|(?:\.claude\b)",
    re.I,
)
_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_HOST_PORT_RE = re.compile(r"\b[a-z0-9][a-z0-9.-]*:\d{2,5}\b", re.I)
_LOCAL_HOST_RE = re.compile(r"\b[a-z0-9-]+\.(?:local|lan|home|internal)\b", re.I)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_URL_RE = re.compile(r"https?://[^\s\"'<>\]\)\}\\]+", re.I)
_PATTERNS = (
    ("session id", _UUID_RE),
    ("file path", _PATH_RE),
    ("server address", _IP_RE),
    ("host and port", _HOST_PORT_RE),
    ("local host name", _LOCAL_HOST_RE),
    ("email address", _EMAIL_RE),
)


class SearchUnavailableError(RuntimeError):
    """Search could not be used, so nothing can be said about what already exists."""


class PrivateMaterialError(ValueError):
    """Text bound for a search engine holds private material."""


class ResearchRejectedError(ValueError):
    """The research result does not meet its rules, so its proposal is rejected."""


@dataclass(frozen=True)
class PrivateMaterial:
    """What must not reach a search engine. ``terms`` match whole words. ``shingles`` are
    runs of ``shingle_words`` consecutive words from the memories, none of which may appear."""

    terms: tuple[str, ...]
    shingles: frozenset[tuple[str, ...]]
    shingle_words: int


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def build_private_material(terms: Iterable[str], texts: Iterable[str], shingle_words: int) -> PrivateMaterial:
    shingles: set[tuple[str, ...]] = set()
    for text in texts:
        words = _words(text)
        shingles.update(tuple(words[start:start + shingle_words]) for start in range(len(words) - shingle_words + 1))
    return PrivateMaterial(tuple(sorted({term for term in terms if term.strip()})), frozenset(shingles), shingle_words)


def _term_findings(text: str, private: PrivateMaterial) -> list[str]:
    lowered = text.lower()
    if any(re.search(rf"(?<![\w-]){re.escape(term.lower())}(?![\w-])", lowered) for term in private.terms):
        return ["private term"]
    return []


def private_findings(text: str, private: PrivateMaterial) -> list[str]:
    """What is wrong with this text, naming the kind of material and not the material."""
    found = [name for name, pattern in _PATTERNS if pattern.search(text)]
    found.extend(_term_findings(text, private))
    words = _words(text)
    size = private.shingle_words
    if any(tuple(words[start:start + size]) in private.shingles for start in range(len(words) - size + 1)):
        found.append("text copied from a memory")
    return found


def check_description(description: str, private: PrivateMaterial, max_chars: int) -> None:
    """Raise unless this description may go to a search engine."""
    if len(description) > max_chars:
        raise PrivateMaterialError(f"description of {len(description)} characters is over the {max_chars} limit")
    findings = private_findings(description, private)
    if findings:
        raise PrivateMaterialError(f"description refused: {', '.join(findings)}")


def _host_is_private(host: str) -> bool:
    return (
        host == "localhost" or ":" in host or _IP_RE.fullmatch(host) is not None or _LOCAL_HOST_RE.fullmatch(host) is not None
    )


def check_fetched_urls(
    activity: Sequence[model_call.ToolActivity], private: PrivateMaterial, public_fragments: Iterable[str]
) -> None:
    """Raise if a fetched link could carry private material out, or reach a private machine.

    A private host is refused always. The rest of a link is checked only if the model wrote it: a
    link that an earlier search or fetch returned came from the web and carries nothing of the
    user's, and such links often hold ids and common words that the checks would take for private.
    The host of a link is checked for private terms only, since a public site's name can hold
    ``.claude``. A path's leading slash goes, since a site's ``/home`` is not a folder of this PC.
    """
    returned: set[str] = set()
    for item in activity:
        if item.name == WEB_FETCH:
            url = str(item.input["url"])
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            findings = ["private host"] if _host_is_private(host) else []
            if _normal_url(url) not in returned:
                rest = unquote(f"{parts.path.lstrip('/')} {parts.query}")
                for fragment in public_fragments:
                    rest = rest.replace(fragment, " ")
                findings.extend(_term_findings(host, private))
                findings.extend(private_findings(rest, private))
            if findings:
                raise PrivateMaterialError(f"a link the model fetched held private material ({', '.join(findings)})")
        returned.update(_normal_url(url) for url in _URL_RE.findall(item.result_text))


def _searches_of(activity: Sequence[model_call.ToolActivity]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    searches = [item for item in activity if item.name == WEB_SEARCH]
    fetches = [item for item in activity if item.name == WEB_FETCH]
    if not any(not item.is_error and item.result_text.strip() for item in searches):
        raise SearchUnavailableError(f"no search returned anything: {len(searches)} searches, {len(fetches)} fetches")
    return (
        [{"query": str(item.input["query"]), "worked": not item.is_error} for item in searches],
        [{"url": str(item.input["url"]), "worked": not item.is_error} for item in fetches],
    )


def _normal_url(url: str) -> str:
    return url.strip().rstrip("/.,;").lower()


def _urls_seen(activity: Sequence[model_call.ToolActivity]) -> set[str]:
    seen = set()
    for item in activity:
        seen.update(_normal_url(url) for url in _URL_RE.findall(item.result_text))
        if item.name == WEB_FETCH and not item.is_error:
            seen.add(_normal_url(str(item.input["url"])))
    return seen


def _check_links(document: Mapping[str, Any], seen: set[str]) -> None:
    if not document["sources"]:
        raise ResearchRejectedError("names no sources")
    named = [source["url"] for source in document["sources"]] + [tool["url"] for tool in document["existing_tools"]]
    unseen = [url for url in named if _normal_url(url) not in seen]
    if unseen:
        raise ResearchRejectedError(f"{len(unseen)} links never appeared in a search or fetch: {unseen[:3]}")


def research_description(
    description: str,
    private: PrivateMaterial,
    config: Config,
    usage_log_path: str,
    budget_usd: float,
    call: Callable[..., model_call.ModelResult],
) -> dict[str, Any]:
    """Research one description; return the record to store with its proposal."""
    check_description(description, private, config.research.description_max_chars)
    with open(PROMPT_PATH, encoding="utf-8") as handle:
        prompt = handle.read()
    result = call(
        prompt=prompt,
        stdin_text=description,
        tools=model_call.RESEARCH_TOOLS,
        model=config.research.model,
        max_budget_usd=min(budget_usd, config.research.budget_per_candidate_usd),
        cwd=config.paths.run_dir,
        claude_exe=config.paths.claude_exe,
        model_config=config.model,
        chunking_config=config.chunking,
        usage_log_path=usage_log_path,
    )
    check_fetched_urls(result.tool_activity, private, config.research.public_path_fragments)
    searches, fetches = _searches_of(result.tool_activity)
    for search in searches:
        # The model may look up the product's own documented folders. The rest is held to the rule.
        query = search["query"]
        for fragment in config.research.public_path_fragments:
            query = query.replace(fragment, " ")
        findings = private_findings(query, private)
        if findings:
            raise PrivateMaterialError(f"a query the model ran held private material ({', '.join(findings)}): {search['query']!r}")
    try:
        document = schemas.parse_research(result.text)
    except schemas.SchemaError as error:
        raise ResearchRejectedError(f"reply is malformed: {error}") from error
    if not document["search_worked"]:
        raise SearchUnavailableError("the research reply says search did not work")
    _check_links(document, _urls_seen(result.tool_activity))
    return {
        "schema_version": SCHEMA_VERSION,
        "description": description,
        "searched": searches,
        "fetched": fetches,
        "official_features": document["official_features"],
        "existing_tools": document["existing_tools"],
        "conventions": document["conventions"],
        "sources": document["sources"],
        "recommendation": document["recommendation"],
        "recommendation_reason": document["recommendation_reason"],
        "cost_usd": result.cost_usd,
    }
