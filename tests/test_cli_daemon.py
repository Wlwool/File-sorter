import signal
import sys
from pathlib import Path
from typing import Any

import pytest

from file_sorter import cli
from file_sorter.cli import main
from file_sorter.service import ServiceError, ServiceSpec
from file_sorter.watcher import DEFAULT_SETTLE

VALID_CONFIG = '[categories.pics]\nfolder = "Pics"\nsystem_dir = "pictures"\nextensions = ["jpg"]\n'


class FakeBackend:
    """Подмена службы: запоминает вызовы."""

    def __init__(self, error: str | None = None) -> None:
        self.calls: list[str] = []
        self.spec: ServiceSpec | None = None
        self._error = error

    def _act(self, action: str) -> str:
        self.calls.append(action)
        if self._error is not None:
            raise ServiceError(self._error)
        return f"MSG-{action}"

    def install(self, spec: ServiceSpec) -> str:
        self.spec = spec
        return self._act("install")

    def uninstall(self) -> str:
        return self._act("uninstall")

    def start(self) -> str:
        return self._act("start")

    def stop(self) -> str:
        return self._act("stop")

    def status(self) -> str:
        return self._act("status")


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    fake = FakeBackend()
    monkeypatch.setattr(cli, "default_backend", lambda: fake)
    return fake


def test_help_lists_service(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "service" in capsys.readouterr().out


class TestServiceInstall:
    def test_records_all_options(self, tmp_path: Path, backend: FakeBackend) -> None:
        folder = tmp_path / "in"
        folder.mkdir()
        config = tmp_path / "my.toml"
        config.write_text(VALID_CONFIG, encoding="utf-8")
        target = tmp_path / "out"
        args = ["service", "install", str(folder), "--mode", "custom"]
        args += ["--target", str(target), "--config", str(config), "--settle", "3"]
        assert main(args) == 0
        assert backend.spec is not None
        assert backend.spec.python == Path(sys.executable)
        assert backend.spec.watch_args == (
            str(folder.resolve()),
            "--mode",
            "custom",
            "--settle",
            "3",
            "--target",
            str(target.resolve()),
            "--config",
            str(config.resolve()),
        )

    def test_relative_paths_become_absolute(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        backend: FakeBackend,
    ) -> None:
        # у службы другая рабочая папка, поэтому пути должны быть абсолютными
        (tmp_path / "in").mkdir()
        (tmp_path / "my.toml").write_text(VALID_CONFIG, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        args = ["service", "install", "in", "--mode", "custom", "--target", "out"]
        assert main([*args, "--config", "my.toml"]) == 0
        assert backend.spec is not None
        watch_args = backend.spec.watch_args
        assert watch_args[0] == str((tmp_path / "in").resolve())
        assert str((tmp_path / "out").resolve()) in watch_args
        assert str((tmp_path / "my.toml").resolve()) in watch_args

    def test_defaults(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        backend: FakeBackend,
    ) -> None:
        dirs = {
            name: tmp_path / name
            for name in ("documents", "downloads", "music", "pictures", "videos")
        }
        dirs["downloads"].mkdir()
        monkeypatch.setattr(cli, "default_system_dirs", lambda: dirs)
        assert main(["service", "install"]) == 0
        assert backend.spec is not None
        assert backend.spec.watch_args == (
            "--mode",
            "system",
            "--settle",
            f"{DEFAULT_SETTLE:g}",
        )

    def test_prints_backend_message(
        self,
        tmp_path: Path,
        backend: FakeBackend,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(["service", "install", str(tmp_path), "--mode", "subfolders"]) == 0
        assert "MSG-install" in capsys.readouterr().out

    def test_missing_folder_is_not_installed(
        self,
        tmp_path: Path,
        backend: FakeBackend,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        missing = tmp_path / "nope"
        assert main(["service", "install", str(missing)]) == 2
        assert "nope" in capsys.readouterr().err
        assert backend.calls == []

    def test_bad_config_is_not_installed(
        self,
        tmp_path: Path,
        backend: FakeBackend,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        bad = tmp_path / "bad.toml"
        bad.write_text("[categories", encoding="utf-8")
        assert main(["service", "install", str(tmp_path), "--config", str(bad)]) == 2
        assert "bad.toml" in capsys.readouterr().err
        assert backend.calls == []

    def test_custom_mode_without_target_is_usage_error(
        self, tmp_path: Path, backend: FakeBackend
    ) -> None:
        with pytest.raises(SystemExit) as info:
            main(["service", "install", str(tmp_path), "--mode", "custom"])
        assert info.value.code == 2
        assert backend.calls == []

    def test_negative_settle_is_usage_error(
        self, tmp_path: Path, backend: FakeBackend
    ) -> None:
        with pytest.raises(SystemExit) as info:
            main(["service", "install", str(tmp_path), "--settle", "-1"])
        assert info.value.code == 2
        assert backend.calls == []


class TestServiceActions:
    @pytest.mark.parametrize("action", ["start", "stop", "status", "uninstall"])
    def test_dispatch(
        self,
        action: str,
        backend: FakeBackend,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(["service", action]) == 0
        assert backend.calls == [action]
        assert f"MSG-{action}" in capsys.readouterr().out

    def test_service_error_is_reported(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        failing = FakeBackend(error="не получилось, сделайте вручную")
        monkeypatch.setattr(cli, "default_backend", lambda: failing)
        assert main(["service", "stop"]) == 1
        assert "сделайте вручную" in capsys.readouterr().err

    def test_unsupported_platform_is_reported(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def unsupported() -> FakeBackend:
            raise ServiceError("эта система не поддерживается")

        monkeypatch.setattr(cli, "default_backend", unsupported)
        assert main(["service", "status"]) == 1
        assert "не поддерживается" in capsys.readouterr().err

    def test_action_is_required(self) -> None:
        with pytest.raises(SystemExit) as info:
            main(["service"])
        assert info.value.code == 2


class TestWatchAsDaemon:
    def test_log_file_receives_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def noisy(*args: Any, **kwargs: Any) -> None:
            print("внутри слежения")

        monkeypatch.setattr(cli, "watch_folder", noisy)
        log = tmp_path / "logs" / "daemon.log"
        before = sys.stdout, sys.stderr
        args = ["watch", str(tmp_path), "--mode", "subfolders", "--log-file", str(log)]
        assert main(args) == 0
        assert (sys.stdout, sys.stderr) == before
        text = log.read_text(encoding="utf-8")
        assert "Папка:" in text
        assert "Слежение запущено" in text
        assert "внутри слежения" in text

    def test_log_file_is_appended(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "watch_folder", lambda *a, **k: None)
        log = tmp_path / "daemon.log"
        args = ["watch", str(tmp_path), "--mode", "subfolders", "--log-file", str(log)]
        main(args)
        main(args)
        assert log.read_text(encoding="utf-8").count("Слежение запущено") == 2

    def test_sigterm_stops_cleanly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def terminated(*args: Any, **kwargs: Any) -> None:
            signal.raise_signal(signal.SIGTERM)

        def sentinel(signum: int, frame: Any) -> None:
            pass

        monkeypatch.setattr(cli, "watch_folder", terminated)
        original = signal.signal(signal.SIGTERM, sentinel)
        try:
            assert main(["watch", str(tmp_path), "--mode", "subfolders"]) == 0
            assert "Остановлено" in capsys.readouterr().out
            assert signal.getsignal(signal.SIGTERM) is sentinel
        finally:
            signal.signal(
                signal.SIGTERM, original if original is not None else signal.SIG_DFL
            )
