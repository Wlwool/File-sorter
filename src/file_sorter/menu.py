"""Интерактивное меню: вопросы по шагам, на выходе - аргументы команды."""

from collections.abc import Callable, Collection

type Ask = Callable[[str], str]

_MAIN_MENU = """\
Сортировщик файлов
Раскладывает файлы по папкам: картинки к картинкам, музыку к музыке и так далее.

Что сделать?
  1. Разобрать папку сейчас
  2. Показать, что будет сделано (файлы не трогаем)
  3. Следить за папкой и разбирать новые файлы
  4. Служба: работать в фоне при каждом входе в систему
  0. Выход
"""

_SERVICE_MENU = """\
Служба (работает в фоне, запускается при входе в систему):
  1. Установить и запустить
  2. Запустить
  3. Остановить (автозапуск останется)
  4. Показать состояние
  5. Удалить (остановить и убрать автозапуск)
  0. Назад
"""

_MODE_MENU = """\
Куда класть файлы?
  1. В системные папки: картинки в Изображения, музыка в Музыку и т. д.
  2. В подпапки внутри этой же папки (например, Загрузки/Images)
  3. В другую папку, которую вы укажете
"""

_INSTALL_WARNING = (
    "Служба запоминает, откуда запущена программа. Если вы запускали её через "
    "uv run или uvx, сначала установите её командой uv tool install, иначе "
    "служба перестанет работать."
)

_MODES = {"1": "system", "2": "subfolders", "3": "custom"}
_SERVICE_ACTIONS = {"2": "start", "3": "stop", "4": "status", "5": "uninstall"}


def _choose(
    ask: Ask, text: str, valid: Collection[str], *, default: str | None = None
) -> str:
    """Показывает пункты и спрашивает номер, пока не получит верный."""
    print(text)
    prompt = f"Ваш выбор [{default}]: " if default is not None else "Ваш выбор: "
    while True:
        answer = ask(prompt).strip()
        if not answer and default is not None:
            return default
        if answer in valid:
            return answer
        print("Нет такого пункта. Введите число из списка.")


def _ask_folder(ask: Ask, question: str) -> list[str]:
    print(question)
    answer = ask("Enter - папка Загрузки, или впишите путь: ").strip()
    return [answer] if answer else []


def _ask_target(ask: Ask) -> str:
    while True:
        answer = ask("В какую папку раскладывать? Впишите путь: ").strip()
        if answer:
            return answer
        print("Путь не может быть пустым.")


def _ask_sort_options(ask: Ask, folder_question: str) -> list[str]:
    """Папка и режим: общая часть clean, watch и service install."""
    folder = _ask_folder(ask, folder_question)
    mode = _MODES[_choose(ask, _MODE_MENU, _MODES, default="1")]
    options = [*folder, "--mode", mode]
    if mode == "custom":
        options += ["--target", _ask_target(ask)]
    return options


def _ask_service(ask: Ask) -> list[str] | None:
    """Подменю службы; None - выбрано "Назад"."""
    choice = _choose(ask, _SERVICE_MENU, ["0", "1", *_SERVICE_ACTIONS])
    if choice == "0":
        return None
    if choice == "1":
        print(_INSTALL_WARNING)
        return [
            "service",
            "install",
            *_ask_sort_options(ask, "За какой папкой следить?"),
        ]
    return ["service", _SERVICE_ACTIONS[choice]]


def _run(ask: Ask) -> list[str] | None:
    while True:
        choice = _choose(ask, _MAIN_MENU, "01234")
        match choice:
            case "0":
                return None
            case "1":
                return ["clean", *_ask_sort_options(ask, "Какую папку разобрать?")]
            case "2":
                options = _ask_sort_options(ask, "Какую папку разобрать?")
                return ["clean", *options, "--dry-run"]
            case "3":
                return ["watch", *_ask_sort_options(ask, "За какой папкой следить?")]
            case _:
                arguments = _ask_service(ask)
                if arguments is not None:
                    return arguments


def ask_arguments(ask: Ask = input) -> list[str] | None:
    """Задаёт вопросы и возвращает аргументы команды. None - пользователь вышел.
    Ctrl+C и конец ввода (Ctrl+D, закрытый stdin) тоже считаются выходом.
    """
    try:
        return _run(ask)
    except EOFError, KeyboardInterrupt:
        print()
        return None
