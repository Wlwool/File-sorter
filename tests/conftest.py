import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import platformdirs
import pytest

from file_sorter import config


@pytest.fixture(autouse=True)
def _isolated_user_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тесты не должны зависеть от настоящего конфига пользователя."""
    missing = tmp_path_factory.mktemp("user_config") / "config.toml"
    monkeypatch.setattr(config, "user_config_path", lambda: missing)


@pytest.fixture(autouse=True)
def journal_file(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Журнал перемещений каждого теста лежит во временной папке.
    Каталога состояния до первой записи нет, как у нового пользователя.
    """
    state = tmp_path_factory.mktemp("state_parent") / "state"
    monkeypatch.setattr(platformdirs, "user_state_dir", lambda *a, **k: str(state))
    return state / "journal.jsonl"


def make_files(directory: Path, *names: str) -> None:
    """Создаёт в папке файлы, содержимое файла равно его имени."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text(name, encoding="utf-8")


class FakeRunner:
    """Подмена запуска внешних программ (systemctl, schtasks, powershell).
    Запоминает вызовы в calls. replies: если фрагмент ключа входит в команду,
    возвращается (код, stdout, stderr), иначе default. missing=True имитирует
    отсутствие программы. on_call вызывается до ответа (например, чтобы
    прочитать временный файл, который потом будет удалён).
    """

    def __init__(
        self,
        replies: Mapping[str, tuple[int, str, str]] | None = None,
        *,
        default: tuple[int, str, str] = (0, "", ""),
        missing: bool = False,
        on_call: Callable[[tuple[str, ...]], None] | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._replies = dict(replies or {})
        self._default = default
        self._missing = missing
        self._on_call = on_call

    def __call__(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = tuple(args)
        self.calls.append(command)
        if self._missing:
            raise FileNotFoundError(command[0])
        if self._on_call is not None:
            self._on_call(command)
        text = " ".join(command)
        for fragment, (code, out, err) in self._replies.items():
            if fragment in text:
                return subprocess.CompletedProcess(command, code, out, err)
        code, out, err = self._default
        return subprocess.CompletedProcess(command, code, out, err)
