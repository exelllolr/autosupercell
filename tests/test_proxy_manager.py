"""Тесты для ProxyManager."""

import pytest
from pathlib import Path
from app.core.proxy_manager import ProxyManager
from app.config import settings


@pytest.fixture
def proxy_file(tmp_path):
    """Создать временный файл с прокси."""
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(
        "127.0.0.1:8080\n"
        "user:pass@192.168.1.1:3128\n"
        "10.0.0.2:9000:user2:pass2\n"
        "10.0.0.1:9090\n"
    )
    return proxy_file


def test_load_proxies(proxy_file, monkeypatch):
    """Тест загрузки прокси из файла."""
    monkeypatch.setattr(settings, "PROXY_LIST_FILE", str(proxy_file))
    monkeypatch.setattr(settings, "PROXY_ENABLED", True)
    monkeypatch.setattr(settings, "NOVADA_ENABLED", False)  # изолируем от .env

    manager = ProxyManager()
    assert len(manager.proxies) == 4
    assert manager.proxies[0]["server"] == "http://127.0.0.1:8080"
    assert "username" in manager.proxies[1]
    assert manager.proxies[1]["username"] == "user"
    assert manager.proxies[2]["server"] == "http://10.0.0.2:9000"
    assert manager.proxies[2]["username"] == "user2"


def test_get_proxy(proxy_file, monkeypatch):
    """Тест получения прокси."""
    monkeypatch.setattr(settings, "PROXY_LIST_FILE", str(proxy_file))
    monkeypatch.setattr(settings, "PROXY_ENABLED", True)
    monkeypatch.setattr(settings, "NOVADA_ENABLED", False)

    manager = ProxyManager()
    proxy = manager.get_proxy()
    assert proxy is not None
    assert "server" in proxy


def test_get_proxy_first_only(proxy_file, monkeypatch):
    """Если PROXY_USE_FIRST_ONLY=True — всегда первый прокси."""
    monkeypatch.setattr(settings, "PROXY_LIST_FILE", str(proxy_file))
    monkeypatch.setattr(settings, "PROXY_ENABLED", True)
    monkeypatch.setattr(settings, "PROXY_USE_FIRST_ONLY", True)
    monkeypatch.setattr(settings, "NOVADA_ENABLED", False)

    manager = ProxyManager()
    p1 = manager.get_proxy()
    p2 = manager.get_proxy()
    assert p1["server"] == "http://127.0.0.1:8080"
    assert p2["server"] == "http://127.0.0.1:8080"


def test_get_proxy_sequential_rotation(proxy_file, monkeypatch):
    """При PROXY_ROTATION_ENABLED=False — последовательный выбор прокси."""
    monkeypatch.setattr(settings, "PROXY_LIST_FILE", str(proxy_file))
    monkeypatch.setattr(settings, "PROXY_ENABLED", True)
    monkeypatch.setattr(settings, "PROXY_USE_FIRST_ONLY", False)
    monkeypatch.setattr(settings, "PROXY_ROTATION_ENABLED", False)
    monkeypatch.setattr(settings, "NOVADA_ENABLED", False)

    manager = ProxyManager()
    servers = [manager.get_proxy()["server"] for _ in range(4)]
    assert servers == [
        "http://127.0.0.1:8080",
        "http://192.168.1.1:3128",
        "http://10.0.0.2:9000",
        "http://10.0.0.1:9090",
    ]


def test_mark_proxy_failed(proxy_file, monkeypatch):
    """Тест пометки прокси как провалившегося."""
    monkeypatch.setattr(settings, "PROXY_LIST_FILE", str(proxy_file))
    monkeypatch.setattr(settings, "PROXY_ENABLED", True)
    monkeypatch.setattr(settings, "NOVADA_ENABLED", False)

    manager = ProxyManager()
    proxy = manager.get_proxy()
    manager.mark_proxy_failed(proxy)
    assert len(manager.failed_proxies) == 1


def test_mark_proxy_failed_by_value(proxy_file, monkeypatch):
    """mark_proxy_failed должен работать даже если прокси-словарь не тот же объект."""
    monkeypatch.setattr(settings, "PROXY_LIST_FILE", str(proxy_file))
    monkeypatch.setattr(settings, "PROXY_ENABLED", True)
    monkeypatch.setattr(settings, "PROXY_ROTATION_ENABLED", False)
    monkeypatch.setattr(settings, "NOVADA_ENABLED", False)

    manager = ProxyManager()
    proxy = manager.get_proxy()
    same_value = {
        "server": proxy["server"],
        "username": proxy.get("username", ""),
        "password": proxy.get("password", ""),
    }
    manager.mark_proxy_failed(same_value)
    assert len(manager.failed_proxies) == 1
