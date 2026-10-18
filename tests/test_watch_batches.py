import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from file_sorter import watcher
from file_sorter.config import Category, Config
from file_sorter.sorter import Moved, SortResult
from tests.conftest import make_files

CONFIG = Config(
    (Category("image", "Images", "pictures", "", frozenset({"jpg"})),),
)


class ScriptedTracker:
    """Подмена трекера: каждый вызов ready() отдаёт следующий список файлов.
    Когда список кончился, выставляет stop, и цикл слежения завершается.
    """

    def __init__(self, passes: list[list[Path]], stop: threading.Event) -> None:
        self._passes = passes
        self._stop = stop

    def ready(self) -> list[Path]:
        result = self._passes.pop(0)
        if not self._passes:
            self._stop.set()
        return result


def run_watch(
    source: Path,
    monkeypatch: pytest.MonkeyPatch,
    passes: list[list[Path]],
    *,
    on_result: Callable[[SortResult], None],
    on_batch: Callable[[list[SortResult]], None] | None = None,
) -> None:
    stop = threading.Event()
    monkeypatch.setattr(
        watcher, "SettleTracker", lambda settle: ScriptedTracker(passes, stop)
    )
    watcher.watch(
        source,
        CONFIG,
        lambda category: source / category.folder,
        stop=stop,
        poll_interval=0,
        on_result=on_result,
        on_batch=on_batch,
    )


def test_batch_is_one_pass_of_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_files(tmp_path, "a.jpg", "b.jpg", "c.jpg")
    batches: list[list[SortResult]] = []
    run_watch(
        tmp_path,
        monkeypatch,
        [[tmp_path / "a.jpg", tmp_path / "b.jpg"], [tmp_path / "c.jpg"]],
        on_result=lambda result: None,
        on_batch=batches.append,
    )
    assert [len(batch) for batch in batches] == [2, 1]
    assert all(isinstance(item, Moved) for batch in batches for item in batch)


def test_empty_pass_is_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_files(tmp_path, "a.jpg")
    batches: list[list[SortResult]] = []
    run_watch(
        tmp_path,
        monkeypatch,
        [[], [tmp_path / "a.jpg"]],
        on_result=lambda result: None,
        on_batch=batches.append,
    )
    assert [len(batch) for batch in batches] == [1]


def test_batch_is_reported_even_if_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_files(tmp_path, "a.jpg", "b.jpg")
    batches: list[list[SortResult]] = []
    seen: list[SortResult] = []

    def interrupt_on_second(result: SortResult) -> None:
        seen.append(result)
        if len(seen) == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_watch(
            tmp_path,
            monkeypatch,
            [[tmp_path / "a.jpg", tmp_path / "b.jpg"]],
            on_result=interrupt_on_second,
            on_batch=batches.append,
        )
    # оба файла уже перемещены, поэтому оба должны попасть в пачку
    assert [len(batch) for batch in batches] == [2]


def test_on_batch_is_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_files(tmp_path, "a.jpg")
    results: list[SortResult] = []
    run_watch(
        tmp_path,
        monkeypatch,
        [[tmp_path / "a.jpg"]],
        on_result=results.append,
    )
    assert len(results) == 1
    assert (tmp_path / "Images" / "a.jpg").exists()
