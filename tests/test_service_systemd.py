import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from file_sorter.service.base import ServiceError, ServiceSpec
from file_sorter.service.systemd import (
    SERVICE_NAME,
    SystemdBackend,
    quote_arg,
    render_unit,
    unit_dir,
)
from tests.conftest import FakeRunner

SYSTEMCTL = ("systemctl", "--user")


def make_spec(tmp_path: Path) -> ServiceSpec:
    return ServiceSpec(Path(sys.executable), ("--mode", "subfolders", str(tmp_path)))


def installed(
    tmp_path: Path, replies: Mapping[str, tuple[int, str, str]] | None = None
) -> tuple[SystemdBackend, FakeRunner]:
    """Backend с уже установленной службой; журнал вызовов очищен."""
    runner = FakeRunner(replies)
    backend = SystemdBackend(runner, directory=tmp_path / "units")
    backend.install(make_spec(tmp_path))
    runner.calls.clear()
    return backend, runner


@pytest.mark.parametrize(
    ("raw", "quoted"),
    [
        ("plain", '"plain"'),
        ("with space", '"with space"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("back\\slash", '"back\\\\slash"'),
        ("100%", '"100%%"'),
        ("$HOME", '"$$HOME"'),
    ],
)
def test_quote_arg(raw: str, quoted: str) -> None:
    assert quote_arg(raw) == quoted


class TestRenderUnit:
    def test_contains_expected_lines(self) -> None:
        text = render_unit(
            ("/usr/bin/python3", "-m", "file_sorter", "watch", "--mode", "system")
        )
        expected = 'ExecStart="/usr/bin/python3" "-m" "file_sorter" "watch" '
        assert expected + '"--mode" "system"\n' in text
        assert "Restart=on-failure" in text
        assert "Environment=PYTHONUNBUFFERED=1" in text
        assert "WantedBy=default.target" in text

    @pytest.mark.skipif(
        shutil.which("systemd-analyze") is None, reason="нет systemd-analyze"
    )
    def test_passes_systemd_verify_with_tricky_path(self, tmp_path: Path) -> None:
        tricky = tmp_path / "dir with space" / '100% $x \\ "q"'
        path = tmp_path / SERVICE_NAME
        path.write_text(
            render_unit((sys.executable, "-m", "file_sorter", "watch", str(tricky))),
            encoding="utf-8",
        )
        result = subprocess.run(
            ["systemd-analyze", "verify", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="XDG_CONFIG_HOME только на Linux")
def test_unit_dir_follows_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert unit_dir() == tmp_path / "systemd" / "user"


class TestInstall:
    def test_writes_unit_and_enables_it(self, tmp_path: Path) -> None:
        runner = FakeRunner()
        backend = SystemdBackend(runner, directory=tmp_path / "units")
        message = backend.install(make_spec(tmp_path))
        unit = tmp_path / "units" / SERVICE_NAME
        assert quote_arg(sys.executable) in unit.read_text(encoding="utf-8")
        assert runner.calls == [
            (*SYSTEMCTL, "daemon-reload"),
            (*SYSTEMCTL, "enable", "--now", SERVICE_NAME),
        ]
        assert "journalctl" in message
        assert "enable-linger" in message

    def test_unit_runs_the_current_python_module(self, tmp_path: Path) -> None:
        backend = SystemdBackend(FakeRunner(), directory=tmp_path / "units")
        backend.install(make_spec(tmp_path))
        text = (tmp_path / "units" / SERVICE_NAME).read_text(encoding="utf-8")
        assert f'"{sys.executable}" "-m" "file_sorter" "watch" "--mode"' in text

    def test_without_systemctl_gives_manual_steps(self, tmp_path: Path) -> None:
        backend = SystemdBackend(FakeRunner(missing=True), directory=tmp_path / "u")
        with pytest.raises(ServiceError) as info:
            backend.install(make_spec(tmp_path))
        text = str(info.value)
        assert str(tmp_path / "u" / SERVICE_NAME) in text
        assert f"systemctl --user enable --now {SERVICE_NAME}" in text
        assert (tmp_path / "u" / SERVICE_NAME).is_file()

    def test_failed_enable_shows_error_and_manual_steps(self, tmp_path: Path) -> None:
        runner = FakeRunner({"enable": (1, "", "Failed to connect to bus")})
        backend = SystemdBackend(runner, directory=tmp_path / "u")
        with pytest.raises(ServiceError) as info:
            backend.install(make_spec(tmp_path))
        text = str(info.value)
        assert "Failed to connect to bus" in text
        assert "daemon-reload" in text


class TestUninstall:
    def test_removes_unit_and_disables_service(self, tmp_path: Path) -> None:
        backend, runner = installed(tmp_path)
        backend.uninstall()
        assert not (tmp_path / "units" / SERVICE_NAME).exists()
        assert runner.calls == [
            (*SYSTEMCTL, "disable", "--now", SERVICE_NAME),
            (*SYSTEMCTL, "daemon-reload"),
        ]

    def test_when_not_installed_does_nothing(self, tmp_path: Path) -> None:
        runner = FakeRunner()
        backend = SystemdBackend(runner, directory=tmp_path / "units")
        message = backend.uninstall()
        assert runner.calls == []
        assert "не установлена" in message

    def test_without_systemctl_tells_what_to_remove(self, tmp_path: Path) -> None:
        installed(tmp_path)  # создаёт файл службы
        broken = SystemdBackend(FakeRunner(missing=True), directory=tmp_path / "units")
        with pytest.raises(ServiceError) as info:
            broken.uninstall()
        assert str(tmp_path / "units" / SERVICE_NAME) in str(info.value)


class TestStartStop:
    @pytest.mark.parametrize("action", ["start", "stop"])
    def test_calls_systemctl(self, action: str, tmp_path: Path) -> None:
        backend, runner = installed(tmp_path)
        getattr(backend, action)()
        assert runner.calls == [(*SYSTEMCTL, action, SERVICE_NAME)]

    def test_stop_says_autostart_stays(self, tmp_path: Path) -> None:
        backend, _ = installed(tmp_path)
        assert "автозапуск" in backend.stop()

    def test_failed_start_is_reported(self, tmp_path: Path) -> None:
        backend, _ = installed(tmp_path, {"start": (1, "", "Unit is masked")})
        # установка уже прошла, поэтому ответ для start действует на новые вызовы
        with pytest.raises(ServiceError, match="Unit is masked"):
            backend.start()

    @pytest.mark.parametrize("action", ["start", "stop", "status"])
    def test_require_installation(self, action: str, tmp_path: Path) -> None:
        backend = SystemdBackend(FakeRunner(), directory=tmp_path / "units")
        with pytest.raises(ServiceError, match="service install"):
            getattr(backend, action)()


class TestStatus:
    def test_running(self, tmp_path: Path) -> None:
        backend, _ = installed(
            tmp_path,
            {"is-active": (0, "active\n", ""), "is-enabled": (0, "enabled\n", "")},
        )
        text = backend.status()
        assert "работает" in text
        assert "включён" in text

    def test_stopped_and_disabled(self, tmp_path: Path) -> None:
        backend, _ = installed(
            tmp_path,
            {"is-active": (3, "inactive\n", ""), "is-enabled": (1, "disabled\n", "")},
        )
        text = backend.status()
        assert "остановлена" in text
        assert "выключен" in text

    def test_failed(self, tmp_path: Path) -> None:
        backend, _ = installed(
            tmp_path,
            {"is-active": (3, "failed\n", ""), "is-enabled": (0, "enabled\n", "")},
        )
        assert "ошибк" in backend.status()

    def test_mentions_journal(self, tmp_path: Path) -> None:
        backend, _ = installed(tmp_path, {"is-active": (0, "active\n", "")})
        assert "journalctl" in backend.status()
