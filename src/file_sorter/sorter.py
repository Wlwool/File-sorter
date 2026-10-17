"""Перемещение файлов по категориям."""

import shutil
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from file_sorter.config import Category, Config


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
        category = config.category_for(path.name)
        if category is None:
            report.skipped.append(Skipped(path, SkipReason.UNKNOWN_TYPE))
            continue

        directory = resolve(category)
        if directory.resolve() == path.parent.resolve():
            report.skipped.append(Skipped(path, SkipReason.ALREADY_IN_PLACE))
            continue

        destination = unique_destination(directory, path.name, reserved)
        reserved.add(destination)
        if not dry_run:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                shutil.move(path, destination)
            except OSError as error:
                report.failed.append(Failed(path, str(error)))
                continue
        report.moved.append(Moved(path, destination, category.key))
    return report
