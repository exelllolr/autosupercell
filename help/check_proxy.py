"""
Проверка чистоты прокси перед покупкой.
Проверяет ОБА сервиса: Google (для оплаты) и Supercell (для входа).
Меняет IP (Novada — новый session), пока оба не станут чистыми.

Использование:
    cd autosupercell/help && python check_proxy.py

Прокси из .env (Novada или PROXY_*). Лимит: CHECK_PROXY_MAX_ATTEMPTS (по умолчанию 20).
"""

import asyncio
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(_root / ".env")
except ImportError:
    pass
sys.path.insert(0, str(_root))


def _get_proxy_config():
    """Прокси из proxy_manager приложения (Novada из .env) или из PROXY_*."""
    try:
        from app.config import settings
        from app.core.proxy_manager import proxy_manager
    except ImportError:
        return _get_proxy_config_from_env()
    if not getattr(settings, "PROXY_ENABLED", False):
        return None
    return proxy_manager.get_proxy()


def _get_proxy_config_from_env():
    """Резерв: сборка из NOVADA_* / PROXY_* если app не импортируется."""
    import secrets
    novada_enabled = os.getenv("NOVADA_ENABLED", "").lower() in ("true", "1", "yes")
    novada_user = (os.getenv("NOVADA_USERNAME", "") or "").strip()
    novada_key = (os.getenv("NOVADA_API_KEY", "") or "").strip()
    if novada_enabled and novada_user and novada_key:
        host = (os.getenv("NOVADA_PROXY_HOST", "super.novada.pro") or "super.novada.pro").strip()
        try:
            port = int(os.getenv("NOVADA_PROXY_PORT", "7777") or 7777)
        except ValueError:
            port = 7777
        zone = (os.getenv("NOVADA_ZONE", "res") or "res").strip()
        region = (os.getenv("NOVADA_REGION", "") or "").strip()
        state = (os.getenv("NOVADA_STATE", "") or "").strip()
        city = (os.getenv("NOVADA_CITY", "") or "").strip()
        try:
            sticky_min = int(os.getenv("NOVADA_STICKY_MINUTES", "8") or 8)
        except ValueError:
            sticky_min = 8
        base = f"{novada_user}-zone-{zone}"
        if region:
            base += f"-region-{region.lower()}"
        if state:
            base += f"-st-{state.lower().replace(' ', '')}"
        if city:
            base += f"-city-{city.lower().replace(' ', '')}"
        username = f"{base}-session-{secrets.token_hex(6)}-sessTime-{sticky_min}"
        return {"server": f"http://{host}:{port}", "username": username, "password": novada_key}
    host = (os.getenv("PROXY_HOST", "") or "").strip()
    port = (os.getenv("PROXY_PORT", "") or "").strip()
    if host and port:
        cfg = {"server": f"http://{host}:{port}"}
        u = (os.getenv("PROXY_USERNAME", "") or "").strip()
        p = (os.getenv("PROXY_PASSWORD", "") or "").strip()
        if u:
            cfg["username"] = u
        if p:
            cfg["password"] = p
        return cfg
    return None


def _make_launch_opts(proxy_config):
    opts = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-gpu",
        ],
    }
    if proxy_config:
        opts["proxy"] = proxy_config
    return opts


def _make_context_opts():
    return {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "locale": "en-US",
        "extra_http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        },
    }


async def _check_google(browser) -> dict:
    """Проверяет что Google не блокирует IP."""
    context = await browser.new_context(**_make_context_opts())
    page = await context.new_page()
    result = {"clean": False, "blocked": False, "url": "", "load_ms": None, "error": None}
    try:
        import time
        t0 = time.time()
        response = await page.goto("https://accounts.google.com", timeout=20000, wait_until="domcontentloaded")
        result["load_ms"] = int((time.time() - t0) * 1000)
        result["url"] = page.url
        body = await page.content()
        blocked = any([
            "sorry.google.com" in page.url,
            "signin/rejected" in page.url,
            "Our systems have detected unusual traffic" in body,
            "Couldn't sign you in" in body,
            "browser or app may not be secure" in body,
        ])
        result["blocked"] = blocked
        result["clean"] = not blocked and (response.status < 400 if response else False)
    except Exception as e:
        result["error"] = str(e)
    finally:
        await context.close()
    return result


