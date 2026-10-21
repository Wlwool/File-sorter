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
        pytest.param(("5",), ["undo"], id="undo"),
        pytest.param(("4", "0", "5"), ["undo"], id="service-back-then-undo"),
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
        pytest.param(("6", "1"), ["undo", "--list"], id="history-list"),
        pytest.param(("6", "2", "3"), ["undo", "3"], id="history-undo-number"),
        pytest.param(
            ("6", "2", "0", "abc", "-1", "2"),
            ["undo", "2"],
            id="history-bad-number-asked-again",
        ),
        pytest.param(
            ("6", "9", "1"), ["undo", "--list"], id="bad-history-choice-asked-again"
        ),
        pytest.param(("6", "0", "5"), ["undo"], id="history-back-then-undo"),
        pytest.param(
            ("6", "0", "1", "", "1"),
            ["clean", "--mode", "system"],
            id="history-back-then-clean",
        ),
    ],
)
def test_ask_arguments(answers: tuple[str, ...], expected: list[str] | None) -> None:
    assert menu.ask_arguments(scripted(*answers)) == expected


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
@pytest.mark.parametrize(
    "answers",
    [(), ("1", ""), ("4",), ("6",), ("6", "2")],
    ids=[
        "at-start",
        "at-mode-question",
        "in-service-menu",
        "in-history-menu",
        "at-number-question",
    ],
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


def test_undo_reminds_to_stop_the_service(
    capsys: pytest.CaptureFixture[str],
) -> None:
    menu.ask_arguments(scripted("5"))
    assert "service stop" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["", "12"], ids=["empty", "two-digits"])
def test_main_menu_rejects_answers_that_are_not_one_item(
    answer: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert menu.ask_arguments(scripted(answer, "0")) is None
    assert "Нет такого пункта" in capsys.readouterr().out


def test_history_undo_reminds_to_stop_the_service(
    capsys: pytest.CaptureFixture[str],
) -> None:
    menu.ask_arguments(scripted("6", "2", "1"))
    assert "service stop" in capsys.readouterr().out


def test_history_list_does_not_print_the_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    menu.ask_arguments(scripted("6", "1"))
    assert "service stop" not in capsys.readouterr().out


def test_history_bad_number_is_explained(
    capsys: pytest.CaptureFixture[str],
) -> None:
    menu.ask_arguments(scripted("6", "2", "0", "1"))
    assert "Введите целое число" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("д", True),
        ("да", True),
        ("Д", True),
        ("y", True),
        ("н", False),
        ("нет", False),
        ("Н", False),
        ("n", False),
        ("", True),
        ("  д  ", True),
    ],
)
def test_ask_yes_no_understands_answers(answer: str, expected: bool) -> None:
    assert menu.ask_yes_no(scripted(answer), "Повторить?") is expected


def test_ask_yes_no_default_can_be_no() -> None:
    assert menu.ask_yes_no(scripted(""), "Повторить?", default=False) is False


def test_ask_yes_no_asks_again_on_garbage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert menu.ask_yes_no(scripted("может", "12", "н"), "Повторить?") is False
    assert "Ответьте" in capsys.readouterr().out


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_ask_yes_no_interrupted_input_means_no(error: type[BaseException]) -> None:
    assert menu.ask_yes_no(raising(error), "Повторить?") is False


def test_ask_yes_no_shows_hint_with_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return "н"

    menu.ask_yes_no(ask, "Повторить?")
    assert prompts == ["Повторить? [Д/н]: "]
