"""
Демо Clash Royale через GoLogin: ручной вход в аккаунт → покупка → Google Pay.

Тот же сценарий, что examples/manual_login_gpay_demo.py, с дефолтами для Clash Royale.
Браузер запускается через GoLogin при наличии GOLOGIN_API_TOKEN и GOLOGIN_PROFILE_ID в .env.

Запуск из корня проекта:
  python -m gologin_runner.manual_login_gpay_demo_clash_royale
  python -m gologin_runner.manual_login_gpay_demo_clash_royale --product "80 Gems"
  python -m gologin_runner.manual_login_gpay_demo_clash_royale --product "1200 Gems"
С прокси: python -m gologin_runner.manual_login_gpay_demo_clash_royale (уберите --no-proxy из дефолтов ниже или передайте без --no-proxy)
"""

import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_examples_dir = _project_root / "examples"
for _p in (_project_root, _examples_dir):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

os.environ.setdefault("BROWSER_HEADLESS", "false")

# Дефолты для Clash Royale; прокси из .env (Novada и др.) используются по умолчанию
_argv = list(sys.argv[1:])
if "--game" not in _argv and "-g" not in _argv:
    _argv = ["--game", "clash-royale"] + _argv
if "--product" not in _argv and "-p" not in _argv:
    _argv = ["--product", "500 Gems"] + _argv
# Без --no-proxy: используем свои прокси (NOVADA_* / PROXY_*). Для запуска без прокси добавьте --no-proxy.

sys.argv = [sys.argv[0]] + _argv

from manual_login_gpay_demo import main

if __name__ == "__main__":
    main()
