# File-sorter

Автоматическая сортировка файлов для Linux и Windows.

## Установка

```bash
pip install -r requirements.txt
```

---

## ЧАСТЬ 1: Автоматическая сортировка Downloads (постоянная)

### Описание
Постоянно мониторит папку Downloads и автоматически сортирует новые файлы.

### Linux: Запуск как systemd сервис

Создать файл `~/.config/systemd/user/file_sorter.service`:

```ini
[Unit]
Description=File Sorter Service
After=default.target

[Service]
ExecStart=/usr/bin/python3 /path/to/your/file_sorter.py
Restart=always

[Install]
WantedBy=default.target
```

Активация:
```bash
systemctl --user enable file_sorter.service
systemctl --user start file_sorter.service
```

Остановка:
```bash
systemctl --user stop file_sorter.service
```

### Windows: Запуск вручную

```bash
python file_sorter.py
```

Для остановки: `Ctrl+C`

---

## ЧАСТЬ 2: Одноразовая очистка Downloads + Desktop

### Описание
Один раз сортирует все существующие файлы в папках Downloads и Desktop
Ярлыки на рабочем столе игнорируются.

### Запуск

#### Способ 1: Batch файл (Windows)
Запуск `run_cleanup.bat` и выбор режима.

#### Способ 2: Командная строка

Тестовый режим (показ без перемещения):
```bash
python one_time_cleanup.py --dry-run
```

Реальное перемещение:
```bash
python one_time_cleanup.py
```

---

## Настройка

### Изменить расширения и папки назначения

Редактируйте файл `src/extensions_extended.py`:

```python
file_extensions = {
    'image': ['jpg', 'png', 'gif'],  # добавить свои
    'video': ['mp4', 'mkv', 'avi'],
    # ...
}

destinations = {
    "image": home_directory / "Pictures",      # изменить путь
    "video": home_directory / "Videos",
    # ...
}
```

### Добавить новую категорию

1. Добавить расширения в `file_extensions`
2. Добавить путь назначения в `destinations`

Пример:
```python
file_extensions = {
    'my_category': ['ext1', 'ext2'],
}

destinations = {
    "my_category": home_directory / "Documents" / "MyFolder",
}
```

---

## Перемещение файлов

| Категория | Расширения | Windows путь |
|-----------|-----------|--------------|
| Изображения | jpg, png, gif, svg, webp... | Pictures |
| Видео | mp4, mkv, avi, mov... | Videos |
| Аудио | mp3, flac, wav, aac... | Music |
| Документы | pdf, docx, xlsx, txt... | Documents |
| Архивы | zip, rar, 7z, tar... | Documents/Archives |
| Код | py, js, java, cpp, html... | Documents/Code |
| Программы | exe, msi, dll... | Downloads/Programs |


---

## Требования

- Python 3.7+
- watchdog==6.0.0
