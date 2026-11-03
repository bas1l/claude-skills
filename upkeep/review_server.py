"""The local server behind the review page's Send button. Python's standard library only.

    python review_server.py start  [--config C]             start one, or reuse the one running. Prints JSON
    python review_server.py static --reason T [--config C]  write the file form of the page, saying why Send is off
    python review_server.py serve  [--config C]             what ``start`` runs, detached

**It never applies anything.** It renders the page from the data on disk, checks each Send against
the current review, and writes a batch to a file the session reads. The only files it writes lie
under ``review/server``. It does not import ``review_session`` or ``memory_store``, and it calls
none of the review's writing functions. Tests hold it to that, and check the data folder after a Send.

The page shows untrusted text, and this is a new way in to the review's actions, so every request
must pass all of these, or it gets a bare refusal:

    the loopback address only, on a port the system chose
    exactly one Host header, naming that address and port, against DNS rebinding
    the run's random token as the first part of the path, compared in constant time
    a known path, with no query
    for a POST: exactly that Origin, Content-Type application/json, a Content-Length within the
    limit and no other framing, and, where the browser sends it, Sec-Fetch-Site same-origin

No response holds a CORS header. The only GET is the page itself. Nothing is logged of any request,
since a path holds the token.

It closes by itself on the first of these, with periods from ``review_server`` in ``config.json``:

    finished       the session's ``finish-server`` asked it to
    all_decided    every item is decided, and the page has been given every result
    page_gone      no heartbeat from the page for a period, with no batch waiting for the session
    idle_limit     no Send, no result and nothing done on the page for a longer period

A second start reuses a server that answers, and a stale one left by a crash is cleared first, so
that none stack up.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlsplit

import process_probe
import review_batch
import review_data
import review_page
from config import DEFAULT_CONFIG_PATH, Config, ReviewServerConfig, load_config

LOOPBACK = "127.0.0.1"
START_LOCK_FILE = "start.lock"
LOG_FILE = "server.log"
PROBE_TIMEOUT_SECONDS = 3
START_POLL_SECONDS = 0.1
EXIT_FAILED = 1
REASON_FINISHED = "finished"
REASON_ALL_DECIDED = "all_decided"
REASON_PAGE_GONE = "page_gone"
REASON_IDLE = "idle_limit"
REASON_FAULT = "fault"
CLOSING_TEXT = {
    REASON_FAULT: "The server hit a fault. Its log is review/server/server.log.",
    REASON_FINISHED: "The session finished.",
    REASON_ALL_DECIDED: "Every item is decided, and every result is on this page.",
    REASON_PAGE_GONE: "The page stopped answering for a while, with nothing waiting.",
    REASON_IDLE: "Nothing happened for a long time.",
}
_REFUSED = b'{"message": "Refused."}'
_JSON_TYPE = "application/json"
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_HTTP_OK = 200
_HTTP_BAD = 400
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_NOT_ALLOWED = 405
_HTTP_LENGTH_REQUIRED = 411
_HTTP_TOO_LARGE = 413
_HTTP_UNSUPPORTED = 415
_HTTP_SERVER_ERROR = 500
_HTTP_UNAVAILABLE = 503


@dataclass(frozen=True)
class ClosingFacts:
    """What closing depends on, at one moment, so that the decision can be tested without waiting."""

    stop_requested: bool
    has_items: bool
    all_decided: bool
    pending_batches: bool
    results_delivered: bool
    seconds_since_page: float
    seconds_since_activity: float


def closing_reason(facts: ClosingFacts, settings: ReviewServerConfig) -> Optional[str]:
    """Why the server should close now, if it should. Order matters only for the words shown."""
    if facts.stop_requested:
        return REASON_FINISHED
    if facts.has_items and facts.all_decided and not facts.pending_batches and facts.results_delivered:
        return REASON_ALL_DECIDED
    if facts.seconds_since_activity >= settings.idle_limit_seconds:
        return REASON_IDLE
    if not facts.pending_batches and facts.seconds_since_page >= settings.page_gone_seconds:
        return REASON_PAGE_GONE
    return None


def _signature_of(view: Any) -> str:
    return hashlib.sha256(json.dumps(view, sort_keys=True).encode("utf-8")).hexdigest()


class ServerState:
    """What the running server holds. Everything lasting is on disk."""

    def __init__(self, config: Config, token: str, clock: Callable[[], float] = time.monotonic):
        self.config = config
        self.token = token
        self.clock = clock
        self.port = 0
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.last_page = clock()
        self.last_activity = clock()
        self.delivered = ""
        self.closing: Optional[str] = None
        self._review_stamp: Optional[tuple[str, int, int]] = None
        self._review: Optional[dict[str, Any]] = None

    @property
    def data_dir(self) -> str:
        return self.config.paths.data_dir

    def current_review(self) -> dict[str, Any]:
        """The latest review, read again whenever its file has changed. A pass may build a new one
        while this runs, and the page must then be told."""
        data_dir = self.data_dir
        weeks = [week for week in review_data.week_folders(data_dir) if os.path.isfile(review_data.review_path(data_dir, week))]
        if not weeks:
            raise FileNotFoundError("no review yet")
        path = review_data.review_path(data_dir, weeks[-1])
        stat = os.stat(path)
        stamp = (path, stat.st_mtime_ns, stat.st_size)
        if stamp != self._review_stamp:
            self._review = review_data.load_review(data_dir, weeks[-1])
            self._review_stamp = stamp
        return self._review

    def touch_activity(self) -> None:
        with self.lock:
            self.last_activity = self.clock()

    def touch_page(self, active: bool) -> None:
        with self.lock:
            self.last_page = self.clock()
            if active:
                self.last_activity = self.last_page

    def results_signature(self) -> str:
        return _signature_of(review_batch.page_view(self.data_dir))

    def facts(self) -> ClosingFacts:
        review = self.current_review()
        view = review_batch.page_view(self.data_dir)
        signature = _signature_of(view)
        now = self.clock()
        return ClosingFacts(
            stop_requested=os.path.exists(review_batch.stop_request_path(self.data_dir)),
            has_items=bool(review["items"]),
            all_decided=all(item["decision"] is not None for item in review["items"]),
            pending_batches=any(not batch["done"] for batch in view),
            results_delivered=(not view) or self.delivered == signature,
            seconds_since_page=now - self.last_page,
            seconds_since_activity=now - self.last_activity,
        )


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows this option would let another process bind the same port while this one is up.
    allow_reuse_address = False
    state: ServerState

    def handle_error(self, request: Any, client_address: Any) -> None:
        """A client that goes away is nothing to report, and a traceback may quote a request."""


class _Handler(BaseHTTPRequestHandler):
    server_version = "upkeep-review"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    error_content_type = "application/json"
    error_message_format = '{"message": "Refused."}'

    def setup(self) -> None:
        self.timeout = self.server.state.config.review_server.request_timeout_seconds
        super().setup()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (the base class names it so)
        """Nothing is logged, because a request's path holds the token."""

    def _security_headers(self) -> None:
        self.send_header("Content-Security-Policy", review_page.content_security_policy(True, for_header=True))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")

    def _respond(self, status: int, body: bytes, content_type: str = _JSON_TYPE) -> None:
        self.close_connection = True
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, document: Mapping[str, Any]) -> None:
        self._respond(status, json.dumps(document, ensure_ascii=True).encode("ascii"))

    def _refuse(self, status: int) -> None:
        self._respond(status, _REFUSED)

    def send_error(self, code: int, message: Optional[str] = None, explain: Optional[str] = None) -> None:
        """The base class's own refusals, such as a broken request line, say no more than these do."""
        self._refuse(code)

    def _host_is_ours(self) -> bool:
        hosts = self.headers.get_all("Host") or []
        return len(hosts) == 1 and hosts[0] == f"{LOOPBACK}:{self.server.state.port}"

    def _route(self) -> Optional[str]:
        """What is asked for, if the token and the path are right. Nothing tells a wrong token from a wrong path."""
        if not self.path.startswith("/"):
            return None
        parts = urlsplit(self.path)
        if parts.query or parts.fragment or parts.netloc:
            return None
        pieces = parts.path.split("/")
        if len(pieces) != 3 or pieces[0] != "":
            return None
        if not hmac.compare_digest(pieces[1].encode("utf-8", "replace"), self.server.state.token.encode("ascii")):
            return None
        return pieces[2]

    def _gate(self) -> Optional[str]:
        """The route, or None once a refusal has been sent."""
        if not self._host_is_ours():
            self._refuse(_HTTP_FORBIDDEN)
            return None
        route = self._route()
        if route is None:
            self._refuse(_HTTP_NOT_FOUND)
        return route

    def _origin_is_ours(self) -> bool:
        origins = self.headers.get_all("Origin") or []
        if len(origins) != 1 or origins[0] != f"http://{LOOPBACK}:{self.server.state.port}":
            return False
        site = self.headers.get("Sec-Fetch-Site")
        return site is None or site == "same-origin"

    def _read_json_body(self) -> Optional[Any]:
        """The body of a POST as JSON, or None once a refusal has been sent."""
        limit = self.server.state.config.review_server.max_body_bytes
        if not self._origin_is_ours():
            self._refuse(_HTTP_FORBIDDEN)
            return None
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != _JSON_TYPE:
            self._refuse(_HTTP_UNSUPPORTED)
            return None
        if self.headers.get("Transfer-Encoding") is not None:
            self._refuse(_HTTP_LENGTH_REQUIRED)
            return None
        length_text = self.headers.get("Content-Length", "")
        if not length_text.isascii() or not length_text.isdigit():
            self._refuse(_HTTP_LENGTH_REQUIRED)
            return None
        length = int(length_text)
        if length > limit:
            self._refuse(_HTTP_TOO_LARGE)
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"), parse_constant=_no_constant)
        except (ValueError, OSError, RecursionError):
            self._refuse(_HTTP_BAD)
            return None

    def do_GET(self) -> None:  # noqa: N802 (the base class names it so)
        route = self._gate()
        if route is None:
            return
        if route != "":
            self._refuse(_HTTP_NOT_FOUND)
            return
        state = self.server.state
        try:
            page = review_data.render_review_page(state.data_dir, state.current_review(), _send_state(state.config.review_server))
        except Exception as error:  # noqa: BLE001 (nothing about a fault goes to the browser)
            print(f"The page could not be rendered: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            self._respond(_HTTP_SERVER_ERROR, b"The review could not be read. Typing in the session still works.", "text/plain")
            return
        state.touch_page(True)
        self._respond(_HTTP_OK, page.encode("utf-8"), "text/html")

    def do_POST(self) -> None:  # noqa: N802 (the base class names it so)
        route = self._gate()
        if route is None:
            return
        if route not in ("status", "send"):
            self._refuse(_HTTP_NOT_FOUND)
            return
        body = self._read_json_body()
        if body is None:
            return
        if route == "status":
            self._status(body)
        else:
            self._send(body)

    def _not_allowed(self) -> None:
        if self._gate() is not None:
            self._refuse(_HTTP_NOT_ALLOWED)

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _not_allowed  # noqa: N815

    def _status(self, body: Any) -> None:
        state = self.server.state
        if not isinstance(body, dict) or not set(body) <= {"active", "probe"}:
            self._refuse(_HTTP_BAD)
            return
        probe = body.get("probe") is True
        if not probe:
            state.touch_page(body.get("active") is True)
        view = review_batch.page_view(state.data_dir)
        if not probe:
            # Set before the reply goes: a page that loses this reply polls again within seconds.
            state.delivered = _signature_of(view)
        try:
            review_id = state.current_review()["review_id"]
        except (OSError, ValueError) as error:
            print(f"The review could not be read: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            review_id = ""
        self._json(_HTTP_OK, {
            "review_id": review_id,
            "closing": CLOSING_TEXT[state.closing] if state.closing else "",
            "batches": view,
        })

    def _send(self, body: Any) -> None:
        state = self.server.state
        if state.closing:
            self._json(_HTTP_UNAVAILABLE, {"message": "The server is closing. Nothing was sent."})
            return
        settings = state.config.review_server
        with state.send_lock:
            try:
                review = state.current_review()
                sorting = review_data.read_sort(state.data_dir, review["week"])[0]
                batch = review_batch.validated_batch(
                    body, review, sorting, review_batch.open_numbers(state.data_dir), settings.max_note_chars, settings.max_page_note_chars, datetime.now(timezone.utc),
                )
                review_batch.write_batch(state.data_dir, batch)
            except review_batch.BatchRefused as refusal:
                self._json(refusal.status, {"message": refusal.message, "reload": refusal.reload, "refused": refusal.refused})
                return
            except (OSError, ValueError) as error:
                print(f"A batch could not be written: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
                self._json(_HTTP_SERVER_ERROR, {"message": "The batch could not be written. Nothing was sent. Type your choices in the session."})
                return
        state.touch_activity()
        self._json(_HTTP_OK, {"batch_id": batch["batch_id"], "accepted": [item["number"] for item in batch["items"]], "refused": batch["refused"]})


def _no_constant(name: str) -> None:
    raise ValueError(f"{name} is not JSON")


def _send_state(settings: ReviewServerConfig) -> review_page.SendState:
    return review_page.SendState(
        True, "", int(settings.heartbeat_seconds * 1000), int(settings.send_poll_seconds * 1000), settings.max_note_chars, settings.max_page_note_chars,
    )


def bind_server(state: ServerState) -> _Server:
    """Bound to the loopback address on a port the system chooses. Nothing else is ever offered."""
    server = _Server((LOOPBACK, 0), _Handler)
    server.state = state
    state.port = server.server_address[1]
    return server


def _watch(state: ServerState, sleep: Callable[[float], None] = time.sleep) -> str:
    """Until something says to close. A fault reading the data keeps the server up, since the
    idle limit still applies, and that needs only the clock."""
    settings = state.config.review_server
    last_signature = ""
    while True:
        try:
            facts = state.facts()
            signature = state.results_signature()
            if signature != last_signature:
                last_signature = signature
                state.touch_activity()
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"The watch could not read the data: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            now = state.clock()
            facts = ClosingFacts(os.path.exists(review_batch.stop_request_path(state.data_dir)), False, False, True, False, now - state.last_page, now - state.last_activity)
        reason = closing_reason(facts, settings)
        if reason is not None:
            return reason
        sleep(settings.watchdog_seconds)


def run_server(config: Config, sleep: Callable[[float], None] = time.sleep) -> str:
    """Serve until something says to close, then leave nothing behind but the reason. Returns it."""
    data_dir = config.paths.data_dir
    token = secrets.token_urlsafe(config.review_server.token_bytes)
    state = ServerState(config, token)
    server = bind_server(state)
    os.makedirs(review_batch.server_dir(data_dir), exist_ok=True)
    for stale in (review_batch.stop_request_path(data_dir), review_batch.closed_path(data_dir)):
        if os.path.exists(stale):
            os.remove(stale)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    pid = os.getpid()
    review_batch.write_json_file(review_batch.server_info_path(data_dir), {
        "schema_version": review_batch.SERVER_INFO_SCHEMA_VERSION, "pid": pid, "process_identity": process_probe.identity_of(pid),
        "port": state.port, "token": token, "url": f"http://{LOOPBACK}:{state.port}/{token}/", "started_at": datetime.now(timezone.utc).isoformat(),
    })
    reason = REASON_FAULT
    try:
        reason = _watch(state, sleep)
        state.closing = reason
        sleep(config.review_server.close_grace_seconds)
    finally:
        server.shutdown()
        server.server_close()
        review_batch.write_json_file(review_batch.closed_path(data_dir), {"reason": reason, "text": CLOSING_TEXT[reason], "at": datetime.now(timezone.utc).isoformat()})
        for leftover in (review_batch.server_info_path(data_dir), review_batch.stop_request_path(data_dir)):
            if os.path.exists(leftover):
                os.remove(leftover)
    return reason


# ---- Starting one, from the launcher ----


def probe(info: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """What a running server answers, through its front door. None if it does not. Counts as no heartbeat."""
    connection = http.client.HTTPConnection(LOOPBACK, info["port"], timeout=PROBE_TIMEOUT_SECONDS)
    try:
        body = json.dumps({"probe": True})
        connection.request("POST", f"/{info['token']}/status", body, {"Origin": f"http://{LOOPBACK}:{info['port']}", "Content-Type": _JSON_TYPE})
        response = connection.getresponse()
        if response.status != _HTTP_OK:
            return None
        return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def _acquire_start_lock(data_dir: str, settings: ReviewServerConfig) -> str:
    """One start at a time, so that two quick clicks do not make two servers. A lock from a start
    that crashed is cleared by its age."""
    path = os.path.join(review_batch.server_dir(data_dir), START_LOCK_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.monotonic() + settings.start_timeout_seconds
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return path
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) >= settings.start_lock_stale_seconds:
                    os.remove(path)
                    continue
            except OSError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("another start of the review server did not finish") from None
            time.sleep(START_POLL_SECONDS)


def _clear_stale_server(data_dir: str, info: Mapping[str, Any]) -> dict[str, Any]:
    """A server that does not answer: end it if it is still the same process, and clear its record."""
    ended = process_probe.terminate(info["pid"], info["process_identity"])
    if os.path.exists(review_batch.server_info_path(data_dir)):
        os.remove(review_batch.server_info_path(data_dir))
    return {"stale_server_cleared": True, "stale_process_ended": ended}


def _spawn(config_path: str, data_dir: str) -> subprocess.Popen[bytes]:
    """The server, on its own: it outlives the launcher's window, and writes only faults to its log."""
    command = [sys.executable, os.path.abspath(__file__), "serve", "--config", config_path]
    log = open(os.path.join(review_batch.server_dir(data_dir), LOG_FILE), "ab")  # noqa: SIM115 (the child holds it)
    try:
        if os.name == "nt":
            base_flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
            try:
                return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=base_flags | _CREATE_BREAKAWAY_FROM_JOB, close_fds=True)
            except OSError:
                return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=base_flags, close_fds=True)
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True)
    finally:
        log.close()


def _wait_until_up(child: subprocess.Popen[bytes], data_dir: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"the server stopped at once, with exit code {child.returncode}")
        info = review_batch.read_server_info(data_dir)
        if info is not None and info["pid"] == child.pid and probe(info) is not None:
            return info
        time.sleep(START_POLL_SECONDS)
    child.terminate()
    raise TimeoutError(f"the server did not answer within {timeout_seconds} seconds")


def start_server(config: Config, config_path: str) -> dict[str, Any]:
    """Reuse the server that answers, or clear what is left and start one. Returns where it is."""
    data_dir = config.paths.data_dir
    settings = config.review_server
    lock = _acquire_start_lock(data_dir, settings)
    try:
        cleared: dict[str, Any] = {}
        info = review_batch.read_server_info(data_dir)
        if info is not None:
            answer = probe(info)
            if answer is not None and not answer["closing"]:
                return {"url": info["url"], "reused": True, "session_waiting": review_batch.waiter_is_running(data_dir)}
            if answer is not None:
                # It is on its way out: wait for that, and do not race it for the record.
                deadline = time.monotonic() + settings.close_grace_seconds + settings.stop_timeout_seconds
                while review_batch.server_is_running(data_dir) and time.monotonic() < deadline:
                    time.sleep(START_POLL_SECONDS)
            if review_batch.read_server_info(data_dir) is not None:
                cleared = _clear_stale_server(data_dir, info)
        review = review_data.latest_review(data_dir)
        removed = review_batch.clear_finished_and_stale(data_dir, review["review_id"])
        child = _spawn(config_path, data_dir)
        info = _wait_until_up(child, data_dir, settings.start_timeout_seconds)
        return {"url": info["url"], "reused": False, "session_waiting": review_batch.waiter_is_running(data_dir), "batches_cleared": removed, **cleared}
    finally:
        if os.path.exists(lock):
            os.remove(lock)


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("start", "static", "serve"))
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--reason", default="")
    arguments = parser.parse_args(argv)
    config_path = os.path.abspath(arguments.config)
    config = load_config(config_path)
    if arguments.action == "serve":
        print(json.dumps({"closed": run_server(config)}), flush=True)
        return 0
    if arguments.action == "static":
        review = review_data.latest_review(config.paths.data_dir)
        send = review_page.SendState(False, arguments.reason or review_page.NOT_SERVED_REASON)
        print(review_data.write_static_page(config.paths.data_dir, review, send))
        return 0
    try:
        result = start_server(config, config_path)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_FAILED
    json.dump(result, sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
