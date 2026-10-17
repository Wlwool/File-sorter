"""Общие типы для управления фоновой службой."""

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ServiceError(Exception):
    """Действие не удалось.
    Текст предназначен для пользователя, если автоматически не получилось,
    в нём есть инструкция, что сделать вручную.
    """


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """Что должна запускать служба."""

    python: Path  # интерпретатор окружения, в котором установлен file-sorter
    watch_args: tuple[str, ...]  # аргументы команды watch (после слова watch)


type Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def run_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Запускает внешнюю программу и собирает вывод. Код возврата не проверяет."""
    return subprocess.run(
        args, capture_output=True, text=True, errors="replace", check=False
    )


class ServiceBackend(Protocol):
    """Управление службой на конкретной системе. Каждый метод возвращает текст
    для пользователя или бросает ServiceError."""

    def install(self, spec: ServiceSpec) -> str: ...

    def uninstall(self) -> str: ...

    def start(self) -> str: ...

    def stop(self) -> str: ...

    def status(self) -> str: ...
