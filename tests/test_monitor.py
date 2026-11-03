"""What the notification-area icon shows and announces, derived from the job list (#9)."""
from clipcura.desktop.monitor import BatchMonitor


def job(jid, status, progress=0.0, actor="human"):
    return {"id": jid, "status": status, "progress": progress, "actor": actor}


def test_progress_covers_the_whole_batch_and_a_notice_ends_it():
    m = BatchMonitor(lang="en")
    assert m.update([job("a", "running", 50), job("b", "queued")]) == []
    assert m.state.progress == 0.25 and m.state.active == 2 and m.state.total == 2

    m.update([job("a", "done", 100), job("b", "running", 50)])
    assert m.state.progress == 0.75

    (notice,) = m.update([job("a", "done", 100), job("b", "failed", 10)])
    assert notice.kind == "batch_done"
    assert notice.title == "Conversions finished" and notice.message == "1 done, 1 failed"
    assert m.state.progress is None and m.state.total == 0  # idle again: the full logo


def test_jobs_finished_before_the_app_started_are_not_announced():
    m = BatchMonitor(lang="en")
    assert m.update([job("old", "done", 100)]) == []
    assert m.state.progress is None


def test_ai_requests_waiting_for_approval_are_announced_once_and_flag_the_icon():
    m = BatchMonitor(lang="cs")
    jobs = [job("a", "awaiting_approval", actor="ai"), job("b", "awaiting_approval", actor="ai")]
    (notice,) = m.update(jobs)
    assert notice.kind == "approval" and notice.title == "AI žádá o převod 2 souborů"
    assert m.state.attention
    assert m.update(jobs) == []  # same requests: no second notification
    m.update([job("a", "queued", actor="ai"), job("b", "rejected", actor="ai")])
    assert not m.state.attention


def test_tooltip_says_what_is_happening():
    m = BatchMonitor(lang="en")
    assert m.tooltip() == "Clipcura - ready"
    m.update([job("a", "running", 40), job("b", "queued"), job("c", "done", 100)])
    assert m.tooltip() == "Clipcura - converting 2 files, 20 %"
    m.paused = True
    assert m.tooltip() == "Clipcura - queue paused, 2 files waiting"
