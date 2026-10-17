"""Конфиг категорий: чтение TOML, проверка, определение категории файла."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePath

import platformdirs

from file_sorter.folders import SYSTEM_DIR_NAMES

APP_NAME = "file-sorter"
DEFAULT_CONFIG_NAME = "default_config.toml"


class ConfigError(ValueError):
    """Конфиг нельзя прочитать или он составлен неверно."""


@dataclass(frozen=True, slots=True)
class Category:
    key: str
    folder: str
    system_dir: str
    system_subdir: str
    extensions: frozenset[str]


@dataclass(frozen=True, slots=True)
class Config:
    categories: tuple[Category, ...]

    def category_for(self, filename: str) -> Category | None:
        """Категория по последнему расширению имени; None, если не найдена."""
        extension = Path(filename).suffix.lstrip(".").lower()
        if not extension:
            return None
        for category in self.categories:
            if extension in category.extensions:
                return category
        return None


def user_config_path() -> Path:
    """Где лежит пользовательский конфиг (файл может не существовать)."""
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


def _relative_path(value: object, key: str, field: str, *, required: bool) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"категория {key!r}: поле {field} должно быть строкой")
    if not value:
        if required:
            raise ConfigError(f"категория {key!r}: поле {field} не задано")
        return value
    path = PurePath(value)
    if path.anchor or ".." in path.parts or not path.parts:
        raise ConfigError(
            f"категория {key!r}: поле {field} должно быть простым "
            f"относительным путём, получено {value!r}"
        )
    return value


def _extensions(value: object, key: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise ConfigError(
            f"категория {key!r}: поле extensions должно быть непустым списком"
        )
    result: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(
                f"категория {key!r}: в extensions допустимы только строки"
            )
        extension = item.strip().lstrip(".").lower()
        if not extension:
            raise ConfigError(f"категория {key!r}: в extensions есть пустое значение")
        result.add(extension)
    return frozenset(result)


def parse_config(data: Mapping[str, object]) -> Config:
    """Проверяет данные из TOML и собирает конфиг."""
    raw = data.get("categories")
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("в конфиге нет раздела [categories]")

    owners: dict[str, str] = {}
    categories: list[Category] = []
    for key, table in raw.items():
        if not isinstance(table, dict):
            raise ConfigError(f"категория {key!r} должна быть таблицей")
        folder = _relative_path(table.get("folder"), key, "folder", required=True)
        system_dir = table.get("system_dir")
        if system_dir not in SYSTEM_DIR_NAMES:
            allowed = ", ".join(sorted(SYSTEM_DIR_NAMES))
            raise ConfigError(
                f"категория {key!r}: system_dir должен быть одним из: {allowed}"
            )
        subdir = _relative_path(
            table.get("system_subdir", ""), key, "system_subdir", required=False
        )
        extensions = _extensions(table.get("extensions"), key)
        for extension in sorted(extensions):
            if extension in owners:
                raise ConfigError(
                    f"расширение {extension!r} указано в категориях "
                    f"{owners[extension]!r} и {key!r}"
                )
            owners[extension] = key
        categories.append(Category(key, folder, system_dir, subdir, extensions))
    return Config(tuple(categories))


def load_config(path: Path | None = None) -> Config:
    """Читает конфиг: указанный файл, иначе пользовательский, иначе встроенный."""
    if path is None:
        candidate = user_config_path()
        path = candidate if candidate.is_file() else None

    if path is None:
        source = "встроенный конфиг"
        text = files("file_sorter").joinpath(DEFAULT_CONFIG_NAME).read_text("utf-8")
    else:
        source = str(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ConfigError(f"{source}: не удалось прочитать ({error})") from error

    try:
        return parse_config(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ConfigError) as error:
        raise ConfigError(f"{source}: {error}") from error
