from pathlib import Path

import pytest

from file_sorter import config
from file_sorter.config import ConfigError, load_config, parse_config, user_config_path


def one_category(**fields: object) -> dict[str, object]:
    """Минимальный корректный конфиг с одной категорией."""
    table: dict[str, object] = {
        "folder": "Images",
        "system_dir": "pictures",
        "extensions": ["jpg"],
    }
    table.update(fields)
    return {"categories": {"image": table}}


class TestDefaultConfig:
    def test_loads(self) -> None:
        cfg = load_config()
        keys = {category.key for category in cfg.categories}
        assert {"image", "video", "audio", "documents", "code"} <= keys

    def test_ts_is_video(self) -> None:
        category = load_config().category_for("movie.ts")
        assert category is not None
        assert category.key == "video"

    def test_sql_is_code(self) -> None:
        category = load_config().category_for("dump.sql")
        assert category is not None
        assert category.key == "code"


class TestCategoryFor:
    def test_case_insensitive(self) -> None:
        category = load_config().category_for("PHOTO.JPG")
        assert category is not None
        assert category.key == "image"

    @pytest.mark.parametrize("name", ["README", ".bashrc", "file.", "x.unknown"])
    def test_unknown_or_no_extension(self, name: str) -> None:
        assert load_config().category_for(name) is None

    def test_uses_last_suffix(self) -> None:
        category = load_config().category_for("backup.tar.gz")
        assert category is not None
        assert category.key == "archive"


class TestParseConfig:
    def test_extensions_are_normalized(self) -> None:
        cfg = parse_config(one_category(extensions=[".JPG", " Png "]))
        assert cfg.categories[0].extensions == frozenset({"jpg", "png"})

    def test_system_subdir_defaults_to_empty(self) -> None:
        cfg = parse_config(one_category())
        assert cfg.categories[0].system_subdir == ""

    def test_duplicate_extension_is_error(self) -> None:
        data = {
            "categories": {
                "a": {"folder": "A", "system_dir": "pictures", "extensions": ["x"]},
                "b": {"folder": "B", "system_dir": "music", "extensions": ["x"]},
            }
        }
        with pytest.raises(ConfigError, match="'x'"):
            parse_config(data)

    def test_no_categories_is_error(self) -> None:
        with pytest.raises(ConfigError, match="categories"):
            parse_config({})

    def test_missing_folder_is_error(self) -> None:
        data = one_category()
        del data["categories"]["image"]["folder"]  # type: ignore[index]
        with pytest.raises(ConfigError, match="folder"):
            parse_config(data)

    def test_unknown_system_dir_is_error(self) -> None:
        with pytest.raises(ConfigError, match="system_dir"):
            parse_config(one_category(system_dir="nowhere"))

    @pytest.mark.parametrize("value", ["../x", "/abs", ""])
    def test_bad_folder_is_error(self, value: str) -> None:
        with pytest.raises(ConfigError, match="folder"):
            parse_config(one_category(folder=value))

    def test_bad_system_subdir_is_error(self) -> None:
        with pytest.raises(ConfigError, match="system_subdir"):
            parse_config(one_category(system_subdir="../x"))

    @pytest.mark.parametrize("value", [[], "jpg", [""], [1]])
    def test_bad_extensions_is_error(self, value: object) -> None:
        with pytest.raises(ConfigError, match="extensions"):
            parse_config(one_category(extensions=value))


class TestLoadConfig:
    def test_explicit_path(self, tmp_path: Path) -> None:
        path = tmp_path / "my.toml"
        path.write_text(
            '[categories.pics]\nfolder = "Pics"\nsystem_dir = "pictures"\n'
            'extensions = ["jpg"]\n',
            encoding="utf-8",
        )
        cfg = load_config(path)
        assert [category.key for category in cfg.categories] == ["pics"]

    def test_missing_explicit_path_is_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError):
            load_config(tmp_path / "nope.toml")

    def test_invalid_toml_is_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.toml"
        path.write_text("[categories", encoding="utf-8")
        with pytest.raises(ConfigError, match="bad.toml"):
            load_config(path)

    def test_error_names_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.toml"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ConfigError, match="empty.toml"):
            load_config(path)

    def test_user_config_is_used_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = tmp_path / "config.toml"
        user.write_text(
            '[categories.pics]\nfolder = "Pics"\nsystem_dir = "pictures"\n'
            'extensions = ["jpg"]\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(config, "user_config_path", lambda: user)
        assert [c.key for c in load_config().categories] == ["pics"]

    def test_default_is_used_without_user_config(self) -> None:
        keys = {category.key for category in load_config().categories}
        assert "video" in keys


class TestUserConfigPath:
    def test_asks_platformdirs_without_author_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, object]] = []

        def fake(appname: str, appauthor: object = None) -> str:
            calls.append((appname, appauthor))
            return str(tmp_path)

        monkeypatch.setattr(config.platformdirs, "user_config_dir", fake)
        assert user_config_path() == tmp_path / "config.toml"
        assert calls == [("file-sorter", False)]