async def _check_supercell(browser) -> dict:
    """Проверяет что Supercell не блокирует IP и страница грузится нормально."""
    context = await browser.new_context(**_make_context_opts())
    page = await context.new_page()
    result = {"clean": False, "blocked": False, "url": "", "load_ms": None, "error": None, "block_reason": ""}
    try:
        import time
        t0 = time.time()
        response = await page.goto("https://store.supercell.com", timeout=30000, wait_until="domcontentloaded")
        result["load_ms"] = int((time.time() - t0) * 1000)
        result["url"] = page.url
        status = response.status if response else 0
        body = await page.content()
        body_lower = body.lower()

        # Признаки блокировки со стороны Supercell
        supercell_block_signals = {
            "unusual activity":     "unusual activity" in body_lower,
            "blocked your login":   "blocked your login" in body_lower,
            "disable vpn":          "vpns, and proxies" in body_lower or "disable vpn" in body_lower,
            "cloudflare block":     "cf-error" in body_lower or "ray id" in body_lower,
            "access denied":        "access denied" in body_lower,
            "403/503 status":       status in (403, 503),
        }

        triggered = [k for k, v in supercell_block_signals.items() if v]
        if triggered:
            result["blocked"] = True
            result["block_reason"] = ", ".join(triggered)
            result["clean"] = False
        elif status >= 400:
            result["clean"] = False
            result["error"] = f"HTTP {status}"
        else:
            result["clean"] = True
    except Exception as e:
        result["error"] = str(e)
    finally:
        await context.close()
    return result


def _get_playwright():
    try:
        from patchright.async_api import async_playwright
        return async_playwright
    except ImportError:
        try:
            from playwright.async_api import async_playwright
            return async_playwright
        except ImportError:
            return None


async def run_checks(proxy_config) -> dict:
    """Одна попытка с заданным прокси: Google + Supercell. Возвращает {google, supercell}."""
    p = _get_playwright()
    if not p:
        print("[X] patchright/playwright не установлен: pip install patchright")
        sys.exit(1)

    async with p() as playwright:
        browser = await playwright.chromium.launch(**_make_launch_opts(proxy_config))
        try:
            if proxy_config:
                try:
                    ctx = await browser.new_context(**_make_context_opts())
                    page = await ctx.new_page()
                    await page.goto("http://ipinfo.novada.pro", timeout=25000, wait_until="commit")
                    await ctx.close()
                except Exception as e:
                    return {
                        "google": {"clean": False, "error": f"Прокси недоступен: {e}"},
                        "supercell": {"clean": False, "error": str(e)},
                    }

            print("   [ Google ] accounts.google.com ...")
            google = await _check_google(browser)
            print("   [ Supercell ] store.supercell.com ...")
            supercell = await _check_supercell(browser)
        finally:
            await browser.close()

    return {"google": google, "supercell": supercell}


