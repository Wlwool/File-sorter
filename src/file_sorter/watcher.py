"""Слежение за папкой: события watchdog, ожидание дописывания, сортировка."""

import os
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from file_sorter.config import Category, Config
from file_sorter.sorter import SortResult, sort_file

DEFAULT_SETTLE = 2.5  # секунд без изменений, после которых файл считается готовым


@dataclass(slots=True)
class _Entry:
    signature: (
        tuple[int, int] | None
    )  # (размер, время изменения) при последней проверке
    changed_at: float  # когда файл в последний раз менялся


class SettleTracker:
    """Помнит новые файлы и отдаёт те, что перестали меняться.
    Файл, который ещё копируется или скачивается, нельзя перемещать:
    он уедет недописанным. Поэтому файл считается готовым, когда его размер
    и время изменения не менялись settle секунд.
    """

    def __init__(
        self, settle: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._settle = settle
        self._clock = clock
        self._pending: dict[Path, _Entry] = {}
        # touch() вызывает поток watchdog, ready() - основной поток
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._pending)

    def touch(self, path: Path) -> None:
        """Отмечает событие с файлом: ожидание начинается заново."""
        with self._lock:
            self._pending[path] = _Entry(None, self._clock())

    def ready(self) -> list[Path]:
        """Файлы, готовые к сортировке. Каждый возвращается один раз."""
        now = self._clock()
        done: list[Path] = []
        with self._lock:
            for path, entry in list(self._pending.items()):
                try:
                    info = path.stat()
                except OSError:  # файл удалён или недоступен
                    del self._pending[path]
                    continue
                if not stat.S_ISREG(info.st_mode):
                    del self._pending[path]
                    continue
                signature = (info.st_size, info.st_mtime_ns)
                if signature != entry.signature:
                    entry.signature = signature
                    entry.changed_at = now
                elif now - entry.changed_at >= self._settle:
                    done.append(path)
                    del self._pending[path]
        return done


class WatchHandler(FileSystemEventHandler):
    """Передаёт трекеру файлы, которые появились в папке.
    Браузеры качают во временный файл и переименовывают его в итоговое имя.
    Для такого файла приходит только событие переименования, поэтому
    обрабатывается не только создание, но и новое имя при переименовании.
    """

    def __init__(self, tracker: SettleTracker) -> None:
        super().__init__()
        self._tracker = tracker

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._tracker.touch(Path(os.fsdecode(event.src_path)))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._tracker.touch(Path(os.fsdecode(event.dest_path)))


def watch(
    source: Path,
    config: Config,
    resolve: Callable[[Category], Path],
    *,
    on_result: Callable[[SortResult], None],
    stop: threading.Event,
    settle: float = DEFAULT_SETTLE,
    dry_run: bool = False,
    poll_interval: float = 0.5,
    started: threading.Event | None = None,
    on_batch: Callable[[list[SortResult]], None] | None = None,
) -> None:
    """Следит за папкой, пока не выставлен stop или не прервано с клавиатуры.
    Сортирует только файлы, появившиеся после запуска. Вложенные папки
    не отслеживаются. started выставляется, когда слежение уже работает.
    on_batch получает результаты одного прохода цикла (файлы, которые
    созрели вместе). Вызывается и при прерывании, чтобы уже перемещённые
    файлы не потерялись. Пустые проходы не передаются.
    """
    if not source.is_dir():
        raise NotADirectoryError(f"папка не найдена: {source}")

    tracker = SettleTracker(settle)
    observer = Observer()
    observer.schedule(WatchHandler(tracker), str(source), recursive=False)
    observer.start()
    try:
        if started is not None:
            started.set()
        while not stop.is_set():
            batch: list[SortResult] = []
            try:
                for path in tracker.ready():
                    result = sort_file(path, config, resolve, dry_run=dry_run)
                    batch.append(result)
                    on_result(result)
            finally:
                if batch and on_batch is not None:
                    on_batch(batch)
            stop.wait(poll_interval)
    finally:
        observer.stop()
        observer.join()
