from pathlib import Path

import pytest

from file_sorter import config


@pytest.fixture(autouse=True)
def _isolated_user_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тесты не должны зависеть от настоящего конфига пользователя."""
    missing = tmp_path_factory.mktemp("user_config") / "config.toml"
    monkeypatch.setattr(config, "user_config_path", lambda: missing)


def make_files(directory: Path, *names: str) -> None:
    """Создаёт в папке файлы, содержимое файла равно его имени."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text(name, encoding="utf-8")