def _print_attempt_result(attempt: int, proxy_config, g: dict, s: dict):
    """Вывод результата одной попытки."""
    server = proxy_config.get("server", "?") if proxy_config else "без прокси"
    user = (proxy_config.get("username", "") or "")[:40] if proxy_config else ""
    print(f"\n  Попытка {attempt} | {server}" + (f" | {user}..." if user else ""))
    print("  " + "-" * 51)

    # Google
    if g.get("clean"):
        print(f"  [Google]    OK  ({g.get('load_ms', '?')}мс)  {g.get('url','')[:60]}")
    elif g.get("blocked"):
        print(f"  [Google]    ЗАБЛОКИРОВАН  {g.get('url','')[:60]}")
    elif g.get("error"):
        err = g["error"]
        short = err[:80] + "..." if len(err) > 80 else err
        print(f"  [Google]    ОШИБКА: {short}")
    else:
        print("  [Google]    нет данных")

    # Supercell
    if s.get("clean"):
        ms = s.get("load_ms", "?")
        warn = ""
        if isinstance(ms, int) and ms > 8000:
            warn = "  [!] медленно"
        elif isinstance(ms, int) and ms > 4000:
            warn = "  [~] медленновато"
        print(f"  [Supercell] OK  ({ms}мс){warn}")
    elif s.get("blocked"):
        print(f"  [Supercell] ЗАБЛОКИРОВАН  причина: {s.get('block_reason','?')}")
    elif s.get("error"):
        err = s["error"]
        short = err[:80] + "..." if len(err) > 80 else err
        print(f"  [Supercell] ОШИБКА: {short}")
    else:
        print("  [Supercell] нет данных")


async def main():
    print("=" * 55)
    print("  Проверка прокси: Google + Supercell")
    print("  Меняем IP до тех пор, пока оба не будут чистыми")
    print("=" * 55)

    # Лимит попыток
    max_attempts = 20
    try:
        max_attempts = int(os.getenv("CHECK_PROXY_MAX_ATTEMPTS", "20") or 20)
    except ValueError:
        pass

    proxy_config = _get_proxy_config()
    if not proxy_config:
        print("\n[!] Прокси не настроен (PROXY_ENABLED=false или нет Novada в .env).")
        print("    Проверяем без прокси (одна попытка).\n")

    attempt = 0
    while True:
        attempt += 1

        r = await run_checks(proxy_config)
        g = r["google"]
        s = r["supercell"]

        _print_attempt_result(attempt, proxy_config, g, s)

        both_clean = g.get("clean") and s.get("clean")

        if both_clean:
            slow = isinstance(s.get("load_ms"), int) and s["load_ms"] > 8000
            print()
            if slow:
                print("[~] IP чистый, но Supercell грузится медленно (>8с). Рекомендуем сменить IP.")
            else:
                print("[OK] ОБА ЧИСТЫЕ — можно запускать покупку!")
            print()
            return True

        # Нет прокси — одна попытка, выходим
        if not proxy_config:
            print("\n[X] Без прокси один из сервисов заблокирован или недоступен.")
            print()
            return False

        # Исчерпан лимит
        if attempt >= max_attempts:
            print(f"\n[X] Не удалось найти чистый IP за {attempt} попыток.")
            print("    Попробуй другой NOVADA_STATE или NOVADA_REGION в .env.")
            print()
            return False

        # Причина неудачи и пауза
        reasons = []
        if not g.get("clean"):
            if g.get("blocked"):
                reasons.append("Google: IP в бане")
            elif g.get("error") and "Timeout" in str(g["error"]):
                reasons.append("Google: таймаут")
            else:
                reasons.append(f"Google: {(g.get('error') or 'не чистый')[:60]}")
        if not s.get("clean"):
            if s.get("blocked"):
                reasons.append(f"Supercell: {s.get('block_reason','заблокирован')}")
            elif s.get("error") and "timeout" in str(s.get("error","")).lower():
                reasons.append("Supercell: таймаут")
            else:
                reasons.append(f"Supercell: {(s.get('error') or 'не чистый')[:60]}")

        print(f"\n  -> {' | '.join(reasons)}")
        print(f"  -> Берём новый IP Novada (попытка {attempt + 1}/{max_attempts})...")

        proxy_config = _get_proxy_config()
        if not proxy_config:
            print("[X] Не удалось получить новый прокси.")
            return False


if __name__ == "__main__":
    clean = asyncio.run(main())
    sys.exit(0 if clean else 1)
