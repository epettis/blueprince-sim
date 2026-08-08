"""The trainer must survive a dashboard holding its checkpoint files open.

On Windows ``os.replace`` fails with PermissionError (WinError 5) when another
process has the DESTINATION open for reading, which is exactly what the
Observatory does when it polls ``latest.json``. This killed a training run
outright twice during progress-tab smoke testing, so the recovery is worth
pinning rather than trusting to review.
"""

from __future__ import annotations

import threading
import time

from blueprince_sim.rl.train import atomic_replace


def test_atomic_replace_succeeds_when_nothing_holds_the_destination(tmp_path):
    """The ordinary path still renames, so the retry wrapper is transparent."""
    tmp = tmp_path / ".tmp_latest.json"
    final = tmp_path / "latest.json"
    tmp.write_text('{"episodes": 1}')

    assert atomic_replace(tmp, final) is True
    assert final.read_text() == '{"episodes": 1}'
    assert not tmp.exists()


def test_atomic_replace_reports_failure_instead_of_raising(tmp_path, monkeypatch):
    """A destination that never frees up returns False rather than propagating.

    The caller decides what a failure costs -- losing one dashboard sample is
    cheap, losing a multi-hour run to an uncaught PermissionError is not.
    """
    tmp = tmp_path / ".tmp_latest.json"
    final = tmp_path / "latest.json"
    tmp.write_text("{}")

    def always_busy(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr("os.replace", always_busy)
    assert atomic_replace(tmp, final, attempts=3, delay_s=0.001) is False


def test_atomic_replace_retries_until_the_reader_lets_go(tmp_path, monkeypatch):
    """A destination busy for the first few attempts still lands on a later one.

    This is the real-world shape: the reader holds the file for microseconds, so
    a transient collision must not be treated as a permanent failure.
    """
    tmp = tmp_path / ".tmp_latest.json"
    final = tmp_path / "latest.json"
    tmp.write_text('{"episodes": 7}')

    real_replace = __import__("os").replace
    calls = {"n": 0}

    def busy_twice(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr("os.replace", busy_twice)
    assert atomic_replace(tmp, final, attempts=8, delay_s=0.001) is True
    assert calls["n"] == 3
    assert final.read_text() == '{"episodes": 7}'


def test_concurrent_poller_does_not_break_the_writer(tmp_path):
    """A thread POLLING the destination cannot stop the writer from landing.

    Reproduces the real trainer/Observatory contention rather than simulating
    it: on POSIX this passes trivially (renaming over an open file is legal),
    and on Windows it exercises the retry path the crash reports came from.

    The reader sleeps between reads, as the Observatory does (--metrics-poll,
    seconds). That gap is load-bearing, not decoration: a reader that reopens
    the file with no pause at all starves the writer, and no finite retry budget
    can win against it. Retries fix transient collisions, NOT sustained
    contention -- so the test models the contention that actually exists.
    """
    final = tmp_path / "latest.json"
    final.write_text('{"episodes": 0}')
    stop = threading.Event()
    read_errors: list[Exception] = []

    def poll():
        while not stop.is_set():
            try:
                final.read_text()
            except (FileNotFoundError, PermissionError):
                pass  # the server tolerates both; see web/server.py
            except Exception as exc:  # noqa: BLE001 - surfaced by the assert below
                read_errors.append(exc)
            time.sleep(0.002)

    reader = threading.Thread(target=poll, daemon=True)
    reader.start()
    try:
        for i in range(1, 26):
            tmp = tmp_path / ".tmp_latest.json"
            tmp.write_text(f'{{"episodes": {i}}}')
            assert atomic_replace(tmp, final), f"write {i} never landed"
    finally:
        stop.set()
        reader.join(timeout=5)

    assert not read_errors, f"reader saw unexpected errors: {read_errors}"
    assert final.read_text() == '{"episodes": 25}'
