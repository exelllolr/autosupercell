"""API routes для работы с магазином Supercell Store."""

import asyncio
import random
import re
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, EmailStr

from app.api.supercell_auth_routes import _accept_cookies
from app.config import settings
from app.core.ai_product_search import AIProductSearch
from app.core.browser_automation import BrowserAutomation
from app.core.google_pay import handle_google_pay
from app.core.proxy_manager import proxy_manager

router = APIRouter()

MAX_BLOCK_RETRIES = 3


async def _find_and_click_product(
    browser: "BrowserAutomation", product_name: str
) -> bool:
    """
    Поиск карточки товара в секции GEMS и клик по ней.
    Сначала находит секцию GEMS на странице, затем ищет карточку с нужным числом гемов.
    """
    import re as _re

    page = browser.page
    if not page:
        return False

    # Ждём загрузки страницы
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass

    num_match = _re.search(r"\d+", product_name)
    num_str = num_match.group() if num_match else ""
    name_lower = product_name.lower().strip()

    logger.info(f"Поиск товара '{product_name}' (num={num_str})")

    # ── Стратегия 1: Найти секцию GEMS, затем карточку с нужным числом ────────
    # JS: ищем заголовок секции "GEMS", затем ближайшую карточку с нужным числом
    try:
        handle = await page.evaluate_handle(
            """([num, name]) => {
                const nameLower = name.toLowerCase();
                // Ищем заголовок секции GEMS
                let gemsSection = null;
                for (const el of document.querySelectorAll('*')) {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t.toUpperCase() === 'GEMS' || t.toUpperCase() === '🔮 GEMS' || t.toUpperCase() === 'GEMS' ) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 || el.offsetParent !== null) {
                            gemsSection = el;
                            break;
                        }
                    }
                }

                // Если нашли секцию GEMS — ищем карточку ниже неё
                if (gemsSection) {
                    const gemsRect = gemsSection.getBoundingClientRect();
                    const gemsTop = gemsSection.offsetTop || 0;
                    // Ищем карточку с нужным числом в пределах 2000px ниже заголовка
                    let best = null, bestScore = Infinity;
                    for (const el of document.querySelectorAll('a, button, [class*="card"], [class*="product"], [class*="item"], li')) {
                        const t = (el.innerText || el.textContent || '').toLowerCase().trim();
                        if (!t.includes(num) || !t.includes('gem')) continue;
                        const elTop = el.offsetTop || 0;
                        if (elTop < gemsTop) continue; // выше секции GEMS — пропускаем
                        const dist = elTop - gemsTop;
                        if (dist > 3000) continue; // слишком далеко
                        const r = el.getBoundingClientRect();
                        if (r.width < 20 || r.height < 10) continue;
                        if (t.length < bestScore) {
                            best = el;
                            bestScore = t.length;
                        }
                    }
                    if (best) return best;
                }

                // Fallback: ищем карточку с точным числом гемов во всём документе
                // Приоритет: элементы с коротким текстом (карточка, не раздел)
                let best = null, bestScore = Infinity;
                for (const el of document.querySelectorAll('a, button, [class*="card"], [class*="product"], [class*="item"], li')) {
                    const t = (el.innerText || el.textContent || '').toLowerCase().trim();
                    if (!t.includes(num) || !t.includes('gem')) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 20 || r.height < 10) continue;
                    // Предпочитаем элементы с текстом близким к "80 gems"
                    if (t.length < bestScore && t.length < name.length * 10) {
                        best = el;
                        bestScore = t.length;
                    }
                }
                return best;
            }""",
            [num_str, name_lower],
        )
        el = handle.as_element()
        if el:
            await el.scroll_into_view_if_needed()
            await page.wait_for_timeout(600)
            bb = await el.bounding_box()
            if bb:
                logger.info(
                    f"Стратегия 1 (GEMS section): ({bb['x']:.0f},{bb['y']:.0f}) size={bb['width']:.0f}x{bb['height']:.0f}"
                )
                await el.click(timeout=5000)
                return True
    except Exception as e:
        logger.debug(f"Стратегия 1 (GEMS section): {e}")

    # ── Стратегия 2: get_by_text точное совпадение ────────────────────────────
    try:
        loc = page.get_by_text(_re.compile(rf"^{_re.escape(num_str)}\s*gems?$", _re.I))
        count = await loc.count()
        for i in range(min(count, 5)):
            el = loc.nth(i)
            try:
                await el.scroll_into_view_if_needed()
                await page.wait_for_timeout(400)
                bb = await el.bounding_box()
                if bb and bb["width"] > 20:
                    logger.info(
                        f"Стратегия 2 (exact get_by_text) #{i}: ({bb['x']:.0f},{bb['y']:.0f})"
                    )
                    await el.click(timeout=5000)
                    return True
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"Стратегия 2: {e}")

    # ── Стратегия 3: CSS :has-text ────────────────────────────────────────────
    for css in [
        f'[class*="card"]:has-text("{product_name}")',
        f'[class*="product"]:has-text("{product_name}")',
        f'a:has-text("{product_name}")',
        f'li:has-text("{product_name}")',
    ]:
        try:
            loc = page.locator(css).first
            if await loc.count() > 0:
                await loc.scroll_into_view_if_needed()
                await page.wait_for_timeout(400)
                bb = await loc.bounding_box()
                if bb:
                    logger.info(
                        f"Стратегия 3 (CSS): '{css}' at ({bb['x']:.0f},{bb['y']:.0f})"
                    )
                    await loc.click(timeout=5000)
                    return True
        except Exception:
            continue

    # ── Стратегия 4: Кнопка Buy с ценой (сумка + $4.99) ───────────────────────
    # На странице магазина кнопка добавления в корзину — белая кнопка с иконкой сумки и ценой
    try:
        price_loc = page.get_by_text(_re.compile(r"\$\d+\.\d+"))
        n = await price_loc.count()
        for i in range(min(n, 15)):
            loc = price_loc.nth(i)
            try:
                await loc.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                if not await loc.is_visible():
                    continue
                bb = await loc.bounding_box()
                if not bb or bb["height"] < 15:
                    continue
                # Текст цены часто внутри кнопки — кликаем родителя (button/a), иначе сам элемент
                to_click = None
                parent = loc.locator("..")
                if await parent.count() > 0:
                    tag = await parent.evaluate(
                        "el => el ? el.tagName.toLowerCase() : ''"
                    )
                    if tag in ("button", "a"):
                        to_click = parent
                if to_click is None:
                    grandparent = loc.locator("../..")
                    if await grandparent.count() > 0:
                        tag = await grandparent.evaluate(
                            "el => el ? el.tagName.toLowerCase() : ''"
                        )
                        if tag in ("button", "a"):
                            to_click = grandparent
                if to_click is not None:
                    await to_click.scroll_into_view_if_needed()
                    await page.wait_for_timeout(200)
                    if await to_click.is_visible():
                        logger.info(
                            f"Стратегия 4 (кнопка с ценой): клик по кнопке с ценой at ({bb['x']:.0f},{bb['y']:.0f})"
                        )
                        await to_click.click(timeout=5000)
                        return True
                logger.info(
                    f"Стратегия 4 (кнопка с ценой): клик по элементу с ценой at ({bb['x']:.0f},{bb['y']:.0f})"
                )
                await loc.click(timeout=5000)
                return True
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"Стратегия 4 (кнопка с ценой): {e}")

    # ── Стратегия 5: Кнопка по aria-label / по тексту Buy / Add to cart ───────
    for label_pattern in ["buy", "add to cart", "add to bag", "purchase", "купить"]:
        try:
            btn = page.get_by_role("button", name=_re.compile(label_pattern, _re.I))
            if await btn.count() > 0:
                for i in range(min(await btn.count(), 5)):
                    b = btn.nth(i)
                    if not await b.is_visible():
                        continue
                    await b.scroll_into_view_if_needed()
                    await page.wait_for_timeout(300)
                    logger.info(
                        f"Стратегия 5 (role=button '{label_pattern}'): клик #{i}"
                    )
                    await b.click(timeout=5000)
                    return True
        except Exception:
            continue

    logger.warning(f"Все стратегии не нашли карточку/кнопку '{product_name}'")
    return False


