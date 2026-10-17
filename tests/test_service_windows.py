import contextlib
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from file_sorter.service.base import ServiceError, ServiceSpec
from file_sorter.service.windows import (
    TASK_NAME,
    WindowsTaskBackend,
    pythonw_for,
    render_task_xml,
)
from tests.conftest import FakeRunner

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
USER = "PC\\dima"


def field(root: ET.Element, path: str) -> str | None:
    return root.findtext(path, namespaces=NS)


def make_backend(
    runner: FakeRunner, tmp_path: Path, name: str = TASK_NAME
) -> WindowsTaskBackend:
    return WindowsTaskBackend(
        runner, log_file=tmp_path / "logs" / "file-sorter.log", task_name=name
    )


def make_spec(tmp_path: Path) -> ServiceSpec:
    (tmp_path / "python.exe").write_text("", encoding="utf-8")
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    return ServiceSpec(tmp_path / "python.exe", ("--mode", "subfolders", "D:\\Files"))


class TestPythonw:
    def test_pythonw_is_preferred_when_present(self, tmp_path: Path) -> None:
        make_spec(tmp_path)
        assert pythonw_for(tmp_path / "python.exe") == tmp_path / "pythonw.exe"

    def test_falls_back_to_python(self, tmp_path: Path) -> None:
        (tmp_path / "python.exe").write_text("", encoding="utf-8")
        assert pythonw_for(tmp_path / "python.exe") == tmp_path / "python.exe"


class TestRenderTaskXml:
    def render(self, command: str = "C:\\Py\\pythonw.exe") -> ET.Element:
        xml = render_task_xml(Path(command), "-m file_sorter watch", USER)
        return ET.fromstring(xml)

    def test_runs_command_with_arguments(self) -> None:
        root = self.render()
        assert field(root, "t:Actions/t:Exec/t:Command") == "C:\\Py\\pythonw.exe"
        assert field(root, "t:Actions/t:Exec/t:Arguments") == "-m file_sorter watch"

    def test_command_with_spaces_is_quoted(self) -> None:
        root = self.render("C:\\Program Files\\Py\\pythonw.exe")
        command = field(root, "t:Actions/t:Exec/t:Command")
        assert command == '"C:\\Program Files\\Py\\pythonw.exe"'

    def test_starts_at_logon_of_the_user(self) -> None:
        root = self.render()
        assert field(root, "t:Triggers/t:LogonTrigger/t:UserId") == USER
        assert field(root, "t:Principals/t:Principal/t:UserId") == USER
        assert field(root, "t:Principals/t:Principal/t:RunLevel") == "LeastPrivilege"

    def test_is_not_limited_by_time_or_battery(self) -> None:
        root = self.render()
        assert field(root, "t:Settings/t:ExecutionTimeLimit") == "PT0S"
        assert field(root, "t:Settings/t:DisallowStartIfOnBatteries") == "false"
        assert field(root, "t:Settings/t:StopIfGoingOnBatteries") == "false"

    def test_restarts_on_failure(self) -> None:
        root = self.render()
        assert field(root, "t:Settings/t:RestartOnFailure/t:Count") == "3"
        assert field(root, "t:Settings/t:RestartOnFailure/t:Interval") == "PT1M"

    def test_special_characters_are_escaped(self) -> None:
        arguments = '-m file_sorter watch "C:\\A & B\\<x>"'
        xml = render_task_xml(Path("x.exe"), arguments, USER)
        root = ET.fromstring(xml)
        assert field(root, "t:Actions/t:Exec/t:Arguments") == arguments


