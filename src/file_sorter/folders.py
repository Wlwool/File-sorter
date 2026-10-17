"""Системные папки пользователя: Загрузки, Документы, Изображения и т. д."""

from pathlib import Path

import platformdirs

_FINDERS = {
    "documents": platformdirs.user_documents_dir,
    "downloads": platformdirs.user_downloads_dir,
    "music": platformdirs.user_music_dir,
    "pictures": platformdirs.user_pictures_dir,
    "videos": platformdirs.user_videos_dir,
}

SYSTEM_DIR_NAMES = frozenset(_FINDERS)


def default_system_dirs() -> dict[str, Path]:
    """Спрашивает у системы, где лежат стандартные папки пользователя."""
    return {name: Path(find()) for name, find in _FINDERS.items()}
