"""Командная строка: file-sorter clean."""

import argparse
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path

from file_sorter.config import ConfigError, load_config
from file_sorter.folders import default_system_dirs
from file_sorter.sorter import (
    Mode,
    SkipReason,
    SortReport,
    resolve_destination,
    sort_folder,
)

_MODE_HELP = (
    "system - в системные папки (Изображения, Музыка и т. д.), по умолчанию; "
    "subfolders - в подпапки внутри сортируемой папки; "
    "custom - в подпапки внутри папки из --target"
)


def build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """Возвращает главный разборщик и разборщик команды clean."""
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
    clean.add_argument(
        "folder",
        nargs="?",
        type=Path,
        help="что сортировать; по умолчанию папка Загрузки",
    )
    clean.add_argument("--mode", choices=[m.value for m in Mode], help=_MODE_HELP)
    clean.add_argument(
        "--target",
        type=Path,
        help="куда раскладывать в режиме custom (само по себе включает его)",
    )
    clean.add_argument(
        "--dry-run",
        action="store_true",
        help="показать, что будет сделано, без перемещения файлов",
    )
    clean.add_argument("--config", type=Path, help="файл конфига категорий (TOML)")
    return parser, clean


_SKIP_TEXT = {
    SkipReason.UNKNOWN_TYPE: "неизвестный тип",
    SkipReason.ALREADY_IN_PLACE: "уже на месте",
}


def _print_report(report: SortReport, *, dry_run: bool) -> None:
    verb = "Будет перемещён" if dry_run else "Перемещён"
    for moved in report.moved:
        print(f"{verb}: {moved.source.name} -> {moved.destination.parent}")
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


def _run_clean(args: argparse.Namespace, clean: argparse.ArgumentParser) -> int:
    if args.mode is not None:
        mode = Mode(args.mode)
    else:
        mode = Mode.CUSTOM if args.target is not None else Mode.SYSTEM
    if mode is Mode.CUSTOM and args.target is None:
        clean.error("режим custom требует --target")
    if mode is not Mode.CUSTOM and args.target is not None:
        clean.error("--target работает только в режиме custom")

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
    try:
        report = sort_folder(source, config, resolve, dry_run=args.dry_run)
    except OSError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    print()
    _print_report(report, dry_run=args.dry_run)
    return 1 if report.failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа. Коды выхода: 0 - успех, 1 - были ошибки, 2 - неверный запуск."""
    parser, clean = build_parser()
    args = parser.parse_args(argv)
    if args.command == "clean":
        return _run_clean(args, clean)
    parser.print_help()
    return 0
