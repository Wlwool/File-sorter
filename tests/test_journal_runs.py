from pathlib import Path

import pytest

from file_sorter import journal
from file_sorter.journal import Entry, Run


def add_run(*names: str) -> None:
    """Добавляет в журнал запуск, в нём по одной записи на имя."""
    journal.append_run(
        Entry(Path("/src") / name, Path("/src/out") / name, 1, 1) for name in names
    )


def names_of(runs: list[Run]) -> list[list[str]]:
    return [[entry.original.name for entry in run.entries] for run in runs]


def test_pop_run_one_is_the_last() -> None:
    add_run("a")
    add_run("b")
    add_run("c")
    run = journal.pop_run(1)
    assert run is not None
    assert [entry.original.name for entry in run.entries] == ["c"]
    assert names_of(journal.load_runs()) == [["a"], ["b"]]


def test_pop_run_takes_one_from_the_middle() -> None:
    add_run("a")
    add_run("b")
    add_run("c")
    run = journal.pop_run(2)
    assert run is not None
    assert [entry.original.name for entry in run.entries] == ["b"]
    assert names_of(journal.load_runs()) == [["a"], ["c"]]


def test_pop_run_takes_the_oldest() -> None:
    add_run("a")
    add_run("b")
    add_run("c")
    run = journal.pop_run(3)
    assert run is not None
    assert [entry.original.name for entry in run.entries] == ["a"]
    assert names_of(journal.load_runs()) == [["b"], ["c"]]


@pytest.mark.parametrize("number", [0, 4, -1])
def test_pop_run_out_of_range_changes_nothing(number: int) -> None:
    add_run("a")
    add_run("b")
    add_run("c")
    assert journal.pop_run(number) is None
    assert names_of(journal.load_runs()) == [["a"], ["b"], ["c"]]


def test_pop_run_on_empty_journal() -> None:
    assert journal.pop_run(1) is None
