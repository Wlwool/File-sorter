import os
from pathlib import Path

from file_sorter import journal, undo


def moved(
    tmp_path: Path, original: str, current: str, content: str = "data"
) -> journal.Entry:
    """Файл уже лежит на новом месте, как после сортировки, запись снята с него."""
    path = tmp_path / current
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    info = path.stat()
    return journal.Entry(tmp_path / original, path, info.st_size, info.st_mtime_ns)


def run_of(*entries: journal.Entry) -> journal.Run:
    return journal.Run("2026-01-01T00:00:00+00:00", entries)


def test_restores_files_in_order(tmp_path: Path) -> None:
    first = moved(tmp_path, "a.jpg", "Images/a.jpg")
    second = moved(tmp_path, "b.mp3", "Audio/b.mp3")
    report = undo.undo_run(run_of(first, second))
    assert [item.destination for item in report.restored] == [
        tmp_path / "a.jpg",
        tmp_path / "b.mp3",
    ]
    assert not any(item.renamed for item in report.restored)
    assert (tmp_path / "a.jpg").read_text(encoding="utf-8") == "data"
    assert not (tmp_path / "Images" / "a.jpg").exists()
    assert not report.skipped
    assert not report.failed


def test_creates_missing_original_folder(tmp_path: Path) -> None:
    entry = moved(tmp_path, "gone/sub/a.jpg", "Images/a.jpg")
    report = undo.undo_run(run_of(entry))
    assert len(report.restored) == 1
    assert (tmp_path / "gone" / "sub" / "a.jpg").exists()


def test_missing_file_is_skipped(tmp_path: Path) -> None:
    entry = moved(tmp_path, "a.jpg", "Images/a.jpg")
    entry.current.unlink()
    report = undo.undo_run(run_of(entry))
    assert report.skipped == [undo.UndoSkipped(entry, undo.UndoSkipReason.MISSING)]
    assert not report.restored
    assert not (tmp_path / "a.jpg").exists()


def test_changed_size_is_skipped_and_left_alone(tmp_path: Path) -> None:
    entry = moved(tmp_path, "a.jpg", "Images/a.jpg")
    entry.current.write_text("совсем другое содержимое", encoding="utf-8")
    report = undo.undo_run(run_of(entry))
    assert report.skipped == [undo.UndoSkipped(entry, undo.UndoSkipReason.CHANGED)]
    assert entry.current.read_text(encoding="utf-8") == "совсем другое содержимое"
    assert not (tmp_path / "a.jpg").exists()


def test_changed_time_only_is_skipped(tmp_path: Path) -> None:
    entry = moved(tmp_path, "a.jpg", "Images/a.jpg")
    later = entry.mtime_ns + 10**9
    os.utime(entry.current, ns=(later, later))
    report = undo.undo_run(run_of(entry))
    assert report.skipped == [undo.UndoSkipped(entry, undo.UndoSkipReason.CHANGED)]
    assert entry.current.exists()


def test_folder_in_place_of_file_is_skipped(tmp_path: Path) -> None:
    folder = tmp_path / "Images" / "a.jpg"
    folder.mkdir(parents=True)
    info = folder.stat()
    entry = journal.Entry(tmp_path / "a.jpg", folder, info.st_size, info.st_mtime_ns)
    report = undo.undo_run(run_of(entry))
    assert report.skipped == [undo.UndoSkipped(entry, undo.UndoSkipReason.CHANGED)]
    assert folder.is_dir()


def test_occupied_name_gets_counter(tmp_path: Path) -> None:
    entry = moved(tmp_path, "a.jpg", "Images/a.jpg")
    (tmp_path / "a.jpg").write_text("other", encoding="utf-8")
    report = undo.undo_run(run_of(entry))
    (item,) = report.restored
    assert item.destination == tmp_path / "a_1.jpg"
    assert item.renamed
    assert (tmp_path / "a.jpg").read_text(encoding="utf-8") == "other"
    assert (tmp_path / "a_1.jpg").read_text(encoding="utf-8") == "data"
    assert not entry.current.exists()


def test_occupied_counter_keeps_counting(tmp_path: Path) -> None:
    entry = moved(tmp_path, "a.jpg", "Images/a.jpg")
    (tmp_path / "a.jpg").write_text("one", encoding="utf-8")
    (tmp_path / "a_1.jpg").write_text("two", encoding="utf-8")
    report = undo.undo_run(run_of(entry))
    assert [item.destination for item in report.restored] == [tmp_path / "a_2.jpg"]


def test_one_failure_does_not_stop_the_rest(tmp_path: Path) -> None:
    (tmp_path / "blocker").write_text("я файл, а не папка", encoding="utf-8")
    broken = moved(tmp_path, "blocker/a.jpg", "Images/a.jpg")
    fine = moved(tmp_path, "b.jpg", "Images/b.jpg")
    report = undo.undo_run(run_of(broken, fine))
    assert [item.entry for item in report.failed] == [broken]
    assert report.failed[0].message
    assert broken.current.exists()
    assert [item.destination for item in report.restored] == [tmp_path / "b.jpg"]
