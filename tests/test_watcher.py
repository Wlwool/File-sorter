import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path

import pytest
from watchdog.events import (
    DirCreatedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileMovedEvent,
)

from file_sorter.config import load_config
from file_sorter.sorter import Mode, SortResult, resolve_destination
from file_sorter.watcher import SettleTracker, WatchHandler, watch
from tests.conftest import make_files


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class TestSettleTracker:
    def make(self, settle: float = 2.0) -> tuple[SettleTracker, FakeClock]:
        clock = FakeClock()
        return SettleTracker(settle, clock), clock

    def test_file_becomes_ready_after_settle_time(self, tmp_path: Path) -> None:
        make_files(tmp_path, "a.jpg")
        tracker, clock = self.make()
        tracker.touch(tmp_path / "a.jpg")
        assert tracker.ready() == []
        clock.now = 1.9
        assert tracker.ready() == []
        clock.now = 2.0
        assert tracker.ready() == [tmp_path / "a.jpg"]

    def test_ready_file_is_returned_once(self, tmp_path: Path) -> None:
        make_files(tmp_path, "a.jpg")
        tracker, clock = self.make(settle=0)
        tracker.touch(tmp_path / "a.jpg")
        tracker.ready()
        assert tracker.ready() == [tmp_path / "a.jpg"]
        assert tracker.ready() == []
        assert len(tracker) == 0

    def test_growing_file_restarts_the_wait(self, tmp_path: Path) -> None:
        path = tmp_path / "a.jpg"
        make_files(tmp_path, "a.jpg")
        tracker, clock = self.make()
        tracker.touch(path)
        tracker.ready()
        clock.now = 1.5
        path.write_text("a longer content than before", encoding="utf-8")
        assert tracker.ready() == []
        clock.now = 3.4
        assert tracker.ready() == []
        clock.now = 3.5
        assert tracker.ready() == [path]

    def test_changed_size_restarts_the_wait_even_if_mtime_is_same(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "a.jpg"
        make_files(tmp_path, "a.jpg")
        tracker, clock = self.make()
        tracker.touch(path)
        tracker.ready()
        clock.now = 1.5
        before = path.stat()
        path.write_text("a longer content than before", encoding="utf-8")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert path.stat().st_size != before.st_size
        assert tracker.ready() == []
        clock.now = 3.4
        assert tracker.ready() == []
        clock.now = 3.5
        assert tracker.ready() == [path]

    def test_changed_mtime_restarts_the_wait(self, tmp_path: Path) -> None:
        path = tmp_path / "a.jpg"
        make_files(tmp_path, "a.jpg")
        tracker, clock = self.make()
        tracker.touch(path)
        tracker.ready()
        clock.now = 1.5
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        assert tracker.ready() == []
        clock.now = 3.4
        assert tracker.ready() == []
        clock.now = 3.5
        assert tracker.ready() == [path]

    def test_new_event_restarts_the_wait(self, tmp_path: Path) -> None:
        path = tmp_path / "a.jpg"
        make_files(tmp_path, "a.jpg")
        tracker, clock = self.make()
        tracker.touch(path)
        tracker.ready()
        clock.now = 1.5
        tracker.touch(path)
        tracker.ready()
        clock.now = 2.0
        assert tracker.ready() == []
        clock.now = 3.5
        assert tracker.ready() == [path]

    def test_touching_twice_tracks_one_file(self, tmp_path: Path) -> None:
        make_files(tmp_path, "a.jpg")
        tracker, _ = self.make()
        tracker.touch(tmp_path / "a.jpg")
        tracker.touch(tmp_path / "a.jpg")
        assert len(tracker) == 1

    def test_deleted_file_is_dropped(self, tmp_path: Path) -> None:
        path = tmp_path / "a.jpg"
        make_files(tmp_path, "a.jpg")
        tracker, clock = self.make(settle=0)
        tracker.touch(path)
        path.unlink()
        assert tracker.ready() == []
        assert len(tracker) == 0

    def test_directory_is_dropped(self, tmp_path: Path) -> None:
        (tmp_path / "folder").mkdir()
        tracker, _ = self.make(settle=0)
        tracker.touch(tmp_path / "folder")
        assert tracker.ready() == []
        assert len(tracker) == 0


class TestWatchHandler:
    def make(self) -> tuple[WatchHandler, SettleTracker]:
        tracker = SettleTracker(0, FakeClock())
        return WatchHandler(tracker), tracker

    def test_created_file_is_tracked(self, tmp_path: Path) -> None:
        make_files(tmp_path, "a.jpg")
        handler, tracker = self.make()
        handler.on_created(FileCreatedEvent(str(tmp_path / "a.jpg")))
        assert len(tracker) == 1

    def test_moved_file_is_tracked_by_new_name(self, tmp_path: Path) -> None:
        make_files(tmp_path, "report.pdf")
        handler, tracker = self.make()
        handler.on_moved(
            FileMovedEvent(
                str(tmp_path / "Unconfirmed.crdownload"), str(tmp_path / "report.pdf")
            )
        )
        assert len(tracker) == 1
        tracker.ready()
        assert tracker.ready() == [tmp_path / "report.pdf"]

    def test_directory_events_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "folder").mkdir()
        handler, tracker = self.make()
        handler.on_created(DirCreatedEvent(str(tmp_path / "folder")))
        handler.on_moved(DirMovedEvent(str(tmp_path / "x"), str(tmp_path / "folder")))
        assert len(tracker) == 0


