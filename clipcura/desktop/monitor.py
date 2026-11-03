"""Turns the job list into what the notification-area icon shows (batch progress, attention) and announces
(batch finished, an assistant waiting for approval). Pure logic, so it is tested without a desktop."""
from __future__ import annotations

from dataclasses import dataclass, field

ACTIVE = ("queued", "running")
FAILED = ("failed",)

TEXT = {
    "en": {
        "done_title": "Conversions finished",
        "done": "{done} done", "failed": "{failed} failed", "cancelled": "{cancelled} cancelled",
        "approval_title": "AI asks to convert {files}",
        "approval": "Open Clipcura to approve or reject.",
        "ready": "Clipcura - ready",
        "converting": "Clipcura - converting {files}, {percent} %",
        "paused": "Clipcura - queue paused, {files} waiting",
        "waiting": "Clipcura - {files} waiting for your approval",
    },
    "cs": {
        "done_title": "Převody dokončeny",
        "done": "hotovo {done}", "failed": "selhalo {failed}", "cancelled": "zrušeno {cancelled}",
        "approval_title": "AI žádá o převod {files}",
        "approval": "Schválíte nebo zamítnete v Clipcuře.",
        "ready": "Clipcura - připraveno",
        "converting": "Clipcura - převádí {files}, {percent} %",
        "paused": "Clipcura - fronta pozastavena, ve frontě {files}",
        "waiting": "Clipcura - ke schválení: {files}",
    },
}


def files(n: int, lang: str, genitive: bool = False) -> str:
    """'3 files' with the Czech form the sentence needs ("převod 3 souborů", "ve frontě 3 soubory")."""
    if lang == "cs":
        if genitive:
            return f"{n} souboru" if n == 1 else f"{n} souborů"
        return f"{n} soubor" if n == 1 else f"{n} soubory" if 2 <= n <= 4 else f"{n} souborů"
    return f"{n} file" if n == 1 else f"{n} files"


@dataclass
class Notice:
    kind: str       # batch_done | approval
    title: str
    message: str


@dataclass
class State:
    progress: float | None = None   # 0..1 over the current batch; None when idle (full logo)
    active: int = 0                  # queued + running
    total: int = 0                   # jobs in the current batch
    attention: bool = False          # something waits for a person's approval
    awaiting: int = 0


@dataclass
class BatchMonitor:
    lang: str = "en"
    paused: bool = False
    state: State = field(default_factory=State)
    _batch: dict[str, str] = field(default_factory=dict)        # job id -> last status
    _announced: set[str] = field(default_factory=set)            # approval requests already notified

    def _t(self, key: str, **values) -> str:
        return TEXT.get(self.lang, TEXT["en"])[key].format(**values)

    def update(self, jobs: list[dict]) -> list[Notice]:
        notices: list[Notice] = []
        by_id = {j["id"]: j for j in jobs}
        for j in jobs:
            if j["status"] in ACTIVE:
                self._batch[j["id"]] = j["status"]
        for jid in self._batch:
            if jid in by_id:
                self._batch[jid] = by_id[jid]["status"]

        active = [jid for jid, s in self._batch.items() if s in ACTIVE]
        if self._batch and not active:
            notices.append(self._batch_done())
            self._batch.clear()

        awaiting = [j for j in jobs if j["status"] == "awaiting_approval"]
        fresh = [j for j in awaiting if j.get("actor") == "ai" and j["id"] not in self._announced]
        if fresh:
            notices.append(Notice("approval", self._t("approval_title", files=files(len(fresh), self.lang, genitive=True)),
                                  self._t("approval")))
            self._announced |= {j["id"] for j in fresh}

        def percent(jid: str) -> float:
            j = by_id.get(jid)
            return 100.0 if j is None or j["status"] not in ACTIVE else float(j.get("progress") or 0)

        total = len(self._batch)
        self.state = State(
            progress=sum(percent(jid) for jid in self._batch) / (100 * total) if total else None,
            active=len(active) if total else 0, total=total, attention=bool(awaiting), awaiting=len(awaiting))
        return notices

    def _batch_done(self) -> Notice:
        counts = {"done": 0, "failed": 0, "cancelled": 0}
        for status in self._batch.values():
            key = "done" if status not in ("failed", "cancelled") else status
            counts[key] += 1
        parts = [self._t(k, **{k: n}) for k, n in counts.items() if n]
        return Notice("batch_done", self._t("done_title"), ", ".join(parts))

    def tooltip(self) -> str:
        s = self.state
        if s.active and self.paused:
            return self._t("paused", files=files(s.active, self.lang))
        if s.active:
            return self._t("converting", files=files(s.active, self.lang), percent=round((s.progress or 0) * 100))
        if s.awaiting:
            return self._t("waiting", files=files(s.awaiting, self.lang))
        return self._t("ready")
