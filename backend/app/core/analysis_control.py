"""Cancellation of the tools owned by one analysis, including media workers."""
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock


# Coordinates worker reservation with deletion of capture files.
task_lock = Lock()
active_tasks = {}


current = ContextVar('analysis_control', default=None)


class Cancelled(Exception):
    pass


class Control:
    def __init__(self):
        self.lock = Lock()
        self.cancelled = False
        self.processes = set()

    def cancel(self):
        with self.lock:
            self.cancelled = True
            for process in self.processes:
                if process.poll() is None:
                    process.kill()


def checkpoint():
    control = current.get()
    if control and control.cancelled:
        raise Cancelled()


@contextmanager
def track(process):
    control = current.get()
    try:
        if control:
            with control.lock:
                if control.cancelled:
                    process.kill()
                    raise Cancelled()
                control.processes.add(process)
        yield
        checkpoint()
    finally:
        if control:
            with control.lock:
                control.processes.discard(process)


def run(cmd, *, timeout, capture_output, **kwargs):
    """Like subprocess.run for this pipeline's captured, non-interactive commands."""
    if not current.get():
        return subprocess.run(cmd, timeout=timeout, capture_output=capture_output, **kwargs)
    checkpoint()
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs) as process:
        with track(process):
            try:
                out, err = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
        return subprocess.CompletedProcess(cmd, process.returncode, out, err)

