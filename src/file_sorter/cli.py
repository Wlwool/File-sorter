"""Командная строка: file-sorter clean и file-sorter watch."""

import argparse
import sys
import threading
import time
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from file_sorter.config import Category, Config, ConfigError, load_config
from file_sorter.folders import default_system_dirs
from file_sorter.sorter import (
    Failed,
    Mode,
    Moved,
    Skipped,
    SkipReason,
    SortReport,
    SortResult,
    resolve_destination,
    sort_folder,
)
from file_sorter.watcher import DEFAULT_SETTLE
from file_sorter.watcher import watch as watch_folder

type Resolver = Callable[[Category], Path]

_MODE_HELP = (
    "system - в системные папки (Изображения, Музыка и т. д.), по умолчанию; "
    "subfolders - в подпапки внутри сортируемой папки; "
    "custom - в подпапки внутри папки из --target"
)

_SKIP_TEXT = {
    SkipReason.UNKNOWN_TYPE: "неизвестный тип",
    SkipReason.ALREADY_IN_PLACE: "уже на месте",
}


def _add_sort_arguments(parser: argparse.ArgumentParser) -> None:
    """Общие параметры команд clean и watch."""
    parser.add_argument(
        "folder",
        nargs="?",
        type=Path,
        help="папка; по умолчанию Загрузки",
    )
    parser.add_argument("--mode", choices=[m.value for m in Mode], help=_MODE_HELP)
    parser.add_argument(
        "--target",
        type=Path,
        help="куда раскладывать в режиме custom (само по себе включает его)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать, что будет сделано, без перемещения файлов",
    )
    parser.add_argument("--config", type=Path, help="файл конфига категорий (TOML)")


def build_parser() -> tuple[
    argparse.ArgumentParser, dict[str, argparse.ArgumentParser]
]:
    """Возвращает главный разборщик и разборщики команд по их именам."""
    parser = argparse.ArgumentParser(
        prog="file-sorter",
        description="Сортировка файлов по папкам.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="КОМАНДА")

    clean = subparsers.add_parser(
        "clean",
        help="одноразовая сортировка папки",
        description="Одноразовая сортировка файлов в папке (без вложенных папок).",
    )
    _add_sort_arguments(clean)

    watch = subparsers.add_parser(
        "watch",
        help="следить за папкой и сортировать новые файлы",
        description=(
            "Следит за папкой и сортирует файлы, которые в ней появляются. "
            "Файлы, лежавшие до запуска, не трогает (для них есть clean). "
            "Остановка: Ctrl+C."
        ),
    )
    _add_sort_arguments(watch)
    watch.add_argument(
        "--settle",
        type=float,
        default=DEFAULT_SETTLE,
        metavar="СЕКУНДЫ",
        help=(
            "сколько секунд файл не должен меняться, чтобы его сортировать "
            f"(по умолчанию {DEFAULT_SETTLE:g})"
        ),
    )
    return parser, {"clean": clean, "watch": watch}


def _moved_text(moved: Moved, *, dry_run: bool) -> str:
    verb = "Будет перемещён" if dry_run else "Перемещён"
    return f"{verb}: {moved.source.name} -> {moved.destination.parent}"


def _print_report(report: SortReport, *, dry_run: bool) -> None:
    for moved in report.moved:
        print(_moved_text(moved, dry_run=dry_run))
    for skipped in report.skipped:
        print(f"Пропущен ({_SKIP_TEXT[skipped.reason]}): {skipped.path.name}")
    for failed in report.failed:
        print(f"[X] Ошибка: {failed.path.name}: {failed.message}", file=sys.stderr)

    def skipped_count(reason: SkipReason) -> int:
        return sum(1 for item in report.skipped if item.reason is reason)

    print()
    print(f"Перемещено: {len(report.moved)}")
    print(f"Пропущено (неизвестный тип): {skipped_count(SkipReason.UNKNOWN_TYPE)}")
    print(f"Пропущено (уже на месте): {skipped_count(SkipReason.ALREADY_IN_PLACE)}")
    print(f"Ошибок: {len(report.failed)}")
    if dry_run:
        print("Это пробный запуск: файлы не перемещались.")


def _print_event(result: SortResult, *, dry_run: bool) -> None:
    """Строка журнала для режима слежения: только перемещения и ошибки."""
    stamp = time.strftime("%H:%M:%S")
    match result:
        case Moved():
            print(f"[{stamp}] {_moved_text(result, dry_run=dry_run)}", flush=True)
        case Failed():
            print(
                f"[{stamp}] [X] Ошибка: {result.path.name}: {result.message}",
                file=sys.stderr,
                flush=True,
            )
        case Skipped():
            pass  # временные и неизвестные файлы в журнал не пишем


def _do_clean(source: Path, config: Config, resolve: Resolver, *, dry_run: bool) -> int:
    try:
        report = sort_folder(source, config, resolve, dry_run=dry_run)
    except OSError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    print()
    _print_report(report, dry_run=dry_run)
    return 1 if report.failed else 0


def _do_watch(
    source: Path,
    config: Config,
    resolve: Resolver,
    *,
    dry_run: bool,
    settle: float,
) -> int:
    print(f"Слежение запущено (файл должен не меняться {settle:g} с). Ctrl+C - стоп.")
    sys.stdout.flush()
    try:
        watch_folder(
            source,
            config,
            resolve,
            settle=settle,
            dry_run=dry_run,
            on_result=partial(_print_event, dry_run=dry_run),
            stop=threading.Event(),
        )
    except KeyboardInterrupt:
        print("\nОстановлено.")
        return 0
    except OSError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    return 0


def _run_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    action: Callable[[Path, Config, Resolver], int],
) -> int:
    """Общая часть команд: режим, конфиг, папки, затем action."""
    if args.mode is not None:
        mode = Mode(args.mode)
    else:
        mode = Mode.CUSTOM if args.target is not None else Mode.SYSTEM
    if mode is Mode.CUSTOM and args.target is None:
        parser.error("режим custom требует --target")
    if mode is not Mode.CUSTOM and args.target is not None:
        parser.error("--target работает только в режиме custom")

    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"Ошибка конфига: {error}", file=sys.stderr)
        return 2

    system_dirs = default_system_dirs()
    source = args.folder.expanduser() if args.folder else system_dirs["downloads"]
    target = args.target.expanduser() if args.target else None
    resolve = partial(
        resolve_destination,
        mode=mode,
        source=source,
        target=target,
        system_dirs=system_dirs,
    )

    print(f"Папка: {source}")
    print(f"Режим: {mode.value}")
    return action(source, config, resolve)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа. Коды выхода: 0 - успех, 1 - были ошибки, 2 - неверный запуск."""
    parser, commands = build_parser()
    args = parser.parse_args(argv)
    match args.command:
        case "clean":
            action = partial(_do_clean, dry_run=args.dry_run)
        case "watch":
            if args.settle < 0:
                commands["watch"].error("--settle не может быть отрицательным")
            action = partial(_do_watch, dry_run=args.dry_run, settle=args.settle)
        case _:
            parser.print_help()
            return 0
    return _run_command(args, commands[args.command], action)
