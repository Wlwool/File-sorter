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
