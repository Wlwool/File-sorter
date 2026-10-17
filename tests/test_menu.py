from collections.abc import Callable, Iterator

import pytest

from file_sorter import menu


def scripted(*answers: str) -> Callable[[str], str]:
    """Подмена input(): отдаёт готовые ответы по очереди."""
    queue: Iterator[str] = iter(answers)

    def ask(prompt: str) -> str:
        return next(queue)

    return ask


def raising(error: type[BaseException], *answers: str) -> Callable[[str], str]:
    """Подмена input(): сначала готовые ответы, потом исключение."""
    queue: Iterator[str] = iter(answers)

    def ask(prompt: str) -> str:
        try:
            return next(queue)
        except StopIteration:
            raise error from None

    return ask


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        pytest.param(("1", "", "1"), ["clean", "--mode", "system"], id="clean-default"),
        pytest.param(
            ("1", "photos", "2"),
            ["clean", "photos", "--mode", "subfolders"],
            id="clean-folder",
        ),
        pytest.param(
            ("2", "", "1"),
            ["clean", "--mode", "system", "--dry-run"],
            id="dry-run",
        ),
        pytest.param(("3", "", "2"), ["watch", "--mode", "subfolders"], id="watch"),
        pytest.param(
            ("1", "src", "3", "out"),
            ["clean", "src", "--mode", "custom", "--target", "out"],
            id="custom-target",
        ),
        pytest.param(
            ("1", "", "3", "", "out"),
            ["clean", "--mode", "custom", "--target", "out"],
            id="custom-empty-target-asked-again",
        ),
        pytest.param(("0",), None, id="exit"),
        pytest.param(("9", "0"), None, id="bad-action-asked-again"),
        pytest.param(
            ("1", "", "7", "1"),
            ["clean", "--mode", "system"],
            id="bad-mode-asked-again",
        ),
        pytest.param(
            ("1", "", ""),
            ["clean", "--mode", "system"],
            id="empty-mode-means-system",
        ),
        pytest.param(
            ("4", "1", "", "2"),
            ["service", "install", "--mode", "subfolders"],
            id="service-install",
        ),
        pytest.param(("4", "2"), ["service", "start"], id="service-start"),
        pytest.param(("4", "3"), ["service", "stop"], id="service-stop"),
        pytest.param(("4", "4"), ["service", "status"], id="service-status"),
        pytest.param(("4", "5"), ["service", "uninstall"], id="service-uninstall"),
        pytest.param(("4", "0", "0"), None, id="service-back-then-exit"),
        pytest.param(
            ("4", "0", "1", "", "1"),
            ["clean", "--mode", "system"],
            id="service-back-then-clean",
        ),
        pytest.param(
            ("4", "9", "4"),
            ["service", "status"],
            id="bad-service-choice-asked-again",
        ),
    ],
)
def test_ask_arguments(answers: tuple[str, ...], expected: list[str] | None) -> None:
    assert menu.ask_arguments(scripted(*answers)) == expected


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
@pytest.mark.parametrize(
    "answers",
    [(), ("1", ""), ("4",)],
    ids=["at-start", "at-mode-question", "in-service-menu"],
)
def test_interrupted_input_means_exit(
    error: type[BaseException], answers: tuple[str, ...]
) -> None:
    assert menu.ask_arguments(raising(error, *answers)) is None


def test_service_install_warns_about_uv_tool_install(
    capsys: pytest.CaptureFixture[str],
) -> None:
    menu.ask_arguments(scripted("4", "1", "", "1"))
    assert "uv tool install" in capsys.readouterr().out
