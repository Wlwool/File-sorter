"""Отмена сортировки: возвращает файлы запуска из журнала на прежние места."""

import shutil
import stat
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from file_sorter.journal import Entry, Run
from file_sorter.sorter import unique_destination


class UndoSkipReason(StrEnum):
    MISSING = "missing"  # файла нет там, куда его положила сортировка
    CHANGED = "changed"  # размер или время изменения не совпадают с журналом


class Restored(NamedTuple):
    entry: Entry
    destination: Path  # куда файл вернулся (имя может отличаться от исходного)

    @property
    def renamed(self) -> bool:
        return self.destination != self.entry.original


class UndoSkipped(NamedTuple):
    entry: Entry
    reason: UndoSkipReason


class UndoFailed(NamedTuple):
    entry: Entry
    message: str


@dataclass(slots=True)
class UndoReport:
    restored: list[Restored] = field(default_factory=list)
    skipped: list[UndoSkipped] = field(default_factory=list)
    failed: list[UndoFailed] = field(default_factory=list)


type UndoResult = Restored | UndoSkipped | UndoFailed


def _restore(entry: Entry) -> UndoResult:
    """Возвращает один файл. Изменённый или пропавший файл не трогает."""
    try:
        info = entry.current.stat()
    except FileNotFoundError, NotADirectoryError:
        return UndoSkipped(entry, UndoSkipReason.MISSING)
    except OSError as error:
        return UndoFailed(entry, str(error))
    unchanged = (info.st_size, info.st_mtime_ns) == (entry.size, entry.mtime_ns)
    if not stat.S_ISREG(info.st_mode) or not unchanged:
        return UndoSkipped(entry, UndoSkipReason.CHANGED)

    try:
        entry.original.parent.mkdir(parents=True, exist_ok=True)
        destination = unique_destination(entry.original.parent, entry.original.name)
        shutil.move(entry.current, destination)
    except OSError as error:
        return UndoFailed(entry, str(error))
    return Restored(entry, destination)


def undo_run(run: Run) -> UndoReport:
    """Возвращает файлы запуска. Занятое исходное имя получает счётчик: a_1.jpg."""
    report = UndoReport()
    for entry in run.entries:
        result = _restore(entry)
        match result:
            case Restored():
                report.restored.append(result)
            case UndoSkipped():
                report.skipped.append(result)
            case UndoFailed():
                report.failed.append(result)
    return report
