"""Автозапуск: установка и управление фоновой службой слежения."""

import sys

from file_sorter.service.base import (
    Runner,
    ServiceBackend,
    ServiceError,
    ServiceSpec,
    run_command,
)
from file_sorter.service.systemd import SystemdBackend
from file_sorter.service.windows import WindowsTaskBackend

__all__ = [
    "Runner",
    "ServiceBackend",
    "ServiceError",
    "ServiceSpec",
    "SystemdBackend",
    "WindowsTaskBackend",
    "default_backend",
    "run_command",
]


def default_backend() -> ServiceBackend:
    """Служба для текущей системы."""
    if sys.platform.startswith("linux"):
        return SystemdBackend()
    if sys.platform == "win32":
        return WindowsTaskBackend()
    raise ServiceError(
        "Автозапуск поддерживается на Linux (systemd) и Windows. "
        "На этой системе запускайте слежение вручную: file-sorter watch"
    )
