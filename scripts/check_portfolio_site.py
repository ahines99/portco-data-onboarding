"""Read-only browser QA; run with `uv run --with playwright python -m scripts.check_portfolio_site`.

Serve docs on localhost:8767 first. Uses installed Edge on Windows; Chromium elsewhere.
Screenshots show the actual site, not a mock-up.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

from src.settings import PROJECT_ROOT


def main() -> None:
    assets = PROJECT_ROOT / "docs/assets"
    assets.mkdir(parents=True, exist_ok=True)
    edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(edge) if edge.exists() else None, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1080}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8767", wait_until="networkidle")
        page.get_by_role("button", name="Play", exact=True).click()
        page.wait_for_function("document.querySelector('#seek').value > 0.2")
        page.get_by_role("button", name="Pause", exact=True).click()
        page.locator("#seek").evaluate("el => {el.value=el.max; el.dispatchEvent(new Event('input'));}")
        assert "[ok] success path" in page.locator("#terminal").inner_text()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(assets / "site-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(assets / "site-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()
    print("PASS: replay play/pause/seek, transcript, desktop/mobile overflow, no JS errors; screenshots captured")


if __name__ == "__main__":
    main()
