"""Utilities for consistent progress reporting across CLI commands."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


def _is_tty(stream: object) -> bool:
    """Return True when the provided stream supports terminal features."""
    try:
        return bool(stream.isatty())  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive fallback
        return False


@dataclass(slots=True)
class _PlainTask:
    """Fallback task that prints throttled updates for non-interactive runs."""

    description: str
    total: int
    completed: int = 0
    ok: int | None = None
    fail: int | None = None
    _last_print: float = 0.0
    _interval: float = 1.5

    def advance(
        self,
        step: int,
        *,
        ok: int | None = None,
        fail: int | None = None,
    ) -> None:
        self.completed += step
        if ok is not None:
            self.ok = ok
        if fail is not None:
            self.fail = fail
        now = time.time()
        if self.completed == self.total or (now - self._last_print) >= self._interval:
            suffix: list[str] = []
            if self.ok is not None:
                suffix.append(f"✓{self.ok}")
            if self.fail is not None:
                suffix.append(f"✗{self.fail}")
            pieces = [
                f"[..] {self.description}: {self.completed}/{self.total}",
            ]
            if suffix:
                pieces.append(f"({' '.join(suffix)})")
            print(" ".join(pieces), file=sys.stderr, flush=True)
            self._last_print = now


@dataclass(slots=True)
class _NullTask:
    """Task placeholder when progress reporting is disabled."""

    def advance(
        self,
        step: int,
        *,
        ok: int | None = None,
        fail: int | None = None,
    ) -> None:
        """Ignore updates when the user opted out of progress output."""
        return


class ProgressManager:
    """Wrapper around Rich progress that gracefully degrades when needed."""

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode
        self._quiet = mode == "none"
        self.console: Console | None = None
        self._progress: Progress | None = None
        self._base_descriptions: dict[int, str] = {}

        use_rich = False
        if not self._quiet:
            if mode == "rich":
                use_rich = True
            elif mode == "auto":
                use_rich = _is_tty(sys.stderr)

        if use_rich:
            self.console = Console(stderr=True, force_terminal=(mode == "rich"))
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                transient=True,
                refresh_per_second=5,
                console=self.console,
            )

    @property
    def is_active(self) -> bool:
        """Return True when progress output is enabled in any form."""
        return not self._quiet

    @property
    def is_rich(self) -> bool:
        """Return True when Rich-based rendering is in use."""
        return self._progress is not None

    @contextmanager
    def live(self):
        """Context manager ensuring Rich progress renders correctly."""
        if self._progress is not None:
            with self._progress:
                yield self
        else:
            yield self

    def add_task(self, description: str, *, total: int) -> int | _PlainTask | _NullTask:
        """Register a new task with the requested total steps."""
        if self._quiet:
            return _NullTask()
        if self._progress is not None:
            task_id = self._progress.add_task(description, total=total)
            self._base_descriptions[task_id] = description
            return task_id
        return _PlainTask(description, total)

    def advance(
        self,
        task: int | _PlainTask | _NullTask | None,
        step: int = 1,
        *,
        ok: int | None = None,
        fail: int | None = None,
    ) -> None:
        """Advance the given task while keeping auxiliary counters in sync."""
        if task is None:
            return
        if isinstance(task, _NullTask):
            return
        if self._progress is not None:
            base = self._base_descriptions.get(int(task), "")
            suffix: list[str] = []
            if ok is not None:
                suffix.append(f"✓{ok}")
            if fail is not None:
                suffix.append(f"✗{fail}")
            description = base
            if suffix and base:
                description = f"{base}  [{' '.join(suffix)}]"
            elif suffix:
                description = "  ".join(suffix)
            self._progress.update(int(task), advance=step, description=description)
            return
        if isinstance(task, _PlainTask):
            task.advance(step, ok=ok, fail=fail)

    def log(self, message: str) -> None:
        """Write a log line without disrupting progress rendering."""
        if self.console is not None:
            self.console.log(message)
        else:
            print(message, file=sys.stderr, flush=True)
