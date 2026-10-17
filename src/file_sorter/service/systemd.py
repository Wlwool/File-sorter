"""Служба для Linux: пользовательский unit systemd."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

import platformdirs

from file_sorter.service.base import Runner, ServiceError, ServiceSpec, run_command

SERVICE_NAME = "file-sorter.service"

_STATE_TEXT = {
    "active": "работает",
    "inactive": "остановлена",
    "failed": "завершилась с ошибкой",
    "activating": "запускается",
}
_ENABLED_TEXT = {"enabled": "включён", "disabled": "выключен"}


def unit_dir() -> Path:
    """Папка пользовательских unit-файлов (учитывает XDG_CONFIG_HOME)."""
    return Path(platformdirs.user_config_dir()) / "systemd" / "user"


def quote_arg(arg: str) -> str:
    """Аргумент для ExecStart: в кавычках, с экранированием \\, \", % и $."""
    escaped = (
        arg.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
        .replace("$", "$$")
    )
    return f'"{escaped}"'


def render_unit(command: Sequence[str]) -> str:
    """Текст unit-файла, запускающего command."""
    exec_start = " ".join(quote_arg(part) for part in command)
    return (
        "[Unit]\n"
        "Description=File-sorter: автоматическая сортировка файлов\n"
        "\n"
        "[Service]\n"
        f"ExecStart={exec_start}\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


class SystemdBackend:
    def __init__(
        self, runner: Runner = run_command, directory: Path | None = None
    ) -> None:
        self._runner = runner
        self._directory = directory

    @property
    def unit_file(self) -> Path:
        directory = self._directory if self._directory is not None else unit_dir()
        return directory / SERVICE_NAME

    def _systemctl(
        self, *args: str, manual: str = ""
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._runner(("systemctl", "--user", *args))
        except FileNotFoundError as error:
            raise ServiceError(
                f"Не найдена программа systemctl (systemd).\n{manual}".rstrip()
            ) from error

    def _checked(self, *args: str, manual: str = "") -> None:
        result = self._systemctl(*args, manual=manual)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ServiceError(
                f"systemctl --user {' '.join(args)} не выполнилась: {detail}\n{manual}"
            )

    def _require_installed(self) -> None:
        if not self.unit_file.is_file():
            raise ServiceError(
                "Служба не установлена. Установите её: file-sorter service install"
            )

    def install(self, spec: ServiceSpec) -> str:
        command = (str(spec.python), "-m", "file_sorter", "watch", *spec.watch_args)
        self.unit_file.parent.mkdir(parents=True, exist_ok=True)
        self.unit_file.write_text(render_unit(command), encoding="utf-8")
        manual = (
            f"Файл службы создан: {self.unit_file}\n"
            "Выполните в терминале:\n"
            "  systemctl --user daemon-reload\n"
            f"  systemctl --user enable --now {SERVICE_NAME}"
        )
        self._checked("daemon-reload", manual=manual)
        self._checked("enable", "--now", SERVICE_NAME, manual=manual)
        return (
            f"Служба установлена и запущена: {self.unit_file}\n"
            "Остановить: file-sorter service stop\n"
            "Состояние: file-sorter service status\n"
            f"Журнал: journalctl --user -u {SERVICE_NAME} -f\n"
            "Служба стартует при входе в систему. Чтобы она запускалась при "
            "загрузке без входа, выполните один раз: loginctl enable-linger"
        )

    def uninstall(self) -> str:
        if not self.unit_file.is_file():
            return "Служба не установлена."
        manual = (
            "Остановите и отключите службу вручную, затем удалите файл "
            f"{self.unit_file}:\n"
            f"  systemctl --user disable --now {SERVICE_NAME}"
        )
        self._checked("disable", "--now", SERVICE_NAME, manual=manual)
        self.unit_file.unlink()
        self._checked("daemon-reload", manual=manual)
        return "Служба остановлена и удалена."

    def start(self) -> str:
        self._require_installed()
        self._checked("start", SERVICE_NAME)
        return "Служба запущена."

    def stop(self) -> str:
        self._require_installed()
        self._checked("stop", SERVICE_NAME)
        return (
            "Служба остановлена, автозапуск остаётся: при следующем входе в "
            "систему она запустится снова. Убрать автозапуск: "
            "file-sorter service uninstall"
        )

    def status(self) -> str:
        self._require_installed()
        active = self._systemctl("is-active", SERVICE_NAME).stdout.strip()
        enabled = self._systemctl("is-enabled", SERVICE_NAME).stdout.strip()
        state = _STATE_TEXT.get(active, active or "неизвестно")
        autostart = _ENABLED_TEXT.get(enabled, enabled or "неизвестно")
        return (
            f"Служба: {state}\n"
            f"Автозапуск: {autostart}\n"
            f"Журнал: journalctl --user -u {SERVICE_NAME} -f"
        )
