from __future__ import annotations

import pytest

from intraday_trader_air import progress_utils


def test_progress_manager_plain_mode_when_not_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(progress_utils, "_is_tty", lambda stream: False)
    manager = progress_utils.ProgressManager(mode="auto")

    assert manager.is_active
    assert not manager.is_rich

    with manager.live():
        task = manager.add_task("download dataset", total=1)
        manager.advance(task, ok=1)

    err = capsys.readouterr().err
    assert "download dataset" in err
    assert "✓1" in err


def test_progress_manager_respects_none_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    manager = progress_utils.ProgressManager(mode="none")

    assert not manager.is_active
    assert not manager.is_rich

    with manager.live():
        task = manager.add_task("ignored", total=3)
        manager.advance(task, ok=1)

    err = capsys.readouterr().err
    assert err == ""


@pytest.mark.skipif(
    not hasattr(progress_utils, "ProgressManager"),
    reason="rich dependency missing",
)
def test_progress_manager_rich_mode_updates_description() -> None:
    manager = progress_utils.ProgressManager(mode="rich")

    assert manager.is_active
    assert manager.is_rich

    with manager.live():
        task_id = manager.add_task("export", total=2)
        manager.advance(task_id, ok=1, fail=0)
        manager.advance(task_id, ok=1, fail=1)
        progress = manager._progress  # noqa: SLF001  # inspect internal state for verification
        assert progress is not None
        description = progress.tasks[int(task_id)].description
        assert "export" in description
        assert "✓1" in description
        assert "✗1" in description

