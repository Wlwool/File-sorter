#!/usr/bin/env bash
# Запуск File-sorter одной командой: при первом запуске uv сам создаёт окружение
# и ставит зависимости. Аргументы передаются программе: ./run.sh clean --dry-run

DIR="$(dirname "$(readlink -f "$0")")"

if ! command -v uv >/dev/null 2>&1; then
    echo "Не найден uv: менеджер Python-проектов, на котором работает программа."
    echo "Установите его одной командой и запустите этот файл снова:"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

status=0
uv run --project "$DIR" file-sorter "$@" || status=$?

# при запуске двойным щелчком окно терминала закрылось бы сразу
if [ "$#" -eq 0 ] && [ -t 0 ]; then
    read -r -p "Нажмите Enter, чтобы закрыть окно..." _
fi
exit "$status"
