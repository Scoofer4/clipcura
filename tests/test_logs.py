"""Transparent log (#26): every process writes what it does from start to shutdown, secrets never reach the file,
and people (GUI) and assistants (API/MCP) read the same entries."""
import logging
import os
import threading

import pytest
from fastapi.testclient import TestClient

from clipcura.api.app import create_app
from clipcura.core import config, events, logs


@pytest.fixture
def logged():
    logs.reset()
    path = logs.setup("app")
    yield path
    logs.reset()


def lines(**filters):
    return logs.read(limit=200, **filters)


def test_start_is_logged_with_version_kind_and_data_folder(logged):
    assert logged.name == "app.log" and logged.parent.name == "logs"
    start = lines()[-1]
    assert start["process"] == "app" and start["level"] == "INFO"
    assert "started" in start["message"] and "source" in start["message"]


def test_secrets_never_reach_the_file(logged):
    key = config.load_config().token
    log = logging.getLogger("clipcura.test")
    log.warning("key %s, header Bearer %s, url http://x/#token=%s&a=1 and #code=abc123", key, key, key)
    text = logged.read_text(encoding="utf-8")
    assert key not in text and "abc123" not in text
    assert "Bearer ***" in text and "token=***" in text and "code=***" in text


def test_uncaught_exception_in_a_thread_is_logged_with_its_traceback(logged):
    def boom():
        raise RuntimeError("worker fell over")

    t = threading.Thread(target=boom, name="clipcura-test")
    t.start()
    t.join()
    entry = lines(level="error")[0]
    assert entry["level"] == "CRITICAL" and entry["thread"] == "clipcura-test"
    assert "worker fell over" in entry["exc"]


def test_failed_job_and_finished_scan_become_log_lines(logged):
    events.publish("scan.done", scan_id="s1", root="D:\\Footage", summary={"ok": 2, "fixable": 1}, actor="ai")
    events.publish("job.status", job_id="j1", status="failed", actor="human", source="D:\\Footage\\a.mp4",
                   output="", error="Conversion failed: Invalid data found", backend="cuda")
    failed = lines(level="error")[0]
    assert failed["source"] == "clipcura.jobs" and "a.mp4" in failed["message"] and "Invalid data" in failed["message"]
    scan = lines(text="D:\\Footage")[-1]
    assert scan["level"] == "INFO" and "ai" in scan["message"]


def test_read_filters_by_level_process_and_text_newest_first(logged):
    log = logging.getLogger("clipcura.test")
    log.info("first info")
    log.warning("a warning")
    log.error("an error")
    assert [e["message"] for e in lines(level="warning")][:2] == ["an error", "a warning"]
    assert lines(text="first info")[0]["message"] == "first info"
    assert lines(process="mcp") == []


def test_log_lines_are_streamed_to_the_gui_without_feedback_loops(logged):
    seen = []
    unsubscribe = events.subscribe(lambda e: seen.append(e) if e["type"] == "log" else None)
    try:
        logging.getLogger("clipcura.test").warning("live line")
    finally:
        unsubscribe()
    assert [e["entry"]["message"] for e in seen] == ["live line"]


def test_api_serves_the_log_to_people_and_assistants(logged):
    logging.getLogger("clipcura.test").error("something broke")
    with TestClient(create_app(), base_url="http://127.0.0.1") as api:
        api.headers["Authorization"] = f"Bearer {config.load_config().token}"
        for actor in ("human", "ai"):
            r = api.get("/api/logs", params={"level": "error"}, headers={"X-Clipcura-Actor": actor})
            assert r.status_code == 200
            assert r.json()["entries"][0]["message"] == "something broke"
        assert r.json()["folder"].endswith("logs")


def test_a_run_that_ended_without_shutdown_is_reported_at_the_next_start():
    # Owner, 2026-11-03: a crash must never take the log with it. The crashed run's lines stay in the file and
    # the next start says plainly that the previous run did not end normally.
    logs.reset()
    logs.setup("app")
    logging.getLogger("clipcura.test").info("last words before the crash")
    marker = logs.session_marker()
    logs.reset()                                   # no regular shutdown: like a crash or a forced end
    dead = marker.with_name("app-999999.json")
    marker.rename(dead)
    dead.write_text(dead.read_text(encoding="utf-8").replace(str(os.getpid()), "999999"), encoding="utf-8")

    logs.setup("app")
    report = lines(level="error")[0]
    assert "999999" in report["message"] and "did not end normally" in report["message"]
    assert lines(text="last words before the crash")       # the crashed run's log is still there
    assert not dead.exists()                                # reported once
    logs.reset()


def test_regular_shutdown_keeps_the_log_and_leaves_no_marker():
    logs.reset()
    path = logs.setup("app")
    marker = logs.session_marker()
    logs.stopped()
    assert not marker.exists()
    assert "Clipcura stopped" in path.read_text(encoding="utf-8")
    logs.reset()
    logs.setup("app")
    assert not lines(level="error")
    logs.reset()
