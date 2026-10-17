from pathlib import Path

import pytest

from file_sorter import cli
from file_sorter.cli import main
from tests.conftest import make_files


def test_no_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "clean" in capsys.readouterr().out


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
