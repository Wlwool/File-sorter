import sys

import pytest

from file_sorter.service import ServiceError, default_backend
from file_sorter.service.systemd import SystemdBackend
from file_sorter.service.windows import WindowsTaskBackend


def test_linux_uses_systemd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert isinstance(default_backend(), SystemdBackend)


def test_windows_uses_task_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(default_backend(), WindowsTaskBackend)


def test_other_platforms_are_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(ServiceError, match="watch"):
        default_backend()
