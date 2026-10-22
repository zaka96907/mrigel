"""Take screenshots of every screen for replica-diff and design review.

    python tools/screens.py [base_url] [out_dir]
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "replica/clone-screens")
OUT.mkdir(parents=True, exist_ok=True)

PUBLIC = [("S00-landing", "/"), ("S01-login", "/login"), ("S01-signup", "/signup")]
PRIVATE = [
    ("S02-dashboard", "/dashboard"),
    ("S03-orders", "/orders"),
    ("S05-queue", "/queue"),
    ("S09-import", "/import"),
    ("S15-blacklist", "/blacklist"),
    ("S14-settings", "/settings"),
    ("S13-team", "/team"),
    ("S03b-new-order", "/orders/new"),
    ("S16-products", "/products"),
    ("S17-finance", "/finance"),
    ("S18-automations", "/automations"),
    ("S19-inbox", "/inbox"),
    ("S20-campaigns", "/campaigns"),
    ("S21-carts", "/carts"),
    ("S22-integrations", "/integrations"),
]


def shoot(page, name, path, width, full=True):
    page.goto(BASE + path, wait_until="networkidle")
    page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=full)


def run(lang: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
            page = context.new_page()
            page.goto(BASE + f"/lang/{lang}")
            for name, path in PUBLIC:
                shoot(page, f"{name}-{lang}", path, width)
            page.goto(BASE + "/demo", wait_until="networkidle")
            for name, path in PRIVATE:
                shoot(page, f"{name}-{lang}", path, width)
            # an order detail: first confirmed order in the list
            page.goto(BASE + "/orders?stage=confirmed", wait_until="networkidle")
            link = page.locator("td.cust a").first
            if link.count():
                link.click()
                page.wait_for_load_state("networkidle")
                page.screenshot(path=str(OUT / f"S04-order-{lang}-{width}.png"), full_page=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    for language in ("ar", "fr"):
        run(language)
    print("saved to", OUT)