def wait_until(condition: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


@contextmanager
def running_watcher(folder: Path, settle: float = 0.2) -> Iterator[list[SortResult]]:
    """Запускает настоящее слежение (watchdog) в потоке; режим subfolders."""
    results: list[SortResult] = []
    stop = threading.Event()
    started = threading.Event()
    resolve = partial(
        resolve_destination,
        mode=Mode.SUBFOLDERS,
        source=folder,
        target=None,
        system_dirs={},
    )
    thread = threading.Thread(
        target=watch,
        args=(folder, load_config(), resolve),
        kwargs={
            "settle": settle,
            "on_result": results.append,
            "stop": stop,
            "started": started,
            "poll_interval": 0.05,
        },
    )
    thread.start()
    try:
        assert started.wait(10), "слежение не запустилось"
        yield results
    finally:
        stop.set()
        thread.join(10)
        assert not thread.is_alive(), "поток слежения не остановился"


class TestWatch:
    def test_missing_folder_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NotADirectoryError):
            watch(
                tmp_path / "nope",
                load_config(),
                lambda category: tmp_path,
                on_result=lambda result: None,
                stop=threading.Event(),
            )

    def test_new_file_is_sorted(self, tmp_path: Path) -> None:
        with running_watcher(tmp_path):
            make_files(tmp_path, "a.jpg")
            assert wait_until(lambda: (tmp_path / "Images" / "a.jpg").exists())
        assert not (tmp_path / "a.jpg").exists()

    def test_existing_files_are_not_touched(self, tmp_path: Path) -> None:
        make_files(tmp_path, "old.jpg")
        with running_watcher(tmp_path):
            make_files(tmp_path, "new.mp3")
            assert wait_until(lambda: (tmp_path / "Audio" / "new.mp3").exists())
        assert (tmp_path / "old.jpg").exists()

    def test_browser_style_download_is_sorted_after_rename(
        self, tmp_path: Path
    ) -> None:
        with running_watcher(tmp_path):
            make_files(tmp_path, "Unconfirmed.crdownload", "other.crdownload")
            os.rename(tmp_path / "Unconfirmed.crdownload", tmp_path / "report.pdf")
            assert wait_until(lambda: (tmp_path / "Documents" / "report.pdf").exists())
        assert (tmp_path / "other.crdownload").exists()

    def test_growing_file_is_not_moved_until_finished(self, tmp_path: Path) -> None:
        chunks = 8
        path = tmp_path / "big.jpg"
        with running_watcher(tmp_path, settle=1.0):
            with path.open("wb") as handle:
                for _ in range(chunks):
                    handle.write(b"x" * 1000)
                    handle.flush()
                    time.sleep(0.1)
                    assert path.exists(), "файл убрали, пока он ещё пишется"
            assert wait_until(lambda: (tmp_path / "Images" / "big.jpg").exists())
        assert (tmp_path / "Images" / "big.jpg").stat().st_size == chunks * 1000