async def _manage_cart_and_checkout(
    browser: "BrowserAutomation", product_name: str, desired_qty: int = 1
) -> dict:
    """
    Управление корзиной после клика по карточке товара.

    Логика:
    1. Ждём появления панели корзины (правая панель) или страницы продукта
    2. Проверяем что в корзине нужный товар
    3. Если количество неверное — нажимаем +/- пока не станет нужным
    4. Если лишние товары — удаляем их
    5. Нажимаем кнопку Checkout

    Возвращает dict с ключами: added (bool), checkout_opened (bool), cart_items (list)
    """
    page = browser.page
    result = {"added": False, "checkout_opened": False, "cart_items": []}

    # Ждём реакции страницы (URL может измениться на /product/...)
    await browser.human_like_delay(2000, 3000)
    await browser.take_screenshot(
        f"after_card_click_{product_name.replace(' ', '_')}.png"
    )

    current_url = page.url
    logger.info(f"URL после клика по карточке: {current_url}")

    # ── Шаг 0: Если открылась панель/модалка продукта — нажать Buy / Add to cart ─
    # На store после клика по карточке открывается панель с "80 Gems" и кнопкой Buy;
    # без клика по ней корзина не открывается.
    buy_add_clicked = False
    for btn_text in [
        "Buy",
        "BUY",
        "Add to cart",
        "ADD TO CART",
        "Add to bag",
        "Купить",
        "Добавить в корзину",
    ]:
        try:
            btn = page.get_by_role("button", name=re.compile(re.escape(btn_text), re.I))
            if await btn.count() > 0:
                for i in range(min(await btn.count(), 5)):
                    b = btn.nth(i)
                    if not await b.is_visible():
                        continue
                    await b.scroll_into_view_if_needed()
                    await page.wait_for_timeout(400)
                    logger.info(f"Нажимаем кнопку на панели продукта: '{btn_text}'")
                    await b.click(timeout=5000)
                    buy_add_clicked = True
                    break
            if buy_add_clicked:
                break
        except Exception:
            continue
    if not buy_add_clicked:
        try:
            for sel in [
                'button:has-text("Buy")',
                'button:has-text("BUY")',
                'a:has-text("Buy")',
                'button:has-text("Add to cart")',
                '[class*="buy"]:has-text("Buy")',
            ]:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.scroll_into_view_if_needed()
                    await page.wait_for_timeout(400)
                    logger.info(f"Нажимаем кнопку Buy/Add to cart: {sel}")
                    await loc.click(timeout=5000)
                    buy_add_clicked = True
                    break
        except Exception:
            pass
    # На странице продукта (/store/.../product/...) кнопка часто — это цена $4.99 (сумка + цена)
    if not buy_add_clicked and "/product/" in current_url:
        try:
            price_loc = page.get_by_text(re.compile(r"\$\d+\.\d+"))
            n = await price_loc.count()
            for i in range(min(n, 12)):
                loc = price_loc.nth(i)
                try:
                    await loc.scroll_into_view_if_needed()
                    await page.wait_for_timeout(300)
                    if not await loc.is_visible():
                        continue
                    bb = await loc.bounding_box()
                    if not bb or bb["height"] < 15:
                        continue
                    to_click = None
                    parent = loc.locator("..")
                    if await parent.count() > 0:
                        tag = await parent.evaluate(
                            "el => el ? el.tagName.toLowerCase() : ''"
                        )
                        if tag in ("button", "a"):
                            to_click = parent
                    if to_click is None:
                        grandparent = loc.locator("../..")
                        if await grandparent.count() > 0:
                            tag = await grandparent.evaluate(
                                "el => el ? el.tagName.toLowerCase() : ''"
                            )
                            if tag in ("button", "a"):
                                to_click = grandparent
                    if to_click is not None:
                        await to_click.scroll_into_view_if_needed()
                        await page.wait_for_timeout(200)
                        if await to_click.is_visible():
                            logger.info(
                                "Нажимаем кнопку с ценой на странице продукта ($X.XX)"
                            )
                            await to_click.click(timeout=5000)
                            buy_add_clicked = True
                            break
                    await loc.click(timeout=5000)
                    logger.info("Нажимаем элемент с ценой на странице продукта")
                    buy_add_clicked = True
                    break
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Клик по кнопке с ценой на product page: {e}")
    if buy_add_clicked:
        await browser.human_like_delay(2000, 3500)
        await browser.take_screenshot(
            f"after_buy_click_{product_name.replace(' ', '_')}.png"
        )
        # Ждём появления корзины или кнопки Checkout (панель может открываться с задержкой)
        for wait_text in ["Checkout", "1 item", "item", "Proceed to Checkout"]:
            try:
                loc = page.get_by_text(re.compile(re.escape(wait_text), re.I)).first
                await loc.wait_for(state="visible", timeout=12000)
                logger.info(f"Корзина/Checkout появились (найден текст '{wait_text}')")
                await browser.human_like_delay(800, 1200)
                break
            except Exception:
                continue

    # ── Шаг A: Если открылась страница продукта (/product/) ──────────────────
    if "/product/" in current_url:
        logger.info("Открылась страница продукта, ищем панель корзины...")
        # Ждём загрузки панели корзины
        try:
            await page.wait_for_selector(
                '[class*="cart"], [class*="Cart"], [class*="sidebar"], [class*="panel"]',
                timeout=15000,
            )
        except Exception:
            pass
        await browser.human_like_delay(1000, 1500)

    # ── Шаг B: Ищем панель корзины ───────────────────────────────────────────
    # Проверяем наличие панели корзины (правая панель с "1 item", "Checkout" и т.д.)
    cart_panel_visible = False
    cart_panel_selectors = [
        '[class*="cart-panel"]',
        '[class*="cartPanel"]',
        '[class*="cart-sidebar"]',
        '[class*="CartSidebar"]',
        '[class*="cart-drawer"]',
        '[class*="CartDrawer"]',
        '[class*="mini-cart"]',
        '[class*="miniCart"]',
        "aside",
        '[role="complementary"]',
    ]
    for sel in cart_panel_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                cart_panel_visible = True
                logger.info(f"Панель корзины найдена: {sel}")
                break
        except Exception:
            continue

    # Если панель не найдена — ищем кнопку корзины (bag icon с ценой) и кликаем
    if not cart_panel_visible:
        logger.info("Панель корзины не видна, ищем кнопку корзины...")
        cart_btn_selectors = [
            '[class*="cart-button"]',
            '[class*="cartButton"]',
            '[class*="cart-icon"]',
            '[class*="cartIcon"]',
            '[class*="cart-toggle"]',
            '[class*="bag"]',
            'button[class*="cart"]',
            'a[class*="cart"]',
            # Не используем [class*="checkout"] — это может быть главная кнопка Checkout, а не открытие корзины
        ]
        for sel in cart_btn_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=3000)
                    logger.info(f"Нажата кнопка корзины: {sel}")
                    await browser.human_like_delay(1000, 1500)
                    cart_panel_visible = True
                    break
            except Exception:
                continue
        if not cart_panel_visible:
            try:
                # Только кнопки корзины/сумки, не главная кнопка "Checkout" (она внизу панели)
                cart_btn = page.get_by_role(
                    "button", name=re.compile(r"cart|корзин|bag|items?", re.I)
                )
                if await cart_btn.count() > 0:
                    await cart_btn.first.click(timeout=3000)
                    logger.info("Нажата кнопка корзины (role=button по тексту)")
                    await browser.human_like_delay(1000, 1500)
                    cart_panel_visible = True
            except Exception:
                pass

    # ── Шаг C: Проверяем количество в корзине и выставляем нужное (desired_qty) ─
    await browser.human_like_delay(800, 1200)

    page_text = await page.evaluate("() => document.body.innerText")
    logger.info(f"Текст страницы (первые 500 символов): {page_text[:500]}")

    # Определяем общее число товаров и число позиций (линий) в корзине
    async def _read_cart_stats():
        return await page.evaluate(
            """() => {
                const bodyText = (document.body.innerText || '').trim();
                let totalItems = null;
                let lineCount = 0;
                const cartRoots = document.querySelectorAll('[class*="cart"], [class*="Cart"], aside, [class*="drawer"], [role="complementary"]');
                const scope = document.body;
                // Сумма по всем input количества в корзине
                const inputs = scope.querySelectorAll('input[type="number"], input[class*="qty"], input[class*="quantity"], input[class*="Qty"]');
                let sum = 0;
                for (const inp of inputs) {
                    const v = parseInt(inp.value, 10);
                    if (!isNaN(v) && v >= 0) { sum += v; lineCount++; }
                }
                if (lineCount > 0) totalItems = sum;
                // Иначе — из текста "N item(s)"
                if (totalItems === null && /\\d+\\s*item/i.test(bodyText)) {
                    const m = bodyText.match(/(\\d+)\\s*item/i);
                    if (m) totalItems = parseInt(m[1], 10);
                }
                // Число между - и + (одна позиция)
                if (totalItems === null) {
                    for (const c of document.querySelectorAll('[class*="cart"], [class*="Cart"], [class*="qty"], [class*="quantity"], aside')) {
                        const match = (c.innerText || '').match(/[−–-]\\s*(\\d+)\\s*\\+/);
                        if (match) { totalItems = parseInt(match[1], 10); lineCount = lineCount || 1; break; }
                    }
                }
                if (totalItems === null && lineCount === 0) lineCount = 1;
                if (totalItems === null) totalItems = 1;
                return { totalItems, lineCount };
            }"""
        )

    cart_stats = await _read_cart_stats()
    total_items = cart_stats.get("totalItems") or 1
    line_count = cart_stats.get("lineCount") or 1
    logger.info(
        f"В корзине: всего товаров={total_items}, позиций (линий)={line_count}, нужно оставить={desired_qty}"
    )

    # Прокручиваем панель корзины (drawer), чтобы блок количества (- 5 +) был в зоне видимости
    try:
        await page.evaluate(
            """() => {
                const cart = document.querySelector('[class*="drawer"], [class*="Drawer"], [class*="cart"], [class*="Cart"], aside[class*="cart"], [class*="sidebar"]');
                if (cart && cart.scrollHeight > cart.clientHeight) {
                    cart.scrollTop = 0;
                }
            }"""
        )
        await page.wait_for_timeout(300)
    except Exception:
        pass

    # Приводим к одному товару: сначала уменьшаем количество (−), потом удаляем лишние позиции (Remove)
    max_minus_clicks = 50
    minus_clicks_done = 0
    while total_items > desired_qty and minus_clicks_done < max_minus_clicks:
        clicked = False
        # 1) JS: ищем минус только внутри корзины, в блоке где есть число и плюс (селектор количества)
        try:
            clicked = await page.evaluate(
                """() => {
                    const cart = document.querySelector('[class*="drawer"], [class*="Drawer"], [class*="cart"], [class*="Cart"], aside, [class*="sidebar"]');
                    const scope = cart || document.body;
                    const candidates = scope.querySelectorAll('button, [role="button"], span, div, a');
                    for (const el of candidates) {
                        const t = (el.innerText || el.textContent || '').trim();
                        if (t !== '−' && t !== '-' && t !== '–') continue;
                        const par = el.closest('[class*="cart"], [class*="Cart"], [class*="qty"], [class*="quantity"], [class*="drawer"], aside');
                        const parText = par ? (par.innerText || par.textContent || '') : '';
                        if (!/[−–-]\\s*\\d+\\s*\\+/.test(parText) && !/\\d+/.test(parText)) continue;
                        const toClick = el.closest('button, [role="button"]') || el;
                        const r = toClick.getBoundingClientRect();
                        if (r.width <= 0 || r.height <= 0) continue;
                        toClick.scrollIntoView({ block: 'center', behavior: 'instant' });
                        toClick.click();
                        return true;
                    }
                    for (const el of candidates) {
                        const t = (el.innerText || el.textContent || '').trim();
                        if (t === '−' || t === '-' || t === '–') {
                            const toClick = el.closest('button, [role="button"]') || el;
                            const r = toClick.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) {
                                toClick.scrollIntoView({ block: 'center', behavior: 'instant' });
                                toClick.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }"""
            )
        except Exception:
            pass
        if not clicked:
            # 2) Playwright: кнопка "−" внутри корзины по роли и тексту
            try:
                cart_loc = page.locator(
                    '[class*="drawer"], [class*="Drawer"], [class*="cart"], [class*="Cart"], aside'
                ).first
                if await cart_loc.count() > 0:
                    minus_btn = cart_loc.get_by_role(
                        "button",
                        name=re.compile(
                            r"decrease|minus|less|уменьшить|^[\s\-−–]+$", re.I
                        ),
                    ).first
                    if await minus_btn.count() > 0:
                        await minus_btn.scroll_into_view_if_needed()
                        await page.wait_for_timeout(200)
                        await minus_btn.click(timeout=3000)
                        clicked = True
            except Exception:
                pass
        if not clicked:
            try:
                minus_btn = page.locator(
                    '[class*="cart"] button:has-text("-"), [class*="cart"] [role="button"]:has-text("-"), [class*="drawer"] button:has-text("-")'
                ).first
                if await minus_btn.count() > 0 and await minus_btn.is_visible():
                    await minus_btn.scroll_into_view_if_needed()
                    await minus_btn.click(timeout=3000)
                    clicked = True
            except Exception:
                pass
        if not clicked:
            logger.warning(
                "Кнопка «−» для уменьшения количества не найдена или не сработала"
            )
            break
        minus_clicks_done += 1
        await browser.human_like_delay(400, 600)
        cart_stats = await _read_cart_stats()
        total_items = cart_stats.get("totalItems") or total_items
        line_count = cart_stats.get("lineCount") or line_count
        if total_items <= desired_qty:
            break
    if minus_clicks_done > 0:
        logger.info(
            f"Уменьшено количество: нажатий − = {minus_clicks_done}, теперь всего товаров={total_items}"
        )

    # Удаляем лишние позиции (оставляем одну): кнопки Remove / Delete / × / trash
    while line_count > 1:
        removed = await page.evaluate(
            """() => {
                const labels = /remove|delete|удалить|trash|убрать/i;
                const all = Array.from(document.querySelectorAll('button, a, [role="button"], [class*="remove"], [class*="Remove"], [class*="delete"], [class*="Delete"]'));
                for (const el of all) {
                    const t = (el.innerText || el.textContent || '').trim();
                    const aria = (el.getAttribute('aria-label') || '').trim();
                    if (t === '×' || t === '✕' || t === 'x' || labels.test(t) || labels.test(aria)) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            el.scrollIntoView({ block: 'center' });
                            el.click();
                            return true;
                        }
                    }
                }
                return false;
            }"""
        )
        if not removed:
            logger.warning("Кнопка удаления позиции из корзины не найдена")
            break
        await browser.human_like_delay(500, 900)
        cart_stats = await _read_cart_stats()
        line_count = cart_stats.get("lineCount") or (line_count - 1)
        total_items = cart_stats.get("totalItems") or total_items
        logger.info(
            f"Удалена одна позиция из корзины, осталось позиций={line_count}, товаров={total_items}"
        )

    cart_qty = total_items

    # Дополнительная корректировка: если одно число по первому input всё ещё не 1
    if cart_qty is not None and cart_qty != desired_qty:
        diff = desired_qty - cart_qty
        need_plus = diff > 0
        clicks_needed = abs(diff)
        logger.info(
            f"Корректируем количество: {cart_qty} → {desired_qty} (нажимаем {'+' if need_plus else '−'} x{clicks_needed})"
        )

        for _ in range(clicks_needed):
            clicked_adj = False
            # Варианты минуса: обычный дефис и Unicode minus
            minus_selectors = [
                'button:has-text("−")',
                'button:has-text("-")',
                '[aria-label*="decrease"]',
                '[aria-label*="minus"]',
                '[class*="qty"] button:has-text("-")',
                '[class*="quantity"] button:has-text("-")',
                'button:has-text("–")',
                '[role="button"]:has-text("−")',
                '[role="button"]:has-text("-")',
            ]
            plus_selectors = [
                'button:has-text("+")',
                '[aria-label*="increase"]',
                '[aria-label*="plus"]',
                '[class*="qty"] button:has-text("+")',
                '[class*="quantity"] button:has-text("+")',
                '[role="button"]:has-text("+")',
            ]
            selectors = plus_selectors if need_plus else minus_selectors
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.scroll_into_view_if_needed()
                        await page.wait_for_timeout(200)
                        await loc.click(timeout=3000)
                        clicked_adj = True
                        logger.info(
                            f"Нажата кнопка {'+' if need_plus else '−'} для количества"
                        )
                        await browser.human_like_delay(400, 700)
                        break
                except Exception:
                    continue
            if not clicked_adj:
                # Fallback: get_by_role по имени кнопки
                try:
                    btn = (
                        page.get_by_role(
                            "button",
                            name=re.compile(r"increase|plus|more|добавить", re.I),
                        )
                        if need_plus
                        else page.get_by_role(
                            "button",
                            name=re.compile(r"decrease|minus|less|уменьшить", re.I),
                        )
                    )
                    if await btn.count() > 0:
                        await btn.first.click(timeout=3000)
                        clicked_adj = True
                        await browser.human_like_delay(400, 700)
                except Exception:
                    pass
            if not clicked_adj:
                # Fallback: через JS ищем кнопку −/+ в блоке количества (рядом с числом)
                try:
                    clicked_js = await page.evaluate(
                        """(needPlus) => {
                            const all = document.querySelectorAll('button, [role="button"], a, span, div');
                            for (const el of all) {
                                const t = (el.innerText || el.textContent || '').trim();
                                const isMinus = t === '−' || t === '-' || t === '–';
                                const isPlus = t === '+';
                                if (!isMinus && !isPlus) continue;
                                const parent = el.closest('[class*="cart"], [class*="Cart"], [class*="qty"], [class*="quantity"], aside');
                                const parentText = parent ? (parent.innerText || '').trim() : '';
                                const hasDigit = /[−–-]\\s*\\d+\\s*\\+/.test(parentText) || (parent && /\\d+/.test(parent.innerText || ''));
                                if (!hasDigit) continue;
                                if (needPlus && isPlus) { el.click(); return true; }
                                if (!needPlus && isMinus) { el.click(); return true; }
                            }
                            for (const el of all) {
                                const t = (el.innerText || el.textContent || '').trim();
                                if (!needPlus && (t === '−' || t === '-' || t === '–')) { el.click(); return true; }
                                if (needPlus && t === '+') { el.click(); return true; }
                            }
                            return false;
                        }""",
                        need_plus,
                    )
                    if clicked_js:
                        clicked_adj = True
                        logger.info(
                            f"Нажата кнопка {'+' if need_plus else '−'} (JS fallback)"
                        )
                        await browser.human_like_delay(400, 700)
                except Exception:
                    pass
            if not clicked_adj:
                logger.warning(
                    f"Не удалось нажать кнопку {'+' if need_plus else '−'} для корректировки количества"
                )
                break
        await browser.human_like_delay(500, 800)

    result["added"] = True

    # Перед Checkout ещё раз убеждаемся, что количество = desired_qty (сначала убираем лишнее, потом Checkout)
    cart_stats = await _read_cart_stats()
    total_items = cart_stats.get("totalItems") or 1
    line_count = cart_stats.get("lineCount") or 1
    if total_items > desired_qty:
        logger.info(
            f"Перед Checkout количество ещё {total_items}, повторяем уменьшение до {desired_qty}"
        )
        for _ in range(min(total_items - desired_qty, 30)):
            try:
                clicked = await page.evaluate(
                    """() => {
                        const cart = document.querySelector('[class*="drawer"], [class*="cart"], aside');
                        const scope = cart || document.body;
                        const candidates = scope.querySelectorAll('button, [role="button"], span, div, a');
                        for (const el of candidates) {
                            const t = (el.innerText || el.textContent || '').trim();
                            if (t !== '−' && t !== '-' && t !== '–') continue;
                            const toClick = el.closest('button, [role="button"]') || el;
                            const r = toClick.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) { toClick.scrollIntoView({ block: 'center' }); toClick.click(); return true; }
                        }
                        return false;
                    }"""
                )
                if not clicked:
                    break
                await browser.human_like_delay(400, 600)
                cart_stats = await _read_cart_stats()
                total_items = cart_stats.get("totalItems") or total_items
                if total_items <= desired_qty:
                    break
            except Exception:
                break
        logger.info(f"После повторного уменьшения: всего товаров={total_items}")

    if total_items > desired_qty:
        logger.warning(
            f"Не удалось привести количество к {desired_qty}, в корзине {total_items}. Checkout не нажимаем."
        )
    else:
        try:
            await browser.take_screenshot(
                f"cart_ready_{product_name.replace(' ', '_')}.png"
            )
        except Exception as e:
            logger.debug(f"Скриншот cart_ready пропущен: {e}")

    # ── Шаг D: Нажимаем Checkout только если количество уже нужное ─────────────
    if total_items > desired_qty:
        pass  # Checkout не нажимаем, см. выше
    else:
        # При большом количестве товаров кнопка Checkout может быть внизу — прокручиваем
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(300)
            # Прокрутка контейнера корзины (если есть)
            await page.evaluate(
                """() => {
                    const cart = document.querySelector('[class*="cart"], [class*="Cart"], aside, [class*="drawer"]');
                    if (cart && cart.scrollHeight > cart.clientHeight) {
                        cart.scrollTop = cart.scrollHeight;
                    }
                }"""
            )
            await page.wait_for_timeout(400)
        except Exception:
            pass

        checkout_selectors = [
            'button:has-text("Checkout")',
            'a:has-text("Checkout")',
            'button:has-text("Proceed to Checkout")',
            'a:has-text("Proceed to Checkout")',
            'button:has-text("Go to checkout")',
            'a:has-text("Go to checkout")',
            '[class*="checkout"]:visible',
            '[data-testid*="checkout"]',
            'button:has-text("Оформить")',
            'a:has-text("Оформить")',
            '[role="button"]:has-text("Checkout")',
        ]
        for sel in checkout_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.scroll_into_view_if_needed()
                    await browser.human_like_delay(500, 800)
                    await loc.click(timeout=5000)
                    logger.info(f"Нажата кнопка Checkout: {sel}")
                    result["checkout_opened"] = True
                    try:
                        await browser.human_like_delay(2000, 3000)
                        await browser.take_screenshot(
                            f"checkout_{product_name.replace(' ', '_')}.png"
                        )
                    except Exception as screenshot_err:
                        logger.debug(
                            f"Скриншот после Checkout пропущен (страница ушла): {screenshot_err}"
                        )
                    break
            except Exception:
                continue
        if not result["checkout_opened"]:
            try:
                checkout_btn = page.get_by_role(
                    "button", name=re.compile(r"checkout|оформить|proceed", re.I)
                )
                if await checkout_btn.count() > 0:
                    await checkout_btn.first.scroll_into_view_if_needed()
                    await browser.human_like_delay(500, 800)
                    await checkout_btn.first.click(timeout=5000)
                    logger.info("Нажата кнопка Checkout (get_by_role)")
                    result["checkout_opened"] = True
                    try:
                        await browser.human_like_delay(2000, 3000)
                        await browser.take_screenshot(
                            f"checkout_{product_name.replace(' ', '_')}.png"
                        )
                    except Exception as screenshot_err:
                        logger.debug(
                            f"Скриншот после Checkout пропущен: {screenshot_err}"
                        )
            except Exception:
                pass

        if not result["checkout_opened"]:
            try:
                for text_pat in [
                    "Checkout",
                    "Proceed to Checkout",
                    "Proceed",
                    "Place order",
                    "Go to checkout",
                ]:
                    loc = page.get_by_text(re.compile(re.escape(text_pat), re.I)).first
                    if await loc.count() > 0:
                        await loc.scroll_into_view_if_needed()
                        await page.wait_for_timeout(400)
                        if await loc.is_visible():
                            await loc.evaluate(
                                "el => { const b = el.closest('button, a, [role=\"button\"]'); (b || el).click(); }"
                            )
                            logger.info(
                                f"Нажата кнопка Checkout (get_by_text): '{text_pat}'"
                            )
                            result["checkout_opened"] = True
                            try:
                                await browser.human_like_delay(2000, 3000)
                                await browser.take_screenshot(
                                    f"checkout_{product_name.replace(' ', '_')}.png"
                                )
                            except Exception:
                                pass
                            break
                    if result["checkout_opened"]:
                        break
            except Exception:
                pass

        if not result["checkout_opened"]:
            try:
                clicked = await page.evaluate(
                    """() => {
                        const re = /checkout|proceed|place\\s*order|оформить/i;
                        for (const el of document.querySelectorAll('button, a, [role="button"], [class*="checkout"], [class*="Checkout"]')) {
                            const t = (el.innerText || el.textContent || '').trim();
                            if (!re.test(t)) continue;
                            const r = el.getBoundingClientRect();
                            if (r.width < 50 || r.height < 20) continue;
                            const style = window.getComputedStyle(el);
                            if (style.visibility === 'hidden' || style.display === 'none') continue;
                            el.scrollIntoView({ block: 'center' });
                            el.click();
                            return true;
                        }
                        return false;
                    }"""
                )
                if clicked:
                    logger.info("Нажата кнопка Checkout (JS fallback)")
                    result["checkout_opened"] = True
                    try:
                        await browser.human_like_delay(2000, 3000)
                        await browser.take_screenshot(
                            f"checkout_{product_name.replace(' ', '_')}.png"
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Checkout JS fallback: {e}")

        if not result["checkout_opened"]:
            logger.warning("Кнопка Checkout не найдена")

    return result


async def run_purchase_flow_after_login(
    browser: "BrowserAutomation",
    game: str,
    product_name: str,
    session_id: str = None,
) -> dict:
    """
    Единый путь покупки после входа в аккаунт.
    Используется в API (_purchase_flow) и в manual_login_gpay_demo.
    Шаги: переход в магазин игры → поиск товара и Buy → корзина, проверка количества → Checkout.
    """
    session_id = session_id or f"purchase_{game}"
    logger.info(f"Переход в магазин {game}...")
    await browser.navigate_to_store(game)
    await browser.human_like_delay(3000, 5000)
    await browser.take_screenshot(f"store_{game}_{session_id}.png")

    logger.info(f"Поиск товара '{product_name}' и добавление в корзину...")
    clicked = await _find_and_click_product(browser, product_name)
    if not clicked:
        await browser.take_screenshot(f"product_not_found_{session_id}.png")
        return {
            "success": False,
            "added_to_cart": False,
            "checkout_opened": False,
            "error": f"Товар '{product_name}' не найден на странице магазина.",
            "url": browser.page.url,
            "session_id": session_id,
        }

    logger.info("Управление корзиной: проверка количества и Checkout...")
    try:
        cart_result = await _manage_cart_and_checkout(
            browser, product_name, desired_qty=1
        )
    except Exception as e:
        logger.exception("Ошибка при управлении корзиной/Checkout")
        return {
            "success": False,
            "added_to_cart": True,
            "checkout_opened": False,
            "error": f"Корзина или Checkout: {e}",
            "url": browser.page.url,
            "session_id": session_id,
        }
    added = cart_result["added"]
    checkout_opened = cart_result["checkout_opened"]
    return {
        "success": added and checkout_opened,
        "added_to_cart": added,
        "checkout_opened": checkout_opened,
        "url": browser.page.url,
        "screenshot": f"store_{game}_{session_id}.png",
        "message": (
            f"Товар «{product_name}» добавлен в корзину, окно оформления заказа открыто"
            if (added and checkout_opened)
            else (
                f"Товар «{product_name}» добавлен в корзину"
                if added
                else "Корзина или Checkout не найдены"
            )
        ),
        "session_id": session_id,
    }


class PurchaseRequest(BaseModel):
    """Запрос на покупку товара в магазине."""

    email: EmailStr
    verification_code: Optional[str] = None  # Код верификации (если уже известен)
    email_password: Optional[str] = (
        None  # Пароль для доступа к email (для получения кода)
    )
    game: str = "brawl-stars"  # Игра: "brawl-stars" или "clash-royale"
    product_name: str = "80 Gems"  # Название товара для поиска
    product_type: str = "gems"  # Тип товара: "gems", "cards", etc.


@router.post("/supercell/purchase")
async def purchase_product(request: PurchaseRequest):
    """
    Покупка товара в Supercell Store.

    На Windows Patchright требует ProactorEventLoop (create_subprocess_exec).
    Uvicorn использует SelectorEventLoop, поэтому весь flow запускается
    в отдельном потоке со своим ProactorEventLoop.
    """
    import sys as _sys

    if _sys.platform == "win32":

        def _run_in_proactor():
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_purchase_flow(request))
            finally:
                loop.close()

        return await asyncio.get_event_loop().run_in_executor(None, _run_in_proactor)
    return await _purchase_flow(request)


