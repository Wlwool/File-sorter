import os
import subprocess
import sys
from pathlib import Path


def test_module_runs_the_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "file_sorter"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert "clean" in result.stdout


def test_module_passes_the_exit_code_through(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "file_sorter", "clean", str(tmp_path / "nope")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 2


def test_output_survives_a_narrow_console_encoding(tmp_path: Path) -> None:
    # на Windows при выводе в файл кодировка бывает cp1252
    # и русский текст не печатается, ASCII воспроизводит то же на Linux
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    env.pop("PYTHONUTF8", None)
    for args in ([], ["clean", str(tmp_path / "nope")]):
        result = subprocess.run(
            [sys.executable, "-m", "file_sorter", *args],
            capture_output=True,
            env=env,
            check=False,
        )
        assert b"UnicodeEncodeError" not in result.stderr
        assert result.returncode in (0, 2)
        assert result.stdout or result.stderr
