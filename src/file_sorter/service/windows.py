"""Служба для Windows: задание Планировщика, запускаемое при входе в систему."""

import getpass
import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape

import platformdirs

from file_sorter.service.base import Runner, ServiceError, ServiceSpec, run_command

TASK_NAME = "File-sorter"

_STATE_TEXT = {
    "Running": "работает",
    "Ready": "остановлена (запустится при следующем входе в систему)",
    "Disabled": "отключена",
}


def pythonw_for(python: Path) -> Path:
    """pythonw.exe того же окружения: он запускает программу без окна консоли."""
    candidate = python.with_name("pythonw.exe")
    return candidate if candidate.exists() else python


def current_user() -> str:
    name = getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{name}" if domain else name


def default_log_file() -> Path:
    log_dir = platformdirs.user_log_dir("file-sorter", appauthor=False)
    return Path(log_dir) / "file-sorter.log"


def render_task_xml(command: Path, arguments: str, user: str) -> str:
    """XML задания: запуск при входе пользователя, без ограничений по времени
    и по питанию от батареи, с перезапуском при сбое.

    Через XML, а не через /tr: у /tr лимит длины пути, а время работы
    по умолчанию ограничено.
    """
    command_text = f'"{command}"' if " " in str(command) else str(command)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>File-sorter: автоматическая сортировка файлов</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command_text)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


class WindowsTaskBackend:
    def __init__(
        self,
        runner: Runner = run_command,
        log_file: Path | None = None,
        task_name: str = TASK_NAME,
    ) -> None:
        self._runner = runner
        self._log_file = log_file
        self._name = task_name

    @property
    def log_file(self) -> Path:
        return self._log_file if self._log_file is not None else default_log_file()

    def _run(
        self, args: Sequence[str], manual: str = ""
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._runner(tuple(args))
        except FileNotFoundError as error:
            raise ServiceError(
                f"Не найдена программа {args[0]}.\n{manual}".rstrip()
            ) from error

    def _exists(self) -> bool:
        return self._run(("schtasks", "/Query", "/TN", self._name)).returncode == 0

    def _require_installed(self) -> None:
        if not self._exists():
            raise ServiceError(
                "Служба не установлена. Установите её: file-sorter service install"
            )

    def install(self, spec: ServiceSpec) -> str:
        python = pythonw_for(spec.python)
        log_file = self.log_file
        arguments = subprocess.list2cmdline(
            [
                "-m",
                "file_sorter",
                "watch",
                *spec.watch_args,
                "--log-file",
                str(log_file),
            ]
        )
        manual = (
            "Вручную: нажмите Win+R, введите shell:startup и создайте в открывшейся "
            "папке ярлык со следующей командой:\n"
            f'  "{python}" {arguments}\n'
            "(pythonw работает без окна консоли, вывод пишется в файл журнала)"
        )
        log_file.parent.mkdir(parents=True, exist_ok=True)
        xml = render_task_xml(python, arguments, current_user())
        with tempfile.TemporaryDirectory() as folder:
            xml_path = Path(folder) / "file-sorter-task.xml"
            xml_path.write_text(xml, encoding="utf-16")
            created = self._run(
                ("schtasks", "/Create", "/TN", self._name, "/XML", str(xml_path), "/F"),
                manual,
            )
        if created.returncode != 0:
            detail = (created.stderr or created.stdout).strip()
            raise ServiceError(
                f"Не удалось создать задание в Планировщике: {detail}\n{manual}"
            )
        started = self._run(("schtasks", "/Run", "/TN", self._name)).returncode == 0
        head = (
            "Служба установлена и запущена."
            if started
            else "Задание создано, но сейчас не запустилось: оно запустится "
            "при следующем входе в систему."
        )
        return (
            f"{head}\n"
            "Остановить: file-sorter service stop\n"
            "Состояние: file-sorter service status\n"
            f"Журнал: {log_file}"
        )

    def uninstall(self) -> str:
        if not self._exists():
            return "Служба не установлена."
        self._run(("schtasks", "/End", "/TN", self._name))  # может не работать
        deleted = self._run(("schtasks", "/Delete", "/TN", self._name, "/F"))
        if deleted.returncode != 0:
            detail = (deleted.stderr or deleted.stdout).strip()
            raise ServiceError(f"Не удалось удалить задание: {detail}")
        return "Служба остановлена и удалена."

    def start(self) -> str:
        self._require_installed()
        result = self._run(("schtasks", "/Run", "/TN", self._name))
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ServiceError(f"Не удалось запустить задание: {detail}")
        return "Служба запущена."

    def stop(self) -> str:
        self._require_installed()
        self._run(("schtasks", "/End", "/TN", self._name))  # уже остановлена - не беда
        return (
            "Служба остановлена, автозапуск остаётся: при следующем входе в "
            "систему она запустится снова. Убрать автозапуск: "
            "file-sorter service uninstall"
        )

    def status(self) -> str:
        self._require_installed()
        name = self._name.replace("'", "''")
        result = self._run(
            (
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"(Get-ScheduledTask -TaskName '{name}' -ErrorAction Stop).State",
            )
        )
        state = result.stdout.strip() if result.returncode == 0 else ""
        text = _STATE_TEXT.get(state, state or "не удалось определить")
        return f"Служба: {text}\nЖурнал: {self.log_file}"
