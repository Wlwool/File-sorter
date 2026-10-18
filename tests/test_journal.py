import json
from datetime import datetime
from pathlib import Path

import platformdirs
import pytest

from file_sorter import journal


@pytest.fixture
def journal_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Направляет каталог состояния во временную папку (его нет до записи)."""
    state = tmp_path / "state"
    monkeypatch.setattr(platformdirs, "user_state_dir", lambda *a, **k: str(state))
    return state / "journal.jsonl"


def make_entry(name: str = "a.jpg", size: int = 1, mtime_ns: int = 1) -> journal.Entry:
    return journal.Entry(
        original=Path("/src") / name,
        current=Path("/dst") / name,
        size=size,
        mtime_ns=mtime_ns,
    )


def run_names(runs: list[journal.Run]) -> list[str]:
    """По одному перемещению в запуске: имя файла служит меткой запуска."""
    return [run.entries[0].original.name for run in runs]


def test_path_is_in_state_dir(journal_file: Path) -> None:
    assert journal.journal_path() == journal_file


def test_load_without_file_is_empty(journal_file: Path) -> None:
    assert journal.load_runs() == []
    assert not journal_file.exists()


def test_roundtrip(journal_file: Path) -> None:
    first = make_entry("a.jpg", size=10, mtime_ns=111)
    second = make_entry("фото.jpg", size=20, mtime_ns=222)
    journal.append_run([first, second])
    runs = journal.load_runs()
    assert len(runs) == 1
    assert runs[0].entries == (first, second)


def test_empty_run_writes_nothing(journal_file: Path) -> None:
    journal.append_run([])
    assert journal.load_runs() == []
    assert not journal_file.exists()


def test_runs_keep_order(journal_file: Path) -> None:
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        journal.append_run([make_entry(name)])
    assert run_names(journal.load_runs()) == ["a.jpg", "b.jpg", "c.jpg"]


def test_one_line_per_run(journal_file: Path) -> None:
    journal.append_run([make_entry("a.jpg"), make_entry("b.jpg")])
    journal.append_run([make_entry("c.jpg")])
    lines = journal_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(isinstance(json.loads(line), dict) for line in lines)


def test_limit_drops_oldest_runs(
    journal_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit = 3
    monkeypatch.setattr(journal, "MAX_RUNS", limit)
    names = [f"run{number}.jpg" for number in range(limit + 2)]
    for name in names:
        journal.append_run([make_entry(name)])
    assert run_names(journal.load_runs()) == names[-limit:]


def test_pop_last_returns_and_removes(journal_file: Path) -> None:
    journal.append_run([make_entry("a.jpg")])
    journal.append_run([make_entry("b.jpg")])
    last = journal.pop_last_run()
    assert last is not None
    assert last.entries[0].original.name == "b.jpg"
    assert run_names(journal.load_runs()) == ["a.jpg"]


def test_pop_last_on_empty_journal_returns_none(journal_file: Path) -> None:
    assert journal.pop_last_run() is None


def test_pop_last_until_empty(journal_file: Path) -> None:
    journal.append_run([make_entry("a.jpg")])
    journal.append_run([make_entry("b.jpg")])
    popped = [journal.pop_last_run(), journal.pop_last_run(), journal.pop_last_run()]
    assert [run is None for run in popped] == [False, False, True]
    assert journal.load_runs() == []


def test_corrupted_line_is_skipped(journal_file: Path) -> None:
    journal.append_run([make_entry("a.jpg")])
    with journal_file.open("a", encoding="utf-8") as stream:
        stream.write("{это не json\n")
    assert run_names(journal.load_runs()) == ["a.jpg"]


def test_json_of_wrong_shape_is_skipped(journal_file: Path) -> None:
    journal.append_run([make_entry("a.jpg")])
    with journal_file.open("a", encoding="utf-8") as stream:
        stream.write('{"foo": 1}\n')
    assert run_names(journal.load_runs()) == ["a.jpg"]


def test_run_has_timezone_aware_time(journal_file: Path) -> None:
    journal.append_run([make_entry()])
    stamp = datetime.fromisoformat(journal.load_runs()[0].time)
    assert stamp.tzinfo is not None


def test_no_leftover_files_after_write(journal_file: Path) -> None:
    journal.append_run([make_entry("a.jpg")])
    journal.append_run([make_entry("b.jpg")])
    journal.pop_last_run()
    assert [path.name for path in journal_file.parent.iterdir()] == ["journal.jsonl"]
