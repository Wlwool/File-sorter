import shutil
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from file_sorter import sorter
from file_sorter.config import Category, Config, load_config
from file_sorter.sorter import Failed, Mode, Moved, resolve_destination
from tests.conftest import make_files


@pytest.fixture
def config() -> Config:
    return load_config()


def subfolders(source: Path) -> Callable[[Category], Path]:
    return partial(
        resolve_destination,
        mode=Mode.SUBFOLDERS,
        source=source,
        target=None,
        system_dirs={},
    )


def busy_error() -> PermissionError:
    """Ошибка Windows "файл занят другим процессом" (WinError 32).
    Атрибут winerror ставим руками: на Linux конструктор его не заполняет.
    """
    error = PermissionError(13, "файл занят")
    error.winerror = 32  # type: ignore[attr-defined]
    return error


def windows_error(code: int) -> PermissionError:
    error = PermissionError(13, "ошибка Windows")
    error.winerror = code  # type: ignore[attr-defined]
    return error


def stub_rename(monkeypatch: pytest.MonkeyPatch, *errors: OSError) -> list[Path]:
    """Path.rename падает с указанными ошибками по очереди, потом работает."""
    real = Path.rename
    calls: list[Path] = []

    def fake(self: Path, target: Path) -> Path:
        calls.append(self)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return real(self, target)

    monkeypatch.setattr(Path, "rename", fake)
    return calls


class TestRetryBusyFile:
    def test_busy_file_is_retried_until_it_moves(
        self, tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        calls = stub_rename(monkeypatch, busy_error(), busy_error())
        sleeps: list[float] = []
        result = sorter.sort_file(
            tmp_path / "a.jpg", config, subfolders(tmp_path), sleep=sleeps.append
        )
        assert isinstance(result, Moved)
        assert (tmp_path / "Images" / "a.jpg").exists()
        assert not (tmp_path / "a.jpg").exists()
        assert len(calls) == 3
        assert sleeps == [1.0, 1.0]

    def test_gives_up_after_all_attempts_and_leaves_file(
        self, tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        calls = stub_rename(monkeypatch, *[busy_error()] * 10)
        sleeps: list[float] = []
        result = sorter.sort_file(
            tmp_path / "a.jpg", config, subfolders(tmp_path), sleep=sleeps.append
        )
        assert isinstance(result, Failed)
        assert result.busy is True
        assert "занят" in result.message
        assert len(calls) == 5
        assert len(sleeps) == 4  # после последней попытки не ждём
        assert (tmp_path / "a.jpg").exists()
        assert list((tmp_path / "Images").iterdir()) == []  # копий нет

    def test_attempts_and_delay_are_configurable(
        self, tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        calls = stub_rename(monkeypatch, *[busy_error()] * 10)
        sleeps: list[float] = []
        sorter.sort_file(
            tmp_path / "a.jpg",
            config,
            subfolders(tmp_path),
            attempts=3,
            delay=0.25,
            sleep=sleeps.append,
        )
        assert len(calls) == 3
        assert sleeps == [0.25, 0.25]

    def test_permission_error_without_winerror_is_not_retried(
        self, tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        calls = stub_rename(monkeypatch, PermissionError(13, "нет прав"))
        sleeps: list[float] = []
        result = sorter.sort_file(
            tmp_path / "a.jpg", config, subfolders(tmp_path), sleep=sleeps.append
        )
        assert isinstance(result, Failed)
        assert result.busy is False
        assert len(calls) == 1
        assert sleeps == []

    def test_other_windows_error_is_not_retried(
        self, tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        calls = stub_rename(monkeypatch, windows_error(5))  # отказано в доступе
        sleeps: list[float] = []
        result = sorter.sort_file(
            tmp_path / "a.jpg", config, subfolders(tmp_path), sleep=sleeps.append
        )
        assert isinstance(result, Failed)
        assert result.busy is False
        assert len(calls) == 1
        assert sleeps == []

    def test_dry_run_does_not_try_to_move(
        self, tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        calls = stub_rename(monkeypatch, busy_error())
        result = sorter.sort_file(
            tmp_path / "a.jpg", config, subfolders(tmp_path), dry_run=True
        )
        assert isinstance(result, Moved)
        assert calls == []


class TestOtherDrive:
    def test_other_drive_falls_back_to_move(
        self, tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        calls = stub_rename(monkeypatch, OSError(18, "другой диск"))  # EXDEV
        result = sorter.sort_file(tmp_path / "a.jpg", config, subfolders(tmp_path))
        assert isinstance(result, Moved)
        assert len(calls) == 1
        assert (tmp_path / "Images" / "a.jpg").exists()
        assert not (tmp_path / "a.jpg").exists()

    def test_failed_fallback_removes_partial_copy_and_retries(
        self, tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        stub_rename(monkeypatch, *[OSError(18, "другой диск")] * 10)
        moves: list[Path] = []

        def copy_then_fail(source: Path, destination: Path) -> None:
            moves.append(destination)
            shutil.copy2(source, destination)  # копия есть, оригинал не удалён
            raise busy_error()

        monkeypatch.setattr(sorter.shutil, "move", copy_then_fail)
        result = sorter.sort_file(
            tmp_path / "a.jpg",
            config,
            subfolders(tmp_path),
            attempts=2,
            sleep=lambda seconds: None,
        )
        assert isinstance(result, Failed)
        assert result.busy is True
        assert len(moves) == 2
        assert (tmp_path / "a.jpg").exists()
        assert list((tmp_path / "Images").iterdir()) == []
