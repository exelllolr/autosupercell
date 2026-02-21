"""Скрипт инициализации директорий проекта."""

from pathlib import Path


def init_directories():
    """Создать необходимые директории."""
    directories = [
        "logs",
        "screenshots",
        "proofs",
        "tmp",
    ]

    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
        print(f"✓ Создана директория: {directory}")

    print("\nВсе директории созданы успешно!")


if __name__ == "__main__":
    init_directories()
