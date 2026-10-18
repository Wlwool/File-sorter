"""Командная строка: file-sorter clean, watch и service."""

import argparse
import shlex
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from pathlib import Path
from types import FrameType

from file_sorter import journal, menu
from file_sorter.config import Category, Config, ConfigError, load_config
from file_sorter.folders import default_system_dirs
from file_sorter.service import ServiceError, ServiceSpec, default_backend
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
from file_sorter.undo import (
    Restored,
    UndoReport,
    UndoSkipReason,
    undo_run,
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

_UNDO_SKIP_TEXT = {
    UndoSkipReason.MISSING: "файла нет на месте, возможно, удалён или перемещён",
    UndoSkipReason.CHANGED: "файл изменён после сортировки",
}


def _add_sort_arguments(parser: argparse.ArgumentParser, *, dry_run: bool) -> None:
    """Общие параметры команд clean, watch и service install."""
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
    if dry_run:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="показать, что будет сделано, без перемещения файлов",
        )
    parser.add_argument("--config", type=Path, help="файл конфига категорий (TOML)")


def _add_settle_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--settle",
        type=float,
        default=DEFAULT_SETTLE,
        metavar="СЕКУНДЫ",
        help=(
            "сколько секунд файл не должен меняться, чтобы его сортировать "
            f"(по умолчанию {DEFAULT_SETTLE:g})"
        ),
    )


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
    _add_sort_arguments(clean, dry_run=True)

    watch = subparsers.add_parser(
        "watch",
        help="следить за папкой и сортировать новые файлы",
        description=(
            "Следит за папкой и сортирует файлы, которые в ней появляются. "
            "Файлы, лежавшие до запуска, не трогает (для них есть clean). "
            "Остановка: Ctrl+C."
        ),
    )
    _add_sort_arguments(watch, dry_run=True)
    _add_settle_argument(watch)
    watch.add_argument(
        "--log-file",
        type=Path,
        help="писать весь вывод в этот файл (для работы в фоне)",
    )

    service = subparsers.add_parser(
        "service",
        help="автозапуск: установка и управление фоновой службой слежения",
        description=(
            "Фоновая служба следит за папкой сама: запускается при входе в систему "
            "(Linux: systemd, Windows: Планировщик заданий)."
        ),
    )
    actions = service.add_subparsers(dest="action", metavar="ДЕЙСТВИЕ", required=True)
    install = actions.add_parser(
        "install",
        help="установить службу и запустить её",
        description=(
            "Устанавливает службу, которая выполняет file-sorter watch с этими "
            "параметрами, и сразу запускает её. Окружение (папка проекта или "
            "установка через uv tool install) должно сохраняться."
        ),
    )
    _add_sort_arguments(install, dry_run=False)
    _add_settle_argument(install)
    actions.add_parser("start", help="запустить службу")
    actions.add_parser("stop", help="остановить службу (автозапуск остаётся)")
    actions.add_parser("status", help="показать состояние службы")
    actions.add_parser("uninstall", help="остановить службу и убрать автозапуск")

    subparsers.add_parser(
        "undo",
        help="отменить последнюю сортировку",
        description=(
            "Возвращает файлы последней сортировки на прежние места. "
            "Повторный запуск отменяет предыдущую сортировку."
        ),
    )

    return parser, {"clean": clean, "watch": watch, "service install": install}


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
    moved_label = "Будет перемещено" if dry_run else "Перемещено"
    print(f"{moved_label}: {len(report.moved)}")
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


def _remember(results: Iterable[SortResult], *, dry_run: bool) -> None:
    """Записывает настоящие перемещения в журнал, чтобы их можно было отменить."""
    if dry_run:
        return
    moves = [item for item in results if isinstance(item, Moved)]
    try:
        journal.record_moves(moves)
    except OSError as error:
        print(
            f"Предупреждение: не удалось записать журнал перемещений ({error}). "
            "Эту сортировку нельзя будет отменить командой undo.",
            file=sys.stderr,
        )


def _do_clean(source: Path, config: Config, resolve: Resolver, *, dry_run: bool) -> int:
    try:
        report = sort_folder(source, config, resolve, dry_run=dry_run)
    except OSError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    print()
    _print_report(report, dry_run=dry_run)
    _remember(report.moved, dry_run=dry_run)
    return 1 if report.failed else 0


