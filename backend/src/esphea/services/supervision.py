"""Run CPU-heavy work in a supervised child process.

Native libraries (e.g. Dionysus) may hold the GIL for minutes, which would
starve the heartbeat thread of the worker and make the watchdog believe the
worker died. The work therefore runs in a fresh process (``spawn``: no inherited
threads, locks or database connections) while the parent keeps the lease alive,
relays progress and terminates the child when asked to abort.
"""

import multiprocessing
import sys
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Protocol

type Progress = Callable[[int, int], None]

TERMINATE_GRACE_SECONDS = 5.0


class SupervisedTask(Protocol):
    """Picklable unit of work that reports progress."""

    def __call__(self, progress: Progress) -> None: ...


class SupervisedTaskError(RuntimeError):
    """The task raised an exception (message preserved) or the process died."""


class SupervisedTaskAbortedError(InterruptedError):
    """The supervisor terminated the task because ``should_abort`` became true."""


def _child_main(task: SupervisedTask, sender: Connection) -> None:
    try:
        task(lambda done, total: sender.send(("progress", done, total)))
    except BaseException as exc:
        sender.send(("error", f"{type(exc).__name__}: {exc}"))
        sender.close()
        sys.exit(1)
    sender.send(("done",))
    sender.close()


def _stop(process: multiprocessing.process.BaseProcess) -> None:
    if process.is_alive():
        process.terminate()
        process.join(TERMINATE_GRACE_SECONDS)
        if process.is_alive():
            process.kill()
            process.join()


def run_supervised(
    task: SupervisedTask,
    *,
    on_progress: Progress,
    should_abort: Callable[[], bool],
    poll_interval: float = 0.5,
) -> None:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child_main, args=(task, sender), daemon=True)
    process.start()
    sender.close()  # the parent only receives
    outcome: tuple[str, ...] | None = None  # ("done",) or ("error", message)
    try:
        while process.is_alive() or receiver.poll():
            if receiver.poll(poll_interval):
                try:
                    message = receiver.recv()
                except EOFError:  # the child closed its end and exited
                    break
                if message[0] == "progress":
                    on_progress(message[1], message[2])
                else:
                    outcome = message
            if should_abort():
                raise SupervisedTaskAbortedError("the task was aborted by its supervisor")
        process.join()
    finally:
        _stop(process)
        receiver.close()
    if outcome is None:
        raise SupervisedTaskError(
            f"the analysis process died unexpectedly (exit code {process.exitcode}); "
            "it may have run out of memory"
        )
    if outcome[0] == "error":
        raise SupervisedTaskError(outcome[1])
