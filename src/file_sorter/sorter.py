"""Перемещение файлов по категориям."""

import errno
import shutil
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from file_sorter.config import Category, Config

BUSY_ATTEMPTS = 5  # сколько раз пробовать переместить занятый файл
BUSY_DELAY = 1.0  # пауза между попытками, секунд
_WINDOWS_BUSY = (32, 33)  # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
BUSY_MESSAGE = "файл занят другой программой: закройте её и повторите"


class Mode(StrEnum):
    SYSTEM = "system"  # в системные папки (Изображения, Музыка, ...)
    SUBFOLDERS = "subfolders"  # в подпапки внутри сортируемой папки
    CUSTOM = "custom"  # в подпапки внутри указанной папки


class SkipReason(StrEnum):
    UNKNOWN_TYPE = "unknown_type"
    ALREADY_IN_PLACE = "already_in_place"


class Moved(NamedTuple):
    source: Path
    destination: Path
    category: str


class Skipped(NamedTuple):
    path: Path
    reason: SkipReason


class Failed(NamedTuple):
    path: Path
    message: str
    busy: bool = False  # файл занят другой программой, есть смысл повторить


@dataclass(slots=True)
class SortReport:
    moved: list[Moved] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    failed: list[Failed] = field(default_factory=list)


def resolve_destination(
    category: Category,
    mode: Mode,
    source: Path,
    target: Path | None,
    system_dirs: Mapping[str, Path],
) -> Path:
    """Папка, в которую должны попасть файлы категории."""
    match mode:
        case Mode.SYSTEM:
            return system_dirs[category.system_dir] / category.system_subdir
        case Mode.SUBFOLDERS:
            return source / category.folder
        case Mode.CUSTOM:
            if target is None:
                raise ValueError("для режима custom нужна целевая папка")
            return target / category.folder


def unique_destination(
    directory: Path, name: str, reserved: Collection[Path] = ()
) -> Path:
    """Путь для файла в папке; занятое имя получает счётчик: a.jpg -> a_1.jpg."""
    candidate = directory / name
    if candidate not in reserved and not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if candidate not in reserved and not candidate.exists():
            return candidate
        counter += 1


type SortResult = Moved | Skipped | Failed


def is_busy_error(error: OSError) -> bool:
    """Файл занят другой программой (WinError 32 или 33).
    На Linux PermissionError означает нехватку прав, это не "занято".
    """
    return (
        isinstance(error, PermissionError)
        and getattr(error, "winerror", None) in _WINDOWS_BUSY
    )


def _move(path: Path, destination: Path) -> None:
    """Перемещает файл, копия и оригинал одновременно не остаются.
    Сначала rename: на одном диске это один шаг, либо переехал, либо нет.
    Копирование нужно только для другого диска. Если оно не удалось, а
    оригинал на месте, недокопированный результат удаляется: имя
    назначения было свободным, значит, файл там наш.
    """
    try:
        path.rename(destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        try:
            shutil.move(path, destination)
        except OSError:
            if path.exists():
                destination.unlink(missing_ok=True)
            raise


def sort_file(
    path: Path,
    config: Config,
    resolve: Callable[[Category], Path],
    *,
    dry_run: bool = False,
    reserved: set[Path] | None = None,
    attempts: int = BUSY_ATTEMPTS,
    delay: float = BUSY_DELAY,
    sleep: Callable[[float], None] = time.sleep,
) -> SortResult:
    """Сортирует один файл.
    reserved - имена, уже занятые в этом запуске: пополняется, чтобы пробный
    запуск (dry_run) выдавал те же имена, что и настоящий.
    Если файл занят другой программой, пробуем attempts раз с паузой delay.
    При отказе файл остаётся на месте, в Failed busy=True.
    """
    category = config.category_for(path.name)
    if category is None:
        return Skipped(path, SkipReason.UNKNOWN_TYPE)

    directory = resolve(category)
    if directory.resolve() == path.parent.resolve():
        return Skipped(path, SkipReason.ALREADY_IN_PLACE)

    taken = reserved if reserved is not None else set()
    destination = unique_destination(directory, path.name, taken)
    taken.add(destination)
    if not dry_run:
        for attempt in range(1, attempts + 1):
            try:
                directory.mkdir(parents=True, exist_ok=True)
                _move(path, destination)
                break
            except OSError as error:
                if not is_busy_error(error):
                    return Failed(path, str(error))
                if attempt == attempts:
                    return Failed(path, BUSY_MESSAGE, busy=True)
                sleep(delay)
    return Moved(path, destination, category.key)


def sort_folder(
    source: Path,
    config: Config,
    resolve: Callable[[Category], Path],
    *,
    dry_run: bool = False,
) -> SortReport:
    """Сортирует файлы папки (без вложенных папок) и возвращает отчёт."""
    if not source.is_dir():
        raise NotADirectoryError(f"папка не найдена: {source}")

    report = SortReport()
    reserved: set[Path] = set()
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        result = sort_file(path, config, resolve, dry_run=dry_run, reserved=reserved)
        match result:
            case Moved():
                report.moved.append(result)
            case Skipped():
                report.skipped.append(result)
            case Failed():
                report.failed.append(result)
    return report
