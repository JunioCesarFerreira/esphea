import time

import pytest

from esphea.services.supervision import (
    Progress,
    SupervisedTaskAbortedError,
    SupervisedTaskError,
    run_supervised,
)


class Counting:
    def __call__(self, progress: Progress) -> None:
        for i in range(1, 4):
            progress(i, 3)


class Failing:
    def __call__(self, progress: Progress) -> None:
        raise ValueError("bad input")


class Sleeping:
    def __call__(self, progress: Progress) -> None:
        time.sleep(60)


class Dying:
    def __call__(self, progress: Progress) -> None:
        import os  # noqa: PLC0415

        os._exit(137)  # like the out-of-memory killer


def test_progress_is_relayed() -> None:
    seen: list[tuple[int, int]] = []
    run_supervised(
        Counting(), on_progress=lambda d, t: seen.append((d, t)), should_abort=lambda: False
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_child_errors_are_reported() -> None:
    with pytest.raises(SupervisedTaskError, match="ValueError: bad input"):
        run_supervised(Failing(), on_progress=lambda d, t: None, should_abort=lambda: False)


def test_a_dead_child_is_detected() -> None:
    with pytest.raises(SupervisedTaskError, match="exit code 137"):
        run_supervised(Dying(), on_progress=lambda d, t: None, should_abort=lambda: False)


def test_abort_terminates_the_child() -> None:
    started = time.monotonic()
    with pytest.raises(SupervisedTaskAbortedError):
        run_supervised(
            Sleeping(),
            on_progress=lambda d, t: None,
            should_abort=lambda: time.monotonic() - started > 1,
            poll_interval=0.1,
        )
    assert time.monotonic() - started < 15
