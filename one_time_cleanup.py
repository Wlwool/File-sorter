"""
Скрипт для одноразовой сортировки файлов в папках Загрузки и Рабочий стол.
python one_time_cleanup.py # Обычный запуск.
python one_time_cleanup.py --dry-run # Тестовый режим (без перемещения)
"""
import sys
from pathlib import Path
from shutil import move
from typing import List
import argparse
from src.file_categorizer import get_file_category
from src.extensions_extended import file_extensions, destinations


class OneTimeSorter:
    """Класс для одноразовой сортировки файлов"""
    def __init__(self, dry_run:bool=False):
        """
        :param dry_run: Если True, только показывает что будет сделано, без перемещения файлов
        """
        self.dry_run = dry_run
        self.stats = {
            'total_files': 0,
            'moved_files': 0,
            'skipped_files': 0,
            'errors': 0,
            'shortcuts_skipped': 0
        }
        # папки для обработки
        self.home_directory = Path.home()
        self.folders_to_clean = [
            self.home_directory / 'Downloads',
            self.home_directory / 'Desktop'
        ]

    def is_shortcut(self, file_path: Path) -> bool:
        """
        Поверка, является ли файл ярлыком
        """
        return file_path.suffix == '.lnk'

    def get_files_from_folder(self, folder_path: Path) -> List[Path]:
        """
        Получает список всех файлов в папке
        :param folder_path: путь к папке
        :return: список путей к файлам
        """
        if not folder_path.exists():
            print(f"Папка {folder_path} не существует")
        files = []
        for i in folder_path.iterdir():
            if i.is_file():
                files.append(i)
        return files

    def sort_file(self, file_path: Path) -> bool:
        """Сортирует файл"""
        # пропуск ярлыка
        if self.is_shortcut(file_path):
            print(f"Пропуск ярлыка {file_path.name}")
            self.stats['shortcuts_skipped'] += 1
            return False
        # определение категории файла
        category = get_file_category(file_path.name, file_extensions)
        if not category or category not in destinations:
            print(f"Неизвестный тип файла: {file_path.name}")
            self.stats['skipped_files'] += 1
            return False
        # получение путей назначения
        destination_folder = destinations[category]
        destination_file = destination_folder / file_path.name

        # проверка на нахождение файла в нужной папке
        if file_path.parent == destination_folder:
            print(f"Файл уже в нужной папке: {file_path.name}")
            self.stats['skipped_files'] += 1
            return False
        # если файл с таким именем существует, то добавляется номер
        if destination_file.exists():
            counter = 1
            stem = file_path.stem
            suffix = file_path.suffix
            while destination_file.exists():
                new_name = f"{stem}_{counter}{suffix}"
                destination_file = destination_folder / new_name
                counter += 1
        # режим тестирования или реальное перемещение
        if self.dry_run:
            print(f"Переместить {file_path.name} --> {destination_folder}")
            self.stats['moved_files'] += 1
            return True

        # создание папки назначения если её нет
        try:
            destination_folder.mkdir(parents=True, exist_ok=True)
            # перемещение файла
            move(str(file_path), str(destination_file))
            print(f"Перемещен {file_path.name} --> {destination_folder}")
            self.stats['moved_files'] += 1
            return True
        except Exception as e:
            print(f"[X] Ошибка при перемещении {file_path.name}: {e}")
            self.stats['errors'] += 1
            return False

    def run(self):
        """Запуск сортировки"""
        print(f"Начало сортировки файлов")
        if self.dry_run:
            print("Режим тестирования - файлы не будут перемещены!")
            print()

        # обработка каждой папки
        for folder in self.folders_to_clean:
            print(f"\n[ ] Обработка папки: {folder}")
            print("**" * 10)

            files = self.get_files_from_folder(folder)
            if not files:
                print("[ ] Папка пуста или не содержит файлов")
                continue
            print(f"Файлов не найдено: {len(files)}")
            print()

            for filepath in files:
                self.stats['total_files'] += 1
                self.sort_file(filepath)
        # вывод статистики
        self.print_statistics()

    def print_statistics(self):
        """Вывод статистики выполнения"""
        print(f"Статистика: \n")
        print(f"Всего файлов обработано: {self.stats['total_files']}")
        print(f"Перемещено: {self.stats['moved_files']}")
        print(f"Пропущено (ярлыки): {self.stats['shortcuts_skipped']}")
        print(f"Пропущено (другие файлы): {self.stats['skipped_files']}")
        print(f"Ошибок: {self.stats['errors']}")
        print()

        if self.dry_run:
            print("Это тестовый запуск. Чтобы действительно переместить файлы,")
            print("   запустите скрипт без параметра --dry-run")


def main():
    parser = argparse.ArgumentParser(
        description='Сортировка файлов в папках Загрузки и Рабочий стол'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Тестовый режим - показать что будет сделано, без перемещения файлов'
    )

    args = parser.parse_args()

    # Создание экземпляра сортировщика и запуск
    sorter = OneTimeSorter(dry_run=args.dry_run)

    try:
        sorter.run()
    except KeyboardInterrupt:
        print("Операция прервана пользователем")
        sys.exit(0)


if __name__ == '__main__':
    main()