async def _purchase_flow(request: PurchaseRequest):
    """Вся логика покупки. На Windows вызывается из потока с ProactorEventLoop."""
    browser = BrowserAutomation()
    session_id = f"purchase_{request.email.replace('@', '_at_')}_{request.game}"
    last_error = None

    for block_attempt in range(MAX_BLOCK_RETRIES):
        try:
            logger.info(
                f"Начало покупки товара '{request.product_name}' в {request.game} для {request.email}"
            )

            # Шаг 1: Авторизация в Supercell Store (порядок как в full-auth: store → cookies → вход)
            logger.info("Шаг 1: Авторизация в Supercell Store...")
            await browser.start()

            # Прогрев: посещение supercell.com до store — снижает вероятность Cloudflare-блокировки
            # (как в supercell_auth_routes.py — естественная цепочка для антибота)
            if getattr(settings, "BROWSER_WARMUP_VISIT_SUPERCELL", True):
                try:
                    logger.info("Прогрев: переход на supercell.com перед store...")
                    await browser.page.goto(
                        "https://www.supercell.com",
                        wait_until="domcontentloaded",
                        timeout=20000,
                    )
                    await browser.human_like_delay(2000, 4000)
                    logger.info("Прогрев supercell.com завершён")
                except Exception as warmup_err:
                    logger.debug("Прогрев supercell.com пропущен: %s", warmup_err)

            # Переход на store, пауза, принятие cookies
            logger.info("Переход на store.supercell.com...")
            for _store_attempt in range(2):
                try:
                    await browser.page.goto(
                        "https://store.supercell.com",
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    break
                except Exception as store_err:
                    if _store_attempt == 0:
                        logger.warning(
                            "Первая попытка загрузки store не удалась (%s), повтор...",
                            store_err,
                        )
                        await asyncio.sleep(3)
                    else:
                        raise
            await browser.page.wait_for_timeout(3000)
            cookies_ok = await _accept_cookies(browser)
            if not cookies_ok:
                await browser.page.wait_for_timeout(2500)
                await _accept_cookies(browser)
            await browser.human_like_delay(2000, 3000)

            current_url = browser.page.url
            page_text = await browser.page.evaluate(
                "() => document.body.innerText.toLowerCase()"
            )
            is_logged_in = (
                "store.supercell.com" in current_url
                and "login" not in current_url.lower()
                and (
                    "logout" in page_text
                    or "sign out" in page_text
                    or "account" in page_text
                )
            )

            if not is_logged_in:
                logger.info(
                    "Требуется авторизация, выполняем вход в том же браузере..."
                )
                from app.core.email_code_reader import EmailCodeReader

                login_selectors = [
                    'a:has-text("Log in")',
                    'a:has-text("Sign in")',
                    'button:has-text("Log in")',
                    '[href*="login"]',
                    "text=Log in",
                ]
                login_clicked = False
                for selector in login_selectors:
                    try:
                        el = await browser.page.query_selector(selector)
                        if el and await el.is_visible():
                            await el.click()
                            login_clicked = True
                            logger.info(f"Кнопка входа найдена: {selector}")
                            break
                    except Exception:
                        continue
                if not login_clicked:
                    try:
                        await browser.page.click("text=Log in", timeout=5000)
                        login_clicked = True
                    except Exception:
                        pass

                # ── Вспомогательная функция: ожидание прохождения Cloudflare challenge ──
                async def _wait_for_cloudflare(max_wait_sec: int = 30) -> bool:
                    """
                    Ожидает, пока Cloudflare challenge страница ("Just a moment..." / "Checking your browser")
                    не разрешится в реальную страницу. Возвращает True если challenge прошёл, False если нет.
                    Cloudflare challenge типичен для VPS/datacenter IP без прокси.
                    """
                    cf_phrases = (
                        "just a moment",
                        "checking your browser",
                        "please wait",
                        "ray id",
                        "cloudflare",
                        "enable javascript",
                        "enable cookies",
                        "one more step",
                        "please turn javascript on",
                        "attention required",
                    )
                    for elapsed in range(max_wait_sec):
                        try:
                            body_text = (
                                await browser.page.evaluate(
                                    "() => document.body.innerText"
                                )
                            ).lower()
                            title = (
                                await browser.page.evaluate("() => document.title")
                            ).lower()
                            is_cf = any(
                                p in body_text or p in title for p in cf_phrases
                            )
                            has_email_input = bool(
                                await browser.page.query_selector(
                                    'input[type="email"], input[name="email"]'
                                )
                            )
                            if not is_cf or has_email_input:
                                if elapsed > 0:
                                    logger.info(
                                        "Cloudflare challenge прошёл через %d сек. URL: %s",
                                        elapsed,
                                        browser.page.url,
                                    )
                                return True
                            if elapsed == 0:
                                logger.warning(
                                    "Обнаружен Cloudflare challenge (%s). "
                                    "Ждём до %d сек. "
                                    "Это типично для VPS-IP без резидентного прокси. "
                                    "Рекомендуется включить прокси (Novada/BrightData) в .env.",
                                    title or body_text[:80],
                                    max_wait_sec,
                                )
                                await browser.take_screenshot(
                                    f"cloudflare_challenge_{session_id}.png"
                                )
                        except Exception:
                            pass
                        await asyncio.sleep(1)
                    logger.error(
                        "Cloudflare challenge не прошёл за %d сек. URL: %s — "
                        "IP-адрес сервера заблокирован. Включите резидентный прокси в .env.",
                        max_wait_sec,
                        browser.page.url,
                    )
                    return False

                # ── Навигация на страницу логина ─────────────────────────────────────────
                if login_clicked:
                    logger.info("Переход на страницу авторизации (ждём редирект)...")
                    try:
                        await browser.page.wait_for_url(
                            lambda url: (
                                "accounts.supercell.com" in url
                                or "id.supercell.com" in url
                            ),
                            timeout=15000,
                        )
                        logger.info(f"Редирект выполнен: {browser.page.url}")
                    except Exception:
                        logger.warning(
                            "Редирект не произошёл, переходим на accounts.supercell.com/en/login"
                        )
                        login_fallback_urls = [
                            "https://accounts.supercell.com/en/login",
                            "https://accounts.supercell.com/login",
                        ]
                        for fallback_url in login_fallback_urls:
                            try:
                                await browser.page.goto(
                                    fallback_url,
                                    wait_until="domcontentloaded",
                                    timeout=30000,
                                )
                                logger.info("Переход на fallback URL: %s", fallback_url)
                                break
                            except Exception as e:
                                logger.debug(
                                    "Ошибка перехода на %s: %s", fallback_url, e
                                )
                else:
                    logger.warning(
                        "Кнопка входа не найдена, переходим напрямую на страницу логина"
                    )
                    login_fallback_urls = [
                        "https://accounts.supercell.com/en/login",
                        "https://accounts.supercell.com/login",
                    ]
                    for fallback_url in login_fallback_urls:
                        try:
                            await browser.page.goto(
                                fallback_url,
                                wait_until="domcontentloaded",
                                timeout=30000,
                            )
                            logger.info("Переход на fallback URL: %s", fallback_url)
                            break
                        except Exception as e:
                            logger.debug("Ошибка перехода на %s: %s", fallback_url, e)

                try:
                    await browser.page.wait_for_load_state(
                        "domcontentloaded", timeout=15000
                    )
                except Exception:
                    pass
                logger.info("Страница логина загружена: %s", browser.page.url)

                # Ожидаем Cloudflare challenge (если VPS-IP без прокси)
                await _wait_for_cloudflare(max_wait_sec=30)

                await browser.human_like_delay(800, 1500)
                await _accept_cookies(browser)
                await browser.human_like_delay(500, 1000)

                # Скриншот страницы логина — ДО поиска email, чтобы было видно что произошло
                await browser.take_screenshot(
                    f"login_page_before_email_{session_id}.png"
                )
                logger.info(
                    "Страница логина — URL: %s | title: %s",
                    browser.page.url,
                    await browser.page.evaluate("() => document.title"),
                )

                current_url = browser.page.url
                if "id.supercell.com" in current_url:
                    for sel in [
                        'button:has-text("LOG IN")',
                        'button:has-text("Log in")',
                        'a:has-text("Log in")',
                    ]:
                        try:
                            el = await browser.page.wait_for_selector(sel, timeout=4000)
                            if el and await el.is_visible():
                                await el.click()
                                logger.info(
                                    f"Кнопка входа на странице id нажата: {sel}"
                                )
                                await browser.human_like_delay(2000, 3000)
                                await _accept_cookies(browser)
                                break
                        except Exception:
                            continue

                # Даём reCAPTCHA / SPA-роутеру время «устояться»
                await browser.human_like_delay(6000, 11000)
                try:
                    for _ in range(random.randint(2, 4)):
                        rx = random.randint(150, 700)
                        ry = random.randint(200, 500)
                        await browser.page.mouse.move(rx, ry)
                        await browser.page.wait_for_timeout(random.randint(400, 900))
                    await browser.page.evaluate(
                        "window.scrollBy({ top: 60, behavior: 'smooth' })"
                    )
                    await browser.page.wait_for_timeout(random.randint(500, 1200))
                except Exception:
                    pass
                await browser.human_like_delay(1000, 2000)

                try:
                    page_text_pre = (
                        await browser.page.evaluate("() => document.body.innerText")
                    ).lower()
                    if (
                        "something went wrong" in page_text_pre
                        or "try again later" in page_text_pre
                    ):
                        logger.warning(
                            "«Something went wrong» на странице логина — перезагрузка"
                        )
                        await browser.page.reload(
                            wait_until="domcontentloaded", timeout=60000
                        )
                        await browser.human_like_delay(8000, 12000)
                        await _accept_cookies(browser)
                        await browser.human_like_delay(1000, 2000)
                except Exception:
                    pass

                email_selectors = [
                    'input[type="email"]',
                    'input[name="email"]',
                    'input[name="username"]',
                    'input[name="identifier"]',
                    'input[id*="email"]',
                    'input[id*="username"]',
                    'input[id*="identifier"]',
                    'input[placeholder*="email" i]',
                    'input[placeholder*="Email" i]',
                    'input[aria-label*="email" i]',
                ]
                email_input = None
                found_email_selector = None
                for i, selector in enumerate(email_selectors):
                    timeout_ms = 30000 if i == 0 else 10000
                    try:
                        email_input = await browser.page.wait_for_selector(
                            selector, timeout=timeout_ms
                        )
                        if email_input:
                            found_email_selector = selector
                            logger.info(f"Найдено поле email: {selector}")
                            break
                    except Exception:
                        continue

                if not email_input:
                    logger.info(
                        "Поле email не найдено с первой попытки — принимаем cookies и ждём ещё..."
                    )
                    await _accept_cookies(browser)
                    await browser.human_like_delay(2000, 3000)
                    # Ещё одно ожидание Cloudflare (мог не пройти сразу)
                    await _wait_for_cloudflare(max_wait_sec=20)
                    for selector in email_selectors:
                        try:
                            email_input = await browser.page.wait_for_selector(
                                selector, timeout=8000
                            )
                            if email_input:
                                found_email_selector = selector
                                break
                        except Exception:
                            continue

                if not email_input:
                    # Финальная попытка — попробовать альтернативный URL логина
                    alt_login_url = (
                        "https://accounts.supercell.com/en/login"
                        if "en/login" not in browser.page.url
                        else "https://accounts.supercell.com/login"
                    )
                    logger.warning(
                        "Email-поле не найдено на %s — пробуем альтернативный URL: %s",
                        browser.page.url,
                        alt_login_url,
                    )
                    try:
                        await browser.page.goto(
                            alt_login_url, wait_until="domcontentloaded", timeout=30000
                        )
                        await _wait_for_cloudflare(max_wait_sec=20)
                        await browser.human_like_delay(3000, 5000)
                        await _accept_cookies(browser)
                        for selector in email_selectors:
                            try:
                                email_input = await browser.page.wait_for_selector(
                                    selector, timeout=10000
                                )
                                if email_input:
                                    found_email_selector = selector
                                    break
                            except Exception:
                                continue
                    except Exception as alt_err:
                        logger.warning(
                            "Альтернативный URL также не сработал: %s", alt_err
                        )

                if not email_input:
                    # Сбор диагностики перед броском исключения
                    current_url_diag = browser.page.url
                    page_title_diag = ""
                    page_text_diag = ""
                    page_html_short = ""
                    try:
                        page_title_diag = await browser.page.evaluate(
                            "() => document.title"
                        )
                        page_text_diag = (
                            await browser.page.evaluate("() => document.body.innerText")
                        ).lower()[:500]
                        page_html_short = (await browser.page.content())[:1000]
                        logger.error(
                            "Email-поле не найдено.\n"
                            "  URL: %s\n"
                            "  Title: %s\n"
                            "  Текст страницы (первые 500 символов): %s\n"
                            "  HTML (первые 1000 символов): %s",
                            current_url_diag,
                            page_title_diag,
                            page_text_diag,
                            page_html_short,
                        )
                        await browser.take_screenshot(
                            f"no_email_field_final_{session_id}.png"
                        )
                    except Exception:
                        pass

                    cf_phrases_check = (
                        "just a moment",
                        "checking your browser",
                        "cloudflare",
                        "ray id",
                        "one more step",
                    )
                    if any(p in page_text_diag for p in cf_phrases_check):
                        raise Exception(
                            f"Cloudflare заблокировал доступ к странице входа Supercell (URL: {current_url_diag}, title: '{page_title_diag}'). "
                            "Это происходит при запуске с IP датацентра/VPS без резидентного прокси. "
                            "Решение: включите резидентный прокси в .env (NOVADA_ENABLED=true + ключи, или BRIGHTDATA_ENABLED=true). "
                            "Скриншот: screenshots/cloudflare_challenge_*.png"
                        )
                    if (
                        "something went wrong" in page_text_diag
                        or "try again later" in page_text_diag
                    ):
                        raise Exception(
                            f"Supercell ID вернул «Something went wrong» (URL: {current_url_diag}). "
                            "Попробуйте позже или с другим прокси."
                        )
                    if (
                        "blocked" in page_text_diag
                        or "unusual activity" in page_text_diag
                    ):
                        raise Exception(
                            f"Supercell заблокировал вход (unusual activity) (URL: {current_url_diag}). "
                            "Используйте резидентный прокси или попробуйте позже."
                        )
                    raise Exception(
                        f"Поле email не найдено на странице входа. "
                        f"URL: {current_url_diag} | Title: '{page_title_diag}'. "
                        "Возможные причины: Cloudflare challenge (VPS без прокси), "
                        "страница не загрузилась или изменилась структура Supercell ID. "
                        "Скриншот: screenshots/no_email_field_final_*.png и login_page_before_email_*.png. "
                        "Рекомендации: 1) включить резидентный прокси (Novada/BrightData), "
                        "2) BROWSER_USE_PATCHRIGHT=true в .env, "
                        "3) проверить скриншоты для точной диагностики."
                    )

                page_text_before = (
                    await browser.page.evaluate("() => document.body.innerText")
                ).lower()
                if (
                    "blocked your login request" in page_text_before
                    or "unusual activity" in page_text_before
                ):
                    raise Exception(
                        "Supercell заблокировал вход (unusual activity). Отключите прокси (PROXY_ENABLED=false) или попробуйте позже."
                    )

                await browser.human_like_delay(800, 1500)
                try:
                    el = await browser.page.query_selector(found_email_selector)
                    if el:
                        box = await el.bounding_box()
                        if box:
                            await browser.page.mouse.move(
                                box["x"] + box["width"] * 0.3,
                                box["y"] + box["height"] * 0.5,
                            )
                            await browser.page.wait_for_timeout(
                                random.randint(200, 400)
                            )
                except Exception:
                    pass
                await browser.human_like_type(
                    found_email_selector, request.email, delay_between_chars=130
                )
                await browser.human_like_delay(800, 1500)
                entered_email = await browser.page.input_value(found_email_selector)
                if entered_email != request.email:
                    await browser.page.keyboard.press("Control+a")
                    await browser.page.wait_for_timeout(random.randint(50, 150))
                    await browser.page.keyboard.press("Delete")
                    await browser.human_like_delay(200, 400)
                    await browser.human_like_type(
                        found_email_selector, request.email, delay_between_chars=130
                    )
                    await browser.human_like_delay(500, 1000)

                page_text_before_click = (
                    await browser.page.evaluate("() => document.body.innerText")
                ).lower()
                if (
                    "blocked your login request" in page_text_before_click
                    or "unusual activity" in page_text_before_click
                ):
                    raise Exception(
                        "Supercell заблокировал вход (unusual activity) на шаге ввода email. "
                        "Отключите прокси (PROXY_ENABLED=false) или попробуйте резидентный прокси."
                    )

                form_scoped = [
                    f"form:has({found_email_selector}) button[type='submit']",
                    f"form:has({found_email_selector}) button:has-text('LOG IN')",
                    f"form:has({found_email_selector}) button:has-text('Log in')",
                    f"form:has({found_email_selector}) button",
                ]
                continue_selectors = form_scoped + [
                    'button:has-text("Send code")',
                    'button:has-text("Get code")',
                    'button:has-text("Next")',
                    'button:has-text("Continue")',
                    'button:has-text("Log in")',
                    'button:has-text("Sign in")',
                    'button[type="submit"]',
                    'input[type="submit"]',
                ]

                if getattr(settings, "CAPTCHA_2CAPTCHA_API_KEY", ""):
                    try:
                        from app.core.recaptcha_solver import solve_recaptcha_enterprise

                        captcha_token = await solve_recaptcha_enterprise(
                            api_key=settings.CAPTCHA_2CAPTCHA_API_KEY,
                            page_url=browser.page.url
                            or "https://accounts.supercell.com/login",
                            timeout=120,
                        )
                        if captcha_token:
                            await browser.page.evaluate(
                                """(token) => {
                                    window.__2captchaToken = token;
                                    var check = setInterval(function() {
                                        if (window.grecaptcha && window.grecaptcha.enterprise) {
                                            clearInterval(check);
                                            var real = window.grecaptcha.enterprise.execute;
                                            if (real && !real.__patched) {
                                                window.grecaptcha.enterprise.execute = function() {
                                                    return Promise.resolve(window.__2captchaToken || null);
                                                };
                                                window.grecaptcha.enterprise.execute.__patched = true;
                                            }
                                        }
                                    }, 100);
                                    setTimeout(function() { clearInterval(check); }, 5000);
                                }""",
                                captcha_token,
                            )
                            await browser.human_like_delay(500, 1000)
                            try:
                                await browser.page.evaluate(
                                    """(token) => {
                                        var form = document.querySelector('form');
                                        if (form && !form.querySelector('input[name="g-recaptcha-response"]')) {
                                            var inp = document.createElement('input');
                                            inp.type = 'hidden';
                                            inp.name = 'g-recaptcha-response';
                                            inp.value = token;
                                            form.appendChild(inp);
                                        }
                                    }""",
                                    captcha_token,
                                )
                            except Exception:
                                pass
                            logger.info(
                                "2Captcha: токен reCAPTCHA подставлен перед LOG IN"
                            )
                        else:
                            logger.warning(
                                "2Captcha не вернул токен — продолжаем без него"
                            )
                    except Exception as e:
                        logger.debug(f"2Captcha при покупке: {e}")

                await browser.human_like_delay(1000, 2000)

                continue_clicked = False
                for selector in continue_selectors:
                    try:
                        element = await browser.page.wait_for_selector(
                            selector, timeout=3000
                        )
                        if not element or not await element.is_visible():
                            continue
                        box = await element.bounding_box()
                        if not box:
                            continue
                        target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
                        target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
                        try:
                            email_box = await browser.page.query_selector(
                                found_email_selector
                            )
                            if email_box:
                                eb = await email_box.bounding_box()
                                start_x = (
                                    eb["x"] + eb["width"] * 0.5 if eb else target_x - 50
                                )
                                start_y = (
                                    eb["y"] + eb["height"] * 0.5
                                    if eb
                                    else target_y - 80
                                )
                            else:
                                start_x, start_y = target_x - 50, target_y - 80
                        except Exception:
                            start_x, start_y = target_x - 50, target_y - 80
                        mid_x = (start_x + target_x) / 2 + random.uniform(-20, 20)
                        mid_y = (start_y + target_y) / 2 + random.uniform(-15, 15)
                        steps = random.randint(12, 20)
                        for i in range(steps):
                            t = (i + 1) / steps
                            bx = (
                                (1 - t) ** 2 * start_x
                                + 2 * (1 - t) * t * mid_x
                                + t**2 * target_x
                            )
                            by = (
                                (1 - t) ** 2 * start_y
                                + 2 * (1 - t) * t * mid_y
                                + t**2 * target_y
                            )
                            await browser.page.mouse.move(
                                bx + random.uniform(-1, 1), by + random.uniform(-1, 1)
                            )
                            await browser.page.wait_for_timeout(random.randint(8, 20))
                        await browser.page.wait_for_timeout(random.randint(80, 180))
                        await browser.page.mouse.click(
                            target_x, target_y, delay=random.randint(60, 130)
                        )
                        continue_clicked = True
                        logger.info(f"Кнопка LOG IN нажата (mouse, Безье): {selector}")
                        break
                    except Exception as e:
                        logger.debug(f"Селектор LOG IN {selector}: {e}")
                        continue

                if not continue_clicked:
                    try:
                        await browser.page.keyboard.press("Tab")
                        await browser.page.wait_for_timeout(random.randint(150, 300))
                        await browser.page.keyboard.press("Enter")
                        continue_clicked = True
                        logger.info("Кнопка LOG IN нажата через Tab+Enter")
                    except Exception:
                        pass

                await browser.human_like_delay(1000, 2000)
                await _accept_cookies(browser)
                await browser.human_like_delay(1500, 2500)
                page_text_after = (
                    await browser.page.evaluate("() => document.body.innerText")
                ).lower()
                if (
                    "blocked your login request" in page_text_after
                    or "unusual activity" in page_text_after
                ):
                    raise Exception(
                        "Supercell заблокировал вход после отправки email (unusual activity). "
                        "Попробуйте: PROXY_ENABLED=false, 2Captcha (CAPTCHA_2CAPTCHA_API_KEY), резидентный прокси или BROWSER_USE_PATCHRIGHT=true."
                    )

                verification_code = request.verification_code
                code_entered_manually = False

                # Режим ручного ввода: если код не передан — ждём 2 минуты, пока пользователь введёт код вручную
                if not verification_code and not request.email_password:
                    logger.info(
                        "Ожидание до 2 минут — введите код верификации вручную в браузере."
                    )
                    manual_wait_seconds = 120
                    deadline = asyncio.get_event_loop().time() + manual_wait_seconds
                    code_input_selectors = [
                        'input[type="tel"]',
                        'input[autocomplete="one-time-code"]',
                        'input[inputmode="numeric"]',
                        'input[placeholder*="123" i]',
                    ]
                    while asyncio.get_event_loop().time() < deadline:
                        try:
                            btn_loc = browser.page.get_by_role(
                                "button", name=re.compile(r"continue", re.I)
                            )
                            if await btn_loc.count() > 0:
                                btn = btn_loc.first
                                aria = (await btn.get_attribute("aria-disabled")) or ""
                                disabled = False
                                try:
                                    disabled = await btn.is_disabled()
                                except Exception:
                                    disabled = "true" in aria.strip().lower()
                                if not disabled:
                                    await btn.click()
                                    logger.info(
                                        "Код введён вручную, нажата кнопка CONTINUE."
                                    )
                                    code_entered_manually = True
                                    break
                        except Exception:
                            pass
                        try:
                            for sel in code_input_selectors:
                                inp = await browser.page.query_selector(sel)
                                if inp:
                                    val = await inp.get_attribute("value") or ""
                                    if len(val.replace(" ", "").replace("-", "")) >= 6:
                                        btn_loc = browser.page.get_by_role(
                                            "button", name=re.compile(r"continue", re.I)
                                        )
                                        if await btn_loc.count() > 0:
                                            await btn_loc.first.click()
                                            logger.info(
                                                "Обнаружено 6 цифр в поле кода, нажата кнопка CONTINUE."
                                            )
                                            code_entered_manually = True
                                    break
                            if code_entered_manually:
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(1)
                    if not code_entered_manually:
                        raise Exception(
                            "Истекло 2 минуты ожидания ручного ввода кода. "
                            "Введите код в браузере в течение 2 минут или передайте verification_code / email_password."
                        )
                else:
                    # Получаем код верификации из запроса или email
                    if not verification_code and request.email_password:
                        logger.info("Ожидание кода верификации из email...")
                        email_reader = EmailCodeReader(
                            request.email, request.email_password
                        )
                        verification_code = email_reader.get_supercell_code(timeout=120)

                    if not verification_code:
                        raise Exception(
                            "Код верификации не предоставлен. "
                            "Введите код верификации из письма Supercell или предоставьте email_password."
                        )

                    verification_code = (
                        verification_code.replace(" ", "").replace("-", "").strip()
                    )
                    code_selectors = [
                        'input[type="tel"]',
                        'input[autocomplete="one-time-code"]',
                        'input[inputmode="numeric"]',
                        'input[placeholder*="123" i]',
                    ]
                    code_input = None
                    for selector in code_selectors:
                        try:
                            code_input = await browser.page.wait_for_selector(
                                selector, timeout=30000
                            )
                            if code_input:
                                break
                        except Exception:
                            continue

                    if code_input:
                        await code_input.fill("")
                        await code_input.type(verification_code, delay=80)
                        await browser.human_like_delay(500, 1000)
                        await code_input.focus()
                        await browser.page.keyboard.press("Enter")
                        await browser.human_like_delay(2000, 3000)

                    await browser.page.wait_for_timeout(5000)
                    try:
                        await browser.page.wait_for_url(
                            lambda url: (
                                "store.supercell.com" in url
                                and "login" not in url.lower()
                            ),
                            timeout=30000,
                        )
                    except Exception:
                        pass

                logger.info("Авторизация завершена, продолжаем покупку...")
                await browser.human_like_delay(2000, 3000)

            # Шаг 2–5: Единый путь покупки после входа (как в purchase_demo и manual_login_gpay_demo)
            purchase_result = await run_purchase_flow_after_login(
                browser, request.game, request.product_name, session_id
            )
            if not purchase_result.get("success") and purchase_result.get("error"):
                raise Exception(purchase_result["error"])
            added = purchase_result["added_to_cart"]
            checkout_opened = purchase_result["checkout_opened"]

            result = {
                "success": True,
                "session_id": session_id,
                "email": request.email,
                "game": request.game,
                "product_name": request.product_name,
                "product_info": {
                    "found": True,
                    "price": None,
                    "confidence": None,
                    "description": request.product_name,
                },
                "added_to_cart": added,
                "checkout_opened": checkout_opened,
                "screenshot": f"after_add_to_cart_{session_id}.png",
                "checkout_screenshot": f"checkout_{session_id}.png"
                if checkout_opened
                else None,
                "url": purchase_result.get("url", browser.page.url),
                "message": purchase_result.get("message", ""),
                "proxy_used": browser.current_proxy is not None,
                "proxy_server": browser.current_proxy.get("server")
                if browser.current_proxy
                else None,
            }

            # Шаг 6: Оплата через Google Pay
            gpay_result = {}
            if checkout_opened and getattr(settings, "GOOGLE_PAY_ENABLED", False):
                google_email = getattr(settings, "GOOGLE_EMAIL", "") or ""
                google_app_password = getattr(settings, "GOOGLE_APP_PASSWORD", "") or ""
                if google_email and google_app_password:
                    logger.info("Шаг 6: Оплата через Google Pay...")
                    gpay_result = await handle_google_pay(
                        browser=browser,
                        email=google_email,
                        app_password=google_app_password,
                        payment_timeout=getattr(settings, "PAYMENT_TIMEOUT", 300),
                        product_name=request.product_name,
                    )
                    logger.info(f"Google Pay результат: {gpay_result}")
                else:
                    logger.info(
                        "Google Pay отключён: GOOGLE_EMAIL или GOOGLE_APP_PASSWORD не заданы"
                    )
            else:
                logger.info(
                    "Google Pay пропущен: checkout не открыт или GOOGLE_PAY_ENABLED=false"
                )

            result.update(
                {
                    "payment_success": gpay_result.get("success", False),
                    "google_pay_clicked": gpay_result.get("google_pay_clicked", False),
                    "payment_confirmed": gpay_result.get("payment_confirmed", False),
                    "payment_verified": gpay_result.get("payment_verified", False),
                    "screenshot_success": gpay_result.get("screenshot_success"),
                    "screenshot_account": gpay_result.get("screenshot_account"),
                    "cards_removed": gpay_result.get("cards_removed", 0),
                    "payment_error": gpay_result.get("error"),
                }
            )

            try:
                video_path = await browser.close()
                if video_path:
                    result["video"] = video_path
            except Exception as close_err:
                logger.debug(f"Ошибка при закрытии браузера: {close_err}")

            return result

        except Exception as e:
            last_error = e
            logger.error(f"Ошибка покупки товара: {e}")
            err_lower = str(e).lower()
            block_phrases = (
                "unusual activity",
                "blocked your login",
                "blocked",
                "blocked your login request",
            )
            is_block = any(p in err_lower for p in block_phrases)
            if (
                is_block
                and getattr(browser, "current_proxy", None)
                and block_attempt < MAX_BLOCK_RETRIES - 1
            ):
                logger.warning(
                    f"Блокировка Supercell (unusual activity), повтор с новым IP "
                    f"(попытка {block_attempt + 1}/{MAX_BLOCK_RETRIES})..."
                )
                proxy_manager.mark_proxy_failed(browser.current_proxy)
                try:
                    await browser.close()
                except Exception:
                    pass
                continue

            screenshot_path = None
            try:
                if browser.page:
                    screenshot_path = await browser.take_screenshot(
                        f"purchase_error_{session_id}.png"
                    )
            except Exception:
                pass
            video_path = None
            try:
                video_path = await browser.close()
            except Exception:
                pass
            detail = {
                "error": str(e),
                "screenshot": str(screenshot_path) if screenshot_path else None,
                "proxy_used": getattr(browser, "current_proxy", None) is not None,
                "proxy_server": browser.current_proxy.get("server")
                if getattr(browser, "current_proxy", None)
                else None,
            }
            if video_path:
                detail["video"] = video_path
            if (
                "timed_out" in err_lower
                or "err_timed_out" in err_lower
                or "err_connection" in err_lower
            ):
                detail["hint"] = (
                    "Прокси не успел загрузить страницу. Попробуйте PROXY_ENABLED=false или проверьте прокси."
                )
            if is_block:
                detail["hint"] = (
                    "Supercell заблокировал вход. Попробуйте: PROXY_ENABLED=false, "
                    "2Captcha (CAPTCHA_2CAPTCHA_API_KEY), BROWSER_USE_PATCHRIGHT=true или резидентный прокси."
                )
            raise HTTPException(status_code=500, detail=detail)

    if last_error:
        raise HTTPException(status_code=500, detail={"error": str(last_error)})
