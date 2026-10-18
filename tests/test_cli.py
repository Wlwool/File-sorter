from pathlib import Path
from typing import Any

import pytest

from file_sorter import cli, journal, watcher
from file_sorter.cli import main
from file_sorter.sorter import Failed, Moved, Skipped, SkipReason
from tests.conftest import make_files


def test_no_arguments_prints_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "clean" in output
    assert "watch" in output


def test_no_arguments_runs_menu_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_files(tmp_path, "a.jpg")
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(
        cli.menu,
        "ask_arguments",
        lambda: ["clean", str(tmp_path), "--mode", "subfolders"],
    )
    assert main([]) == 0
    assert (tmp_path / "Images" / "a.jpg").exists()
    assert "Запускаю: file-sorter clean" in capsys.readouterr().out


def test_menu_exit_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_files(tmp_path, "a.jpg")
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli.menu, "ask_arguments", lambda: None)
    assert main([]) == 0
    assert (tmp_path / "a.jpg").exists()


class TestWatch:
    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        """Подменяет цикл слежения и запоминает, с чем его вызвали."""
        recorded: list[dict[str, Any]] = []

        def fake(source: Path, config: Any, resolve: Any, **kwargs: Any) -> None:
            recorded.append({"source": source, "resolve": resolve, **kwargs})

        monkeypatch.setattr(cli, "watch_folder", fake)
        return recorded

    def test_passes_arguments(
        self, tmp_path: Path, calls: list[dict[str, Any]]
    ) -> None:
        args = ["watch", str(tmp_path), "--mode", "subfolders", "--settle", "0.5"]
        assert main([*args, "--dry-run"]) == 0
        assert calls[0]["source"] == tmp_path
        assert calls[0]["settle"] == 0.5
        assert calls[0]["dry_run"] is True

    def test_default_settle(self, tmp_path: Path, calls: list[dict[str, Any]]) -> None:
        assert main(["watch", str(tmp_path), "--mode", "subfolders"]) == 0
        assert calls[0]["settle"] == watcher.DEFAULT_SETTLE
        assert calls[0]["dry_run"] is False

    def test_default_folder_is_downloads(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        calls: list[dict[str, Any]],
    ) -> None:
        dirs = {
            name: tmp_path / name
            for name in ("documents", "downloads", "music", "pictures", "videos")
        }
        monkeypatch.setattr(cli, "default_system_dirs", lambda: dirs)
        assert main(["watch"]) == 0
        assert calls[0]["source"] == dirs["downloads"]

    def test_negative_settle_is_usage_error(
        self, tmp_path: Path, calls: list[dict[str, Any]]
    ) -> None:
        with pytest.raises(SystemExit) as info:
            main(["watch", str(tmp_path), "--mode", "subfolders", "--settle", "-1"])
        assert info.value.code == 2
        assert not calls

    def test_custom_mode_without_target_is_usage_error(
        self, tmp_path: Path, calls: list[dict[str, Any]]
    ) -> None:
        with pytest.raises(SystemExit) as info:
            main(["watch", str(tmp_path), "--mode", "custom"])
        assert info.value.code == 2
        assert not calls

    def test_ctrl_c_stops_cleanly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def interrupted(*args: Any, **kwargs: Any) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(cli, "watch_folder", interrupted)
        assert main(["watch", str(tmp_path), "--mode", "subfolders"]) == 0
        assert "Остановлено" in capsys.readouterr().out

    def test_missing_folder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "nope"
        assert main(["watch", str(missing), "--mode", "subfolders"]) == 2
        assert "nope" in capsys.readouterr().err

    def test_prints_moves_and_failures_but_not_skips(
        self,
        tmp_path: Path,
        calls: list[dict[str, Any]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        main(["watch", str(tmp_path), "--mode", "subfolders"])
        capsys.readouterr()
        on_result = calls[0]["on_result"]
        on_result(Moved(tmp_path / "a.jpg", tmp_path / "Images" / "a.jpg", "image"))
        on_result(Skipped(tmp_path / "skipme.xyz", SkipReason.UNKNOWN_TYPE))
        on_result(Failed(tmp_path / "bad.jpg", "нет доступа"))
        captured = capsys.readouterr()
        assert "a.jpg" in captured.out
        assert "skipme.xyz" not in captured.out
        assert "bad.jpg" in captured.err

    def test_batch_is_recorded_in_journal(
        self, tmp_path: Path, calls: list[dict[str, Any]]
    ) -> None:
        make_files(tmp_path / "Images", "a.jpg")
        main(["watch", str(tmp_path), "--mode", "subfolders"])
        on_batch = calls[0]["on_batch"]
        on_batch(
            [
                Moved(tmp_path / "a.jpg", tmp_path / "Images" / "a.jpg", "image"),
                Skipped(tmp_path / "skipme.xyz", SkipReason.UNKNOWN_TYPE),
                Failed(tmp_path / "bad.jpg", "нет доступа"),
            ]
        )
        (run,) = journal.load_runs()
        assert [entry.original.name for entry in run.entries] == ["a.jpg"]

    def test_dry_run_batch_is_not_recorded(
        self, tmp_path: Path, calls: list[dict[str, Any]]
    ) -> None:
        make_files(tmp_path / "Images", "a.jpg")
        main(["watch", str(tmp_path), "--mode", "subfolders", "--dry-run"])
        calls[0]["on_batch"](
            [Moved(tmp_path / "a.jpg", tmp_path / "Images" / "a.jpg", "image")]
        )
        assert journal.load_runs() == []

    def test_batch_without_moves_is_not_recorded(
        self, tmp_path: Path, calls: list[dict[str, Any]]
    ) -> None:
        main(["watch", str(tmp_path), "--mode", "subfolders"])
        calls[0]["on_batch"](
            [
                Skipped(tmp_path / "skipme.xyz", SkipReason.UNKNOWN_TYPE),
                Failed(tmp_path / "bad.jpg", "нет доступа"),
            ]
        )
        assert journal.load_runs() == []


class TestClean:
    def test_subfolders_mode_moves_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3", "x.unknown")
        code = main(["clean", str(tmp_path), "--mode", "subfolders"])
        assert code == 0
        assert (tmp_path / "Images" / "a.jpg").exists()
        assert (tmp_path / "Audio" / "b.mp3").exists()
        assert (tmp_path / "x.unknown").exists()
        assert "Перемещено: 2" in capsys.readouterr().out

    def test_dry_run_moves_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        make_files(tmp_path, "a.jpg")
        code = main(["clean", str(tmp_path), "--mode", "subfolders", "--dry-run"])
        assert code == 0
        assert (tmp_path / "a.jpg").exists()
        assert not (tmp_path / "Images").exists()
        assert "пробный" in capsys.readouterr().out.lower()

    def test_dry_run_summary_says_will_be_moved(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3", "x.unknown")
        code = main(["clean", str(tmp_path), "--mode", "subfolders", "--dry-run"])
        assert code == 0
        output = capsys.readouterr().out
        assert "Будет перемещено: 2" in output
        assert "Перемещено: 2" not in output

    def test_target_implies_custom_mode(self, tmp_path: Path) -> None:
        source = tmp_path / "src"
        target = tmp_path / "out"
        make_files(source, "a.jpg")
        assert main(["clean", str(source), "--target", str(target)]) == 0
        assert (target / "Images" / "a.jpg").exists()

    def test_custom_mode_without_target_is_usage_error(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as info:
            main(["clean", str(tmp_path), "--mode", "custom"])
        assert info.value.code == 2

    def test_target_with_other_mode_is_usage_error(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as info:
            main(["clean", str(tmp_path), "--mode", "system", "--target", "x"])
        assert info.value.code == 2

    def test_missing_folder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "nope"
        assert main(["clean", str(missing), "--mode", "subfolders"]) == 2
        assert "nope" in capsys.readouterr().err

    def test_bad_config(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "bad.toml"
        bad.write_text("[categories", encoding="utf-8")
        make_files(tmp_path / "src", "a.jpg")
        code = main(
            [
                "clean",
                str(tmp_path / "src"),
                "--mode",
                "subfolders",
                "--config",
                str(bad),
            ]
        )
        assert code == 2
        assert "bad.toml" in capsys.readouterr().err
        assert (tmp_path / "src" / "a.jpg").exists()

    def test_custom_config_is_used(self, tmp_path: Path) -> None:
        config_path = tmp_path / "my.toml"
        config_path.write_text(
            '[categories.pics]\nfolder = "Pics"\nsystem_dir = "pictures"\n'
            'extensions = ["jpg"]\n',
            encoding="utf-8",
        )
        source = tmp_path / "src"
        make_files(source, "a.jpg", "b.mp3")
        args = ["clean", str(source), "--mode", "subfolders"]
        assert main([*args, "--config", str(config_path)]) == 0
        assert (source / "Pics" / "a.jpg").exists()
        assert (source / "b.mp3").exists()

    def test_system_mode_and_default_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dirs = {
            name: tmp_path / name
            for name in ("documents", "downloads", "music", "pictures", "videos")
        }
        monkeypatch.setattr(cli, "default_system_dirs", lambda: dirs)
        make_files(dirs["downloads"], "a.jpg", "b.pdf")
        assert main(["clean"]) == 0
        assert (dirs["pictures"] / "a.jpg").exists()
        assert (dirs["documents"] / "b.pdf").exists()

    def test_returns_one_when_a_move_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        make_files(tmp_path, "a.jpg", "Images")  # "Images" - это файл
        code = main(["clean", str(tmp_path), "--mode", "subfolders"])
        assert code == 1
        assert "a.jpg" in capsys.readouterr().err

    def test_records_moves_in_journal(self, tmp_path: Path) -> None:
        make_files(tmp_path, "a.jpg", "b.mp3", "x.unknown")
        main(["clean", str(tmp_path), "--mode", "subfolders"])
        (run,) = journal.load_runs()
        assert [entry.original.name for entry in run.entries] == ["a.jpg", "b.mp3"]
        first = run.entries[0]
        assert first.current == tmp_path / "Images" / "a.jpg"
        assert first.size == first.current.stat().st_size

    def test_dry_run_records_nothing(self, tmp_path: Path, journal_file: Path) -> None:
        make_files(tmp_path, "a.jpg")
        main(["clean", str(tmp_path), "--mode", "subfolders", "--dry-run"])
        assert journal.load_runs() == []
        assert not journal_file.exists()

    def test_nothing_moved_records_nothing(
        self, tmp_path: Path, journal_file: Path
    ) -> None:
        make_files(tmp_path, "x.unknown")
        main(["clean", str(tmp_path), "--mode", "subfolders"])
        assert not journal_file.exists()

    def test_journal_error_does_not_fail_the_sort(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def broken(entries: Any) -> None:
            raise OSError("диск полон")

        monkeypatch.setattr(journal, "append_run", broken)
        make_files(tmp_path, "a.jpg")
        assert main(["clean", str(tmp_path), "--mode", "subfolders"]) == 0
        assert (tmp_path / "Images" / "a.jpg").exists()
        err = capsys.readouterr().err
        assert "журнал" in err
        assert "диск полон" in err
