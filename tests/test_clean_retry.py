from collections.abc import Callable
from pathlib import Path

import pytest

from file_sorter import cli, journal, sorter
from file_sorter.cli import main
from file_sorter.sorter import BUSY_MESSAGE, Failed
from tests.conftest import make_files

CLEAN = ["--mode", "subfolders"]


def make_busy(monkeypatch: pytest.MonkeyPatch, **times: int) -> list[str]:
    """Файлы с этими именами "заняты" столько раз, сколько указано.
    Остальные (и занятые после исчерпания счётчика) перемещаются по-настоящему.
    Возвращает имена в порядке обращений.
    """
    real = sorter.sort_file
    left = dict(times)
    seen: list[str] = []

    def fake(path: Path, *args: object, **kwargs: object) -> object:
        seen.append(path.name)
        if left.get(path.name, 0) > 0:
            left[path.name] -= 1
            return Failed(path, BUSY_MESSAGE, busy=True)
        return real(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sorter, "sort_file", fake)
    monkeypatch.setattr(cli, "sort_file", fake)
    return seen


def answers(*replies: str) -> tuple[Callable[[str], str], list[str]]:
    queue = iter(replies)
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return next(queue)

    return ask, asked


class TestCleanRetryFromMenu:
    def test_yes_retries_and_moves_the_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3")
        make_busy(monkeypatch, **{"a.jpg": 1})
        ask, asked = answers("д")
        code = main(["clean", str(tmp_path), *CLEAN], retry_ask=ask)
        assert code == 0
        assert (tmp_path / "Images" / "a.jpg").exists()
        assert not (tmp_path / "a.jpg").exists()
        assert len(asked) == 1
        assert "a.jpg" in capsys.readouterr().out

    def test_retry_result_goes_into_the_same_journal_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3")
        make_busy(monkeypatch, **{"a.jpg": 1})
        ask, _ = answers("д")
        main(["clean", str(tmp_path), *CLEAN], retry_ask=ask)
        (run,) = journal.load_runs()
        assert sorted(entry.original.name for entry in run.entries) == [
            "a.jpg",
            "b.mp3",
        ]

    def test_no_leaves_the_file_and_explains(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3")
        seen = make_busy(monkeypatch, **{"a.jpg": 1})
        ask, asked = answers("н")
        code = main(["clean", str(tmp_path), *CLEAN], retry_ask=ask)
        assert code == 1
        assert (tmp_path / "a.jpg").exists()
        assert seen.count("a.jpg") == 1
        assert len(asked) == 1
        output = capsys.readouterr().out
        assert "остались на месте" in output
        (run,) = journal.load_runs()
        assert [entry.original.name for entry in run.entries] == ["b.mp3"]

    def test_still_busy_asks_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        seen = make_busy(monkeypatch, **{"a.jpg": 2})
        ask, asked = answers("д", "д")
        code = main(["clean", str(tmp_path), *CLEAN], retry_ask=ask)
        assert code == 0
        assert len(asked) == 2
        assert seen.count("a.jpg") == 3
        assert (tmp_path / "Images" / "a.jpg").exists()

    def test_still_busy_then_no_gives_up(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        make_files(tmp_path, "a.jpg")
        make_busy(monkeypatch, **{"a.jpg": 5})
        ask, asked = answers("д", "н")
        assert main(["clean", str(tmp_path), *CLEAN], retry_ask=ask) == 1
        assert len(asked) == 2
        assert (tmp_path / "a.jpg").exists()
        assert "остались на месте" in capsys.readouterr().out

    def test_only_busy_files_are_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3")
        seen = make_busy(monkeypatch, **{"a.jpg": 1})
        ask, _ = answers("д")
        main(["clean", str(tmp_path), *CLEAN], retry_ask=ask)
        assert seen.count("b.mp3") == 1
        assert seen.count("a.jpg") == 2

    def test_end_of_input_counts_as_no_but_journal_is_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3")
        make_busy(monkeypatch, **{"a.jpg": 1})

        def closed(prompt: str) -> str:
            raise EOFError

        assert main(["clean", str(tmp_path), *CLEAN], retry_ask=closed) == 1
        (run,) = journal.load_runs()
        assert [entry.original.name for entry in run.entries] == ["b.mp3"]


class TestCleanWithoutQuestion:
    def test_not_asked_when_not_from_menu(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        make_files(tmp_path, "a.jpg")
        seen = make_busy(monkeypatch, **{"a.jpg": 1})
        assert main(["clean", str(tmp_path), *CLEAN]) == 1
        assert seen == ["a.jpg"]
        assert "a.jpg" in capsys.readouterr().err

    def test_not_asked_when_failure_is_not_busy(self, tmp_path: Path) -> None:
        make_files(tmp_path, "a.jpg", "Images")  # "Images" - это файл
        ask, asked = answers()
        assert main(["clean", str(tmp_path), *CLEAN], retry_ask=ask) == 1
        assert asked == []

    def test_not_asked_when_nothing_failed(self, tmp_path: Path) -> None:
        make_files(tmp_path, "a.jpg")
        ask, asked = answers()
        assert main(["clean", str(tmp_path), *CLEAN], retry_ask=ask) == 0
        assert asked == []

    def test_not_asked_in_dry_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        make_busy(monkeypatch, **{"a.jpg": 1})
        ask, asked = answers()
        code = main(["clean", str(tmp_path), *CLEAN, "--dry-run"], retry_ask=ask)
        assert code == 1  # подмена вернула Failed даже в пробном запуске
        assert asked == []


class TestMenuPassesInput:
    def test_menu_choice_gets_the_retry_question(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        make_files(tmp_path, "a.jpg")
        make_busy(monkeypatch, **{"a.jpg": 1})
        asked: list[str] = []

        def fake_input(prompt: str = "") -> str:
            asked.append(prompt)
            return "д"

        monkeypatch.setattr(cli, "_is_interactive", lambda: True)
        monkeypatch.setattr(
            cli.menu, "ask_arguments", lambda: ["clean", str(tmp_path), *CLEAN]
        )
        monkeypatch.setattr("builtins.input", fake_input)
        assert main([]) == 0
        assert len(asked) == 1
        assert (tmp_path / "Images" / "a.jpg").exists()
