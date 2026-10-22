"""End-to-end: the core loop in a real browser.

    pip install -r requirements-dev.txt && python -m playwright install chromium
    python -m pytest e2e            # starts its own server on port 8765 with a fresh database
"""

import os
import socket
import subprocess
import sys
import tempfile
import time

import pytest
from playwright.sync_api import expect, sync_playwright

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


PORT = _free_port()
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def server():
    db = os.path.join(tempfile.mkdtemp(prefix="mrigel-e2e-"), "e2e.db")
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "SECRET_KEY": "e2e", "RUN_JOBS": "0", "DEMO_MODE": "0"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    yield proc
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def page(server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        problems: list[str] = []
        opened: list[str] = []
        # the WhatsApp tab is a redirect after a form post: record it (routes do not see redirects)
        context.on("request", lambda r: opened.append(r.url) if r.url.startswith("https://wa.me/") else None)
        pg = context.new_page()
        pg.on("console", lambda m: problems.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        pg.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
        pg.on("response", lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 500 else None)
        pg.problems, pg.opened = problems, opened
        yield pg
        context.close()
        browser.close()
        assert not [p for p in problems if "wa.me" not in p], problems


def test_core_loop_in_arabic(page):
    page.goto(BASE + "/")
    expect(page.get_by_role("heading", level=1)).to_contain_text("ما تبعتش كولي")
    page.get_by_role("link", name="ابدا مجاناً").first.click()

    page.get_by_label("اسم المتجر").fill("Dzair Shop")
    page.get_by_label("اسمك").fill("Sami")
    page.get_by_label("البريد الإلكتروني").fill("sami@shop.dz")
    page.get_by_label("كلمة السر").fill("password123")
    page.get_by_role("button", name="أنشئ الحساب").click()
    expect(page.get_by_role("heading", name="لوحة التحكم")).to_be_visible()

    page.get_by_role("link", name="زيد طلبية").click()
    page.get_by_label("اسم الزبون").fill("Nesrine Kaci")
    page.get_by_label("رقم الهاتف").fill("0661 23 45 67")
    page.get_by_label("الولاية").select_option("19")
    page.get_by_label("المنتج").fill("Sérum vitamine C")
    page.get_by_label("المجموع (دج)").fill("3200")
    page.get_by_role("button", name="سجّل").click()
    expect(page.locator(".slip-name")).to_have_text("Nesrine Kaci")

    with page.expect_popup() as popup_info:
        page.get_by_role("button", name="ابعت في واتساب").click()
    for _ in range(50):  # the new tab posts the form, then is redirected to wa.me
        if page.opened:
            break
        page.wait_for_timeout(100)
    popup_info.value.close()
    assert page.opened and page.opened[0].startswith("https://wa.me/213661234567?text=")

    page.reload()
    expect(page.locator(".slip .badge")).to_have_text("في انتظار الرد")
    page.get_by_label("انسخ رد الزبون").fill("wah akid, l3chiya")
    page.get_by_role("button", name="افهم الرد").click()
    expect(page.get_by_role("status").filter(has_text="أكّد")).to_be_visible()
    expect(page.locator(".slip .badge")).to_have_text("مؤكدة")
    expect(page.locator(".slip .stamp")).to_contain_text("مريڨل")


def test_keyboard_confirm_from_queue(page):
    page.goto(BASE + "/login")
    page.get_by_label("البريد الإلكتروني").fill("sami@shop.dz")
    page.get_by_label("كلمة السر").fill("password123")
    page.keyboard.press("Enter")
    expect(page.get_by_role("heading", name="لوحة التحكم")).to_be_visible()
    page.goto(BASE + "/orders/new")
    page.get_by_label("اسم الزبون").fill("Karim Ziani")
    page.get_by_label("رقم الهاتف").fill("0770112233")
    page.get_by_label("الولاية").select_option("31")
    page.get_by_label("المجموع (دج)").fill("4800")
    page.get_by_label("المجموع (دج)").press("Enter")
    page.goto(BASE + "/queue")
    expect(page.locator(".slip-name")).to_have_text("Karim Ziani")
    confirm = page.get_by_role("button", name="أكّد", exact=True)
    confirm.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("heading", name="كلش مريڨل!")).to_be_visible()


def test_french_and_mobile(page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(BASE + "/lang/fr")
    page.goto(BASE + "/login")
    page.get_by_label("E-mail").fill("sami@shop.dz")
    page.get_by_label("Mot de passe").fill("password123")
    page.get_by_role("button", name="Se connecter").click()
    expect(page.get_by_role("heading", name="Tableau de bord")).to_be_visible()
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("link", name="Commandes", exact=True).click()
    expect(page.get_by_role("heading", name="Commandes", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal scroll on mobile"
