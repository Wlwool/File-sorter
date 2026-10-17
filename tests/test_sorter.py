from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from file_sorter.config import Category, Config, load_config
from file_sorter.sorter import (
    Mode,
    SkipReason,
    resolve_destination,
    sort_folder,
    unique_destination,
)
from tests.conftest import make_files

IMAGE = Category(
    key="image",
    folder="Images",
    system_dir="pictures",
    system_subdir="",
    extensions=frozenset({"jpg"}),
)
ARCHIVE = Category(
    key="archive",
    folder="Archives",
    system_dir="documents",
    system_subdir="Archives",
    extensions=frozenset({"zip"}),
)


class TestUniqueDestination:
    def test_free_name_is_kept(self, tmp_path: Path) -> None:
        assert unique_destination(tmp_path, "a.jpg") == tmp_path / "a.jpg"

    def test_existing_name_gets_counter(self, tmp_path: Path) -> None:
        make_files(tmp_path, "a.jpg")
        assert unique_destination(tmp_path, "a.jpg") == tmp_path / "a_1.jpg"

    def test_counter_skips_taken_numbers(self, tmp_path: Path) -> None:
        make_files(tmp_path, "a.jpg", "a_1.jpg")
        assert unique_destination(tmp_path, "a.jpg") == tmp_path / "a_2.jpg"

    def test_name_without_extension(self, tmp_path: Path) -> None:
        make_files(tmp_path, "notes")
        assert unique_destination(tmp_path, "notes") == tmp_path / "notes_1"

    def test_reserved_names_are_avoided(self, tmp_path: Path) -> None:
        reserved = {tmp_path / "a.jpg"}
        assert unique_destination(tmp_path, "a.jpg", reserved) == tmp_path / "a_1.jpg"

    def test_reserved_counter_names_are_avoided(self, tmp_path: Path) -> None:
        reserved = {tmp_path / "a.jpg", tmp_path / "a_1.jpg"}
        assert unique_destination(tmp_path, "a.jpg", reserved) == tmp_path / "a_2.jpg"


class TestResolveDestination:
    def test_system_mode_uses_system_dir(self, tmp_path: Path) -> None:
        dirs = {"pictures": tmp_path / "Pics"}
        result = resolve_destination(IMAGE, Mode.SYSTEM, tmp_path, None, dirs)
        assert result == tmp_path / "Pics"

    def test_system_mode_adds_subdir(self, tmp_path: Path) -> None:
        dirs = {"documents": tmp_path / "Docs"}
        result = resolve_destination(ARCHIVE, Mode.SYSTEM, tmp_path, None, dirs)
        assert result == tmp_path / "Docs" / "Archives"

    def test_subfolders_mode_is_inside_source(self, tmp_path: Path) -> None:
        result = resolve_destination(IMAGE, Mode.SUBFOLDERS, tmp_path, None, {})
        assert result == tmp_path / "Images"

    def test_custom_mode_is_inside_target(self, tmp_path: Path) -> None:
        target = tmp_path / "out"
        result = resolve_destination(IMAGE, Mode.CUSTOM, tmp_path, target, {})
        assert result == target / "Images"

    def test_custom_mode_requires_target(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="custom"):
            resolve_destination(IMAGE, Mode.CUSTOM, tmp_path, None, {})


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


class TestSortFolder:
    def test_moves_known_file(self, tmp_path: Path, config: Config) -> None:
        make_files(tmp_path, "a.jpg")
        report = sort_folder(tmp_path, config, subfolders(tmp_path))
        assert not (tmp_path / "a.jpg").exists()
        assert (tmp_path / "Images" / "a.jpg").read_text(encoding="utf-8") == "a.jpg"
        assert [m.category for m in report.moved] == ["image"]

    def test_unknown_file_stays(self, tmp_path: Path, config: Config) -> None:
        make_files(tmp_path, "x.unknown", "README")
        report = sort_folder(tmp_path, config, subfolders(tmp_path))
        assert (tmp_path / "x.unknown").exists()
        assert (tmp_path / "README").exists()
        assert {s.reason for s in report.skipped} == {SkipReason.UNKNOWN_TYPE}
        assert len(report.skipped) == 2

    def test_directories_are_ignored(self, tmp_path: Path, config: Config) -> None:
        (tmp_path / "folder.jpg").mkdir()
        report = sort_folder(tmp_path, config, subfolders(tmp_path))
        assert (tmp_path / "folder.jpg").is_dir()
        assert not report.moved
        assert not report.skipped

    def test_file_already_in_place(self, tmp_path: Path, config: Config) -> None:
        make_files(tmp_path, "a.jpg")
        resolve = partial(
            resolve_destination,
            mode=Mode.SYSTEM,
            source=tmp_path,
            target=None,
            system_dirs={"pictures": tmp_path},
        )
        report = sort_folder(tmp_path, config, resolve)
        assert (tmp_path / "a.jpg").exists()
        assert [s.reason for s in report.skipped] == [SkipReason.ALREADY_IN_PLACE]

    def test_collision_does_not_overwrite(self, tmp_path: Path, config: Config) -> None:
        make_files(tmp_path / "Images", "a.jpg")
        (tmp_path / "Images" / "a.jpg").write_text("old", encoding="utf-8")
        make_files(tmp_path, "a.jpg")
        report = sort_folder(tmp_path, config, subfolders(tmp_path))
        assert (tmp_path / "Images" / "a.jpg").read_text(encoding="utf-8") == "old"
        assert (tmp_path / "Images" / "a_1.jpg").read_text(encoding="utf-8") == "a.jpg"
        assert report.moved[0].destination == tmp_path / "Images" / "a_1.jpg"

    def test_dry_run_changes_nothing(self, tmp_path: Path, config: Config) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3")
        report = sort_folder(tmp_path, config, subfolders(tmp_path), dry_run=True)
        assert (tmp_path / "a.jpg").exists()
        assert (tmp_path / "b.mp3").exists()
        assert not (tmp_path / "Images").exists()
        assert not (tmp_path / "Audio").exists()
        assert len(report.moved) == 2

    def test_dry_run_plans_collision_name(self, tmp_path: Path, config: Config) -> None:
        make_files(tmp_path / "Images", "a.jpg")
        make_files(tmp_path, "a.jpg")
        report = sort_folder(tmp_path, config, subfolders(tmp_path), dry_run=True)
        assert report.moved[0].destination == tmp_path / "Images" / "a_1.jpg"

    def test_failure_is_reported_and_others_continue(
        self, tmp_path: Path, config: Config
    ) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3", "Images")  # "Images" - это файл
        report = sort_folder(tmp_path, config, subfolders(tmp_path))
        assert [f.path.name for f in report.failed] == ["a.jpg"]
        assert (tmp_path / "a.jpg").exists()
        assert (tmp_path / "Audio" / "b.mp3").exists()

    def test_missing_folder_raises(self, tmp_path: Path, config: Config) -> None:
        missing = tmp_path / "nope"
        with pytest.raises(NotADirectoryError):
            sort_folder(missing, config, subfolders(missing))

    def test_files_are_processed_in_name_order(
        self, tmp_path: Path, config: Config
    ) -> None:
        make_files(tmp_path, "c.jpg", "a.jpg", "b.jpg")
        report = sort_folder(tmp_path, config, subfolders(tmp_path), dry_run=True)
        assert [m.source.name for m in report.moved] == ["a.jpg", "b.jpg", "c.jpg"]