class TestInstall:
    def test_creates_task_from_xml_and_runs_it(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}

        def on_call(command: tuple[str, ...]) -> None:
            if "/Create" in command:
                path = Path(command[command.index("/XML") + 1])
                captured["path"] = path
                captured["bytes"] = path.read_bytes()

        runner = FakeRunner(on_call=on_call)
        backend = make_backend(runner, tmp_path)
        log_file = tmp_path / "logs" / "file-sorter.log"
        message = backend.install(make_spec(tmp_path))

        create, run = runner.calls
        assert create[:4] == ("schtasks", "/Create", "/TN", TASK_NAME)
        assert "/F" in create
        assert run == ("schtasks", "/Run", "/TN", TASK_NAME)

        data = captured["bytes"]
        assert isinstance(data, bytes)
        assert data.startswith((b"\xff\xfe", b"\xfe\xff"))  # UTF-16 с BOM
        root = ET.fromstring(data)
        command = field(root, "t:Actions/t:Exec/t:Command")
        arguments = field(root, "t:Actions/t:Exec/t:Arguments")
        assert command is not None
        assert command.endswith("pythonw.exe")
        assert arguments is not None
        assert arguments.startswith("-m file_sorter watch --mode subfolders")
        assert "--log-file" in arguments
        assert str(log_file) in arguments

        assert not Path(str(captured["path"])).exists()  # временный XML удалён
        assert (tmp_path / "logs").is_dir()
        assert str(log_file) in message

    def test_failed_run_is_not_fatal(self, tmp_path: Path) -> None:
        runner = FakeRunner({"/Run": (1, "", "task did not start")})
        message = make_backend(runner, tmp_path).install(make_spec(tmp_path))
        assert "следующем входе" in message

    def test_failed_create_gives_manual_steps(self, tmp_path: Path) -> None:
        runner = FakeRunner({"/Create": (1, "", "ERROR: Access is denied.")})
        with pytest.raises(ServiceError) as info:
            make_backend(runner, tmp_path).install(make_spec(tmp_path))
        text = str(info.value)
        assert "Access is denied" in text
        assert "shell:startup" in text
        assert "-m file_sorter watch" in text

    def test_without_schtasks_gives_manual_steps(self, tmp_path: Path) -> None:
        backend = make_backend(FakeRunner(missing=True), tmp_path)
        with pytest.raises(ServiceError, match="shell:startup"):
            backend.install(make_spec(tmp_path))


class TestControl:
    def test_uninstall_ends_and_deletes_task(self, tmp_path: Path) -> None:
        runner = FakeRunner()
        make_backend(runner, tmp_path).uninstall()
        assert runner.calls == [
            ("schtasks", "/Query", "/TN", TASK_NAME),
            ("schtasks", "/End", "/TN", TASK_NAME),
            ("schtasks", "/Delete", "/TN", TASK_NAME, "/F"),
        ]

    def test_uninstall_when_not_installed(self, tmp_path: Path) -> None:
        runner = FakeRunner({"/Query": (1, "", "ERROR: not found")})
        message = make_backend(runner, tmp_path).uninstall()
        assert len(runner.calls) == 1
        assert "не установлена" in message

    def test_start(self, tmp_path: Path) -> None:
        runner = FakeRunner()
        make_backend(runner, tmp_path).start()
        assert runner.calls[-1] == ("schtasks", "/Run", "/TN", TASK_NAME)

    def test_stop_says_autostart_stays(self, tmp_path: Path) -> None:
        runner = FakeRunner()
        message = make_backend(runner, tmp_path).stop()
        assert runner.calls[-1] == ("schtasks", "/End", "/TN", TASK_NAME)
        assert "следующем входе" in message

    @pytest.mark.parametrize("action", ["start", "stop", "status"])
    def test_require_installation(self, action: str, tmp_path: Path) -> None:
        runner = FakeRunner({"/Query": (1, "", "ERROR: not found")})
        with pytest.raises(ServiceError, match="service install"):
            getattr(make_backend(runner, tmp_path), action)()

    def test_failed_start_is_reported(self, tmp_path: Path) -> None:
        runner = FakeRunner({"/Run": (1, "", "no access")})
        with pytest.raises(ServiceError, match="no access"):
            make_backend(runner, tmp_path).start()

    @pytest.mark.parametrize(
        ("state", "word"),
        [("Running", "работает"), ("Ready", "остановлена"), ("Disabled", "отключена")],
    )
    def test_status_by_state(self, state: str, word: str, tmp_path: Path) -> None:
        runner = FakeRunner({"Get-ScheduledTask": (0, f"{state}\r\n", "")})
        text = make_backend(runner, tmp_path).status()
        assert word in text
        assert str(tmp_path / "logs" / "file-sorter.log") in text

    def test_status_with_unknown_state_shows_it(self, tmp_path: Path) -> None:
        runner = FakeRunner({"Get-ScheduledTask": (0, "Queued\n", "")})
        assert "Queued" in make_backend(runner, tmp_path).status()


@pytest.mark.skipif(sys.platform != "win32", reason="нужен настоящий Планировщик")
def test_real_task_scheduler_roundtrip(tmp_path: Path) -> None:
    """Проверяет, что Windows принимает наш XML: создание, статус, удаление."""
    name = f"File-sorter-test-{uuid.uuid4().hex[:8]}"
    backend = WindowsTaskBackend(task_name=name, log_file=tmp_path / "log.txt")
    spec = ServiceSpec(Path(sys.executable), ("--mode", "subfolders", str(tmp_path)))
    try:
        try:
            backend.install(spec)
        except ServiceError as error:
            text = str(error).lower()
            if "denied" in text or "отказано" in text:
                pytest.skip("нет прав на создание заданий в Планировщике")
            raise
        assert backend.status()
    finally:
        with contextlib.suppress(ServiceError):
            backend.uninstall()
    with pytest.raises(ServiceError, match="service install"):
        backend.status()
