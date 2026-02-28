"""
Демо Clash Royale: тот же сценарий, что manual_login_gpay_demo.py, с дефолтами для Clash Royale.

Переход в магазин clash-royale → поиск товара (по умолчанию «500 Gems») → Buy → корзина → Checkout → Google Pay.

Запуск (по умолчанию без прокси, чтобы store.supercell.com не таймаутил):
  python examples/manual_login_gpay_demo_clash_royale.py
  python examples/manual_login_gpay_demo_clash_royale.py --product "80 Gems"
  python examples/manual_login_gpay_demo_clash_royale.py --product "1200 Gems"
С прокси: python examples/manual_login_gpay_demo.py --game clash-royale --product "80 Gems"
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_examples_dir = Path(__file__).resolve().parent
for _p in (_project_root, _examples_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Подставляем дефолты для Clash Royale, если не переданы
# По умолчанию --no-proxy: через Novada/прокси store.supercell.com часто даёт ERR_TIMED_OUT
_argv = list(sys.argv[1:])
if "--game" not in _argv and "-g" not in _argv:
    _argv = ["--game", "clash-royale"] + _argv
if "--product" not in _argv and "-p" not in _argv:
    _argv = ["--product", "500 Gems"] + _argv
if "--no-proxy" not in _argv:
    _argv = ["--no-proxy"] + _argv

sys.argv = [sys.argv[0]] + _argv

# Запуск того же main, что и в manual_login_gpay_demo
from manual_login_gpay_demo import main

if __name__ == "__main__":
    main()
