"""Queue Manager: fila de trabalhos com um worker (processamento em lote, cancelamento seguro).

Um só trabalho de IA de cada vez: em máquinas modestas dois modelos em paralelo
esgotam RAM/VRAM e ficam mais lentos do que em série.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import asdict
from typing import Callable

from .chunking import Cancelled
from .config import UserError, get_logger
from .models.registry import Registry
from .pipeline import JobRequest, run

log = get_logger("stems4u.jobs")


class Job:
    def __init__(self, req: JobRequest):
        self.id = uuid.uuid4().hex[:12]
        self.req = req
        self.status = "queued"
        self.events: list[dict] = []
        self.result = None
        self.error: dict | None = None
        self.cancel_flag = threading.Event()
        self.created = time.time()

    def snapshot(self) -> dict:
        last = self.events[-1] if self.events else {}
        return {"id": self.id, "status": self.status, "input": self.req.input, "request": asdict(self.req),
                "last": last, "error": self.error,
                "result": {"outdir": self.result.outdir, "tracks": self.result.tracks,
                           "report": self.result.report} if self.result else None}


class JobManager:
    def __init__(self, registry: Registry | None = None, separator_factory: Callable | None = None):
        self.registry = registry or Registry()
        self.factory = separator_factory
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []
        self.cv = threading.Condition()
        self.worker = threading.Thread(target=self._loop, daemon=True, name="s4u-worker")
        self.worker.start()

    def submit(self, req: JobRequest) -> Job:
        job = Job(req)
        with self.cv:
            self.jobs[job.id] = job
            self.order.append(job.id)
            job.events.append({"stage": "queued", "progress": 0, "message": "Em fila"})
            self.cv.notify_all()
        return job

    def cancel(self, job_id: str) -> None:
        job = self.jobs[job_id]
        job.cancel_flag.set()
        with self.cv:
            if job.status == "queued":
                job.status = "cancelled"
                job.events.append({"stage": "cancelled", "progress": 0, "message": "Cancelado"})
            self.cv.notify_all()

    def list(self) -> list[dict]:
        return [self.jobs[i].snapshot() | {"result": None} for i in self.order]

    def wait_events(self, job_id: str, since: int, timeout: float = 15.0) -> tuple[list[dict], str]:
        job = self.jobs[job_id]
        with self.cv:
            if len(job.events) <= since and job.status in ("queued", "processing"):
                self.cv.wait(timeout)
            return job.events[since:], job.status

    def _next(self) -> Job | None:
        for i in self.order:
            if self.jobs[i].status == "queued":
                return self.jobs[i]
        return None

    def _loop(self):
        while True:
            with self.cv:
                job = self._next()
                while job is None:
                    self.cv.wait()
                    job = self._next()
                job.status = "processing"
                self.cv.notify_all()

            def emit(e, job=job):
                with self.cv:
                    job.events.append(e)
                    self.cv.notify_all()

            try:
                job.result = run(job.req, self.registry, emit, job.cancel_flag.is_set, self.factory)
                status = "completed"
            except Cancelled:
                status = "cancelled"
                emit({"stage": "cancelled", "progress": 0, "message": "Cancelado pelo utilizador"})
            except UserError as exc:
                log.warning("Job %s falhou: %s", job.id, exc.message)
                job.error = exc.to_dict()
                status = "failed"
                emit({"stage": "failed", "progress": 0, "message": exc.message, "hint": exc.hint})
            except Exception as exc:  # noqa: BLE001
                log.error("Job %s erro interno:\n%s", job.id, traceback.format_exc())
                job.error = {"code": "internal", "message": "Erro interno durante o processamento.",
                             "hint": f"{type(exc).__name__}: {exc}. Detalhe no ficheiro de log."}
                status = "failed"
                emit({"stage": "failed", "progress": 0, "message": job.error["message"], "hint": job.error["hint"]})
            with self.cv:
                job.status = status
                self.cv.notify_all()
