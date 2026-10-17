from pathlib import Path

from file_sorter import folders


def test_default_system_dirs_has_all_names() -> None:
    dirs = folders.default_system_dirs()
    assert set(dirs) == set(folders.SYSTEM_DIR_NAMES)
    assert all(isinstance(path, Path) for path in dirs.values())


def test_default_config_uses_only_known_system_dirs() -> None:
    from file_sorter.config import load_config

    used = {category.system_dir for category in load_config().categories}
    assert used <= folders.SYSTEM_DIR_NAMES
