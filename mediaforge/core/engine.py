"""Очередь задач конвертации: потоки, события, отмена."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import formats as fm
from .convert import Cancelled, ConvertError, convert_file
from .ffmpeg import MediaInfo, Tools, probe

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"


@dataclass
class Job:
    src: Path
    info: MediaInfo
    target: fm.Target
    out_dir: Path | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = STATUS_PENDING
    progress: float = 0.0
    speed: str = ""
    message: str = ""
    output: Path | None = None
    elapsed: float = 0.0
    # фрагмент принадлежит файлу, а не запуску: у каждого job свой
    trim_start: float = 0.0
    trim_end: float = 0.0
    # свой флаг: задача может быть снята с очереди, пока движок занят другими
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def name(self) -> str:
        return self.src.name


EventCB = Callable[[str, Job], None]


class _AnyCancel:
    """Событие-адаптер: «отменено», если взведён общий стоп или флаг задачи.

    convert_file/run_ffmpeg дёргают только `is_set()`, поэтому отдельный класс
    не нужен — достаточно того же интерфейса.
    """

    __slots__ = ("_events",)

    def __init__(self, *events: threading.Event) -> None:
        self._events = events

    def is_set(self) -> bool:
        return any(event.is_set() for event in self._events)


class Engine:
    """Пускает задачи параллельно (по умолчанию 2), не блокируя UI."""

    def __init__(
        self,
        tools: Tools,
        options: fm.ConvertOptions,
        on_event: EventCB,
        max_workers: int = 2,
    ):
        self.tools = tools
        self.options = options
        self.on_event = on_event
        self.max_workers = max(1, int(max_workers))
        self._cancel = threading.Event()
        self._pool: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()
        self._running = 0
        self._done_count = 0
        self._remaining = 0
        self._last_emit: dict[str, float] = {}
        # имена результатов, занятые задачами текущего запуска
        self._claimed: set[Path] = set()

    # ------------------------------------------------------------------ #
    @property
    def running(self) -> bool:
        with self._lock:
            return self._remaining > 0 or self._running > 0

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel

    def stop(self) -> None:
        self._cancel.set()

    def start(self, jobs: list[Job], default_out_dir: Path) -> None:
        if self.running:
            return
        self._cancel = threading.Event()
        self._done_count = 0
        self._remaining = len(jobs)
        self._last_emit.clear()
        self._claimed = set()          # новый запуск снова может перезаписывать
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers,
                                        thread_name_prefix="mediaforge")
        for job in jobs:
            job.status = STATUS_PENDING
            job.progress = 0.0
            job.message = ""
            job.speed = ""
            job.cancel.clear()
            self._pool.submit(self._run_one, job, default_out_dir)
        self._pool.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    def _run_one(self, job: Job, default_out_dir: Path) -> None:
        # Отмена могла случиться раньше, чем пул взял задачу: такой выход
        # обязан пройти через тот же finally, иначе _remaining не уменьшится
        # и движок навсегда останется в состоянии running.
        with self._lock:
            self._running += 1
            # отмена может прийти и общей командой «стоп», и снятием этой
            # задачи с очереди — второй случай помечает сам Job
            cancelled_before_start = self._cancel.is_set() or job.cancel.is_set()
        started = time.monotonic()

        def progress(p: float, speed: str) -> None:
            job.progress = p
            if speed:
                job.speed = speed
            now = time.monotonic()
            last = self._last_emit.get(job.id, 0.0)
            if p >= 1.0 or now - last > 0.08:
                self._last_emit[job.id] = now
                self._emit("progress", job)

        out_dir = job.out_dir or default_out_dir
        try:
            if cancelled_before_start:
                job.status = STATUS_CANCELLED
                job.message = "Отменено"
                self._emit("cancelled", job)
                return

            job.status = STATUS_RUNNING
            job.progress = 0.0
            self._emit("start", job)

            # opts копируются на задачу: trim из ConvertOptions — значение для
            # CLI/API, а в очереди у каждого файла свой фрагмент
            opts = self.options.copy(trim_start=job.trim_start,
                                     trim_end=job.trim_end)
            result = convert_file(
                job.src, job.target, opts, self.tools, out_dir,
                info=job.info, on_progress=progress,
                cancel=_AnyCancel(self._cancel, job.cancel),
                claimed=self._claimed,
            )
            job.output = result.output
            job.message = result.note
            job.progress = 1.0
            job.status = STATUS_DONE
            self._emit("done", job)
        except Cancelled:
            job.status = STATUS_CANCELLED
            job.message = "Отменено"
            self._emit("cancelled", job)
        except (ConvertError, OSError, ValueError) as exc:
            job.status = STATUS_ERROR
            job.message = str(exc)[:300]
            self._emit("error", job)
        except Exception as exc:  # noqa: BLE001 — не роняем пул из-за одного файла
            job.status = STATUS_ERROR
            job.message = f"{type(exc).__name__}: {exc}"[:300]
            self._emit("error", job)
        finally:
            job.elapsed = time.monotonic() - started
            with self._lock:
                self._running -= 1
                self._done_count += 1
                self._remaining -= 1
                finished = self._remaining == 0
            if finished:
                self._emit("finished", job)

    def _emit(self, event: str, job: Job) -> None:
        try:
            self.on_event(event, job)
        except Exception:  # noqa: BLE001 — колбэк UI не должен ломать конвертацию
            pass


def make_job(src: Path, target_key: str | None, tools: Tools) -> Job:
    info = probe(src, tools)
    key = target_key or fm.default_target(src.suffix, info.kind)
    target = fm.BY_KEY.get(key)
    if target is None:
        avail = fm.targets_for(info.kind)
        target = avail[0] if avail else fm.BY_KEY["mp4"]
    return Job(src=Path(src), info=info, target=target)
