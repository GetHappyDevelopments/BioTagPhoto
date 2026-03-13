from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable, Optional, Protocol

from PySide6.QtCore import QObject, QThread, Signal, Slot


class WorkerTask(Protocol):
    def __call__(self, ctx: "WorkerTaskContext") -> None:
        """Long-running task body."""


@dataclass(frozen=True)
class WorkerTaskContext:
    """
    Context passed to the task for progress/status reporting and cancellation checks.
    """

    is_cancelled: Callable[[], bool]
    report_progress: Callable[[int, int], None]
    report_status: Callable[[str], None]

    def check_cancelled(self) -> bool:
        return bool(self.is_cancelled())


class BackgroundWorker(QObject):
    """
    Generic QObject worker running in a QThread.

    Signals:
    - progress(current, total)
    - status(message)
    - finished()
    - error(message)
    """

    progress = Signal(int, int)
    status = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, task: WorkerTask, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._task: WorkerTask = task
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return bool(self._cancel_event.is_set())

    @Slot()
    def run(self) -> None:
        ctx = WorkerTaskContext(
            is_cancelled=self.is_cancelled,
            report_progress=self._emit_progress,
            report_status=self._emit_status,
        )
        try:
            self._task(ctx)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def _emit_progress(self, current: int, total: int) -> None:
        self.progress.emit(int(current), int(total))

    def _emit_status(self, message: str) -> None:
        self.status.emit(str(message))


class WorkerRunner(QObject):
    """
    Convenience wrapper that owns a worker + thread and wires lifecycle.
    """

    def __init__(self, task: WorkerTask, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.thread = QThread(parent)
        self.worker = BackgroundWorker(task=task)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

    def start(self) -> None:
        self.thread.start()

    def cancel(self) -> None:
        self.worker.cancel()

    def is_running(self) -> bool:
        return bool(self.thread.isRunning())