def _run_time_text(stamp: str) -> str:
    """Время запуска из журнала в местном времени, нечитаемое - как есть."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp


def _restored_text(item: Restored) -> str:
    name = item.entry.original.name
    if item.renamed:
        return (
            f"Возвращён под другим именем: {name} -> {item.destination.name} "
            f"({name} уже существует)"
        )
    return f"Возвращён: {name} -> {item.entry.original.parent}"


def _print_undo_report(report: UndoReport) -> None:
    for restored in report.restored:
        print(_restored_text(restored))
    for skipped in report.skipped:
        name = skipped.entry.original.name
        print(f"Пропущен: {name} ({_UNDO_SKIP_TEXT[skipped.reason]})")
    for failed in report.failed:
        name = failed.entry.original.name
        print(f"[X] Ошибка: {name}: {failed.message}", file=sys.stderr)
    print()
    print(f"Возвращено: {len(report.restored)}")
    print(f"Пропущено: {len(report.skipped)}")
    print(f"Ошибок: {len(report.failed)}")


def _do_undo() -> int:
    try:
        runs = journal.load_runs()
    except OSError as error:
        print(f"Ошибка: не удалось прочитать журнал ({error})", file=sys.stderr)
        return 2
    if not runs:
        print("Нечего отменять: журнал перемещений пуст.")
        return 0

    run = runs[-1]
    when = _run_time_text(run.time)
    print(f"Отменяю сортировку от {when} (файлов: {len(run.entries)})\n")
    report = undo_run(run)
    _print_undo_report(report)
    try:
        journal.pop_last_run()
    except OSError as error:
        print(
            f"Предупреждение: не удалось обновить журнал ({error}). "
            "Повторный undo попробует отменить эту сортировку ещё раз.",
            file=sys.stderr,
        )
    return 1 if report.failed else 0


def _raise_interrupt(signum: int, frame: FrameType | None) -> None:
    """SIGTERM (так службу останавливает systemd) работает как Ctrl+C."""
    raise KeyboardInterrupt


def _do_watch(
    source: Path,
    config: Config,
    resolve: Resolver,
    *,
    dry_run: bool,
    settle: float,
) -> int:
    previous = signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        print(
            f"Слежение запущено (файл должен не меняться {settle:g} с). Ctrl+C - стоп.",
            flush=True,
        )
        try:
            watch_folder(
                source,
                config,
                resolve,
                settle=settle,
                dry_run=dry_run,
                on_result=partial(_print_event, dry_run=dry_run),
                on_batch=partial(_remember, dry_run=dry_run),
                stop=threading.Event(),
            )
        except KeyboardInterrupt:
            print("\nОстановлено.", flush=True)
            return 0
        except OSError as error:
            print(f"Ошибка: {error}", file=sys.stderr)
            return 2
        return 0
    finally:
        signal.signal(
            signal.SIGTERM, previous if previous is not None else signal.SIG_DFL
        )


@contextmanager
def _output_to(log_file: Path | None) -> Iterator[None]:
    """Направляет весь вывод программы в файл (без окна консоли его не видно)."""
    if log_file is None:
        yield
        return
    log_file.parent.mkdir(parents=True, exist_ok=True)
    original = sys.stdout, sys.stderr
    with log_file.open("a", encoding="utf-8", buffering=1) as stream:
        sys.stdout = sys.stderr = stream
        try:
            yield
        finally:
            sys.stdout, sys.stderr = original


def _resolve_mode(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Mode:
    if args.mode is not None:
        mode = Mode(args.mode)
    else:
        mode = Mode.CUSTOM if args.target is not None else Mode.SYSTEM
    if mode is Mode.CUSTOM and args.target is None:
        parser.error("режим custom требует --target")
    if mode is not Mode.CUSTOM and args.target is not None:
        parser.error("--target работает только в режиме custom")
    return mode


def _run_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    action: Callable[[Path, Config, Resolver], int],
) -> int:
    """Общая часть команд: режим, конфиг, папки, затем action."""
    mode = _resolve_mode(args, parser)
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


def _prepare_install(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> ServiceSpec | None:
    """Проверяет параметры службы и собирает её команду; None - если нельзя.

    Пути делаем абсолютными: у службы другая рабочая папка.
    """
    mode = _resolve_mode(args, parser)
    if args.settle < 0:
        parser.error("--settle не может быть отрицательным")
    try:
        load_config(args.config)
    except ConfigError as error:
        print(f"Ошибка конфига: {error}", file=sys.stderr)
        return None

    if args.folder is not None:
        folder = args.folder.expanduser().resolve()
    else:
        folder = default_system_dirs()["downloads"]
    if not folder.is_dir():
        print(f"Ошибка: папка не найдена: {folder}", file=sys.stderr)
        return None

    watch_args: list[str] = []
    if args.folder is not None:
        watch_args.append(str(folder))
    watch_args += ["--mode", mode.value, "--settle", f"{args.settle:g}"]
    if args.target is not None:
        watch_args += ["--target", str(args.target.expanduser().resolve())]
    if args.config is not None:
        watch_args += ["--config", str(args.config.expanduser().resolve())]
    return ServiceSpec(Path(sys.executable), tuple(watch_args))


def _run_service(args: argparse.Namespace, install: argparse.ArgumentParser) -> int:
    try:
        backend = default_backend()
        if args.action == "install":
            spec = _prepare_install(args, install)
            if spec is None:
                return 2
            message = backend.install(spec)
        else:
            controls = {
                "uninstall": backend.uninstall,
                "start": backend.start,
                "stop": backend.stop,
                "status": backend.status,
            }
            message = controls[args.action]()
    except ServiceError as error:
        print(error, file=sys.stderr)
        return 1
    print(message)
    return 0


def _use_utf8_output() -> None:
    """Выводит текст в UTF-8 на Windows"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _is_interactive() -> bool:
    """Меню показывает только человеку у терминала, а не скрипту или службе."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа. Коды выхода: 0 - успех, 1 - были ошибки, 2 - неверный запуск."""
    _use_utf8_output()
    parser, commands = build_parser()
    args = parser.parse_args(argv)
    match args.command:
        case "clean":
            clean = partial(_do_clean, dry_run=args.dry_run)
            return _run_command(args, commands["clean"], clean)
        case "watch":
            if args.settle < 0:
                commands["watch"].error("--settle не может быть отрицательным")
            watch = partial(_do_watch, dry_run=args.dry_run, settle=args.settle)
            with _output_to(args.log_file):
                return _run_command(args, commands["watch"], watch)
        case "service":
            return _run_service(args, commands["service install"])
        case "undo":
            return _do_undo()
        case _:
            if _is_interactive():
                chosen = menu.ask_arguments()
                if chosen is None:
                    return 0
                print(f"\nЗапускаю: file-sorter {shlex.join(chosen)}\n")
                return main(chosen)
            parser.print_help()
            return 0
