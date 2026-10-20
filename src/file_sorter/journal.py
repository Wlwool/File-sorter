"""Журнал перемещений: что куда переехало, чтобы это можно было отменить.
Формат - JSON Lines: одна строка на один запуск (clean или пачка файлов watch).
"""

import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import platformdirs

from file_sorter.config import APP_NAME
from file_sorter.sorter import Moved

MAX_RUNS = 50  # сколько последних запусков хранится; старые удаляются сами
JOURNAL_NAME = "journal.jsonl"


@dataclass(frozen=True, slots=True)
class Entry:
    """Одно перемещение. size и mtime_ns нужны, чтобы понять, менялся ли файл."""

    original: Path
    current: Path
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class Run:
    """Один запуск: время (ISO 8601 с часовым поясом) и его перемещения."""

    time: str
    entries: tuple[Entry, ...]


def journal_path() -> Path:
    """Где лежит журнал (файл может не существовать)."""
    state_dir = platformdirs.user_state_dir(APP_NAME, appauthor=False)
    return Path(state_dir) / JOURNAL_NAME


def _encode(run: Run) -> str:
    return json.dumps(
        {
            "time": run.time,
            "entries": [
                {
                    "original": str(entry.original),
                    "current": str(entry.current),
                    "size": entry.size,
                    "mtime_ns": entry.mtime_ns,
                }
                for entry in run.entries
            ],
        }
    )


def _decode(line: str) -> Run | None:
    """Строка журнала в запуск; None, если строка испорчена или не той формы."""
    try:
        data = json.loads(line)
        entries = tuple(
            Entry(
                original=Path(item["original"]),
                current=Path(item["current"]),
                size=int(item["size"]),
                mtime_ns=int(item["mtime_ns"]),
            )
            for item in data["entries"]
        )
        return Run(time=str(data["time"]), entries=entries)
    except ValueError, TypeError, KeyError:
        return None


def load_runs() -> list[Run]:
    """Все запуски от старых к новым. Нет файла - пустой список."""
    try:
        text = journal_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    runs = (_decode(line) for line in text.splitlines() if line.strip())
    return [run for run in runs if run is not None]


def _write_runs(runs: Iterable[Run]) -> None:
    """Пишет журнал целиком через временный файл: сбой не оставит половину."""
    path = journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{_encode(run)}\n" for run in runs)
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def append_run(entries: Iterable[Entry]) -> None:
    """Добавляет запуск; лишние старые запуски (сверх MAX_RUNS) удаляются."""
    items = tuple(entries)
    if not items:
        return
    stamp = datetime.now(UTC).isoformat()
    runs = [*load_runs(), Run(stamp, items)]
    _write_runs(runs[-MAX_RUNS:])


def record_moves(moves: Iterable[Moved]) -> None:
    """Записывает перемещённые файлы как один запуск.
    Пути сохраняются полными: undo может запускаться из другой папки.
    Размер и время изменения берутся у файла на новом месте. Файл, который
    уже исчез, пропускается. Если не осталось ни одного, журнал не меняется.
    """
    entries: list[Entry] = []
    for move in moves:
        try:
            info = move.destination.stat()
        except OSError:
            continue
        entries.append(
            Entry(
                move.source.absolute(),
                move.destination.absolute(),
                info.st_size,
                info.st_mtime_ns,
            )
        )
    append_run(entries)


def pop_run(number: int) -> Run | None:
    """Достаёт запуск по номеру и убирает его из журнала.
    Номер считается от конца: 1 - последний, 2 - предыдущий и так далее.
    None, если такого номера нет (журнал при этом не меняется).
    """
    runs = load_runs()
    if not 1 <= number <= len(runs):
        return None
    index = len(runs) - number
    run = runs[index]
    _write_runs(runs[:index] + runs[index + 1 :])
    return run


def pop_last_run() -> Run | None:
    """Достаёт последний запуск и убирает его из журнала. None, если пусто."""
    return pop_run(1)
