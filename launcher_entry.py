"""Точка входа для сборки AurumLauncher.exe (PyInstaller).

Запуск из исходников: python -m launcher
Сборка:             tools/build_launcher.py
"""

from launcher.ui import main

if __name__ == "__main__":
    main()
