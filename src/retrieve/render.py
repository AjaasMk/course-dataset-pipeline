from typing import Callable, Optional

from src.retrieve.probe import BROWSER_HEADERS, MIN_LINKS, MIN_TEXT_CHARS, classify, ProbeVerdict

DEFAULT_TIMEOUT_MS = 60_000
SETTLE_MS = 3_000
# "networkidle" waits for 500ms of zero network activity, which never arrives on
# a site that polls or beacons -- so it fails at any timeout rather than being a
# duration problem. MoSPI timed out at 30s under networkidle and loads in 5s
# under domcontentloaded plus a settle delay.
WAIT_UNTIL = "domcontentloaded"


class RenderError(Exception):
    pass


def is_render_worthwhile(html: str) -> bool:
    """Whether a page needs a browser at all.

    Rendering costs a browser launch, so it is only worth doing where a plain
    fetch produced neither readable text nor a usable link structure. The NIRF
    year index has almost no visible text and is still perfectly machine-usable,
    which is why link density counts here exactly as it does in the probe.
    """
    return classify(200, html).verdict is ProbeVerdict.JS_REQUIRED


def _default_launcher():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderError(
            "playwright is not installed; run pip install playwright && playwright install chromium"
        ) from exc

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    browser._owning_playwright = playwright
    return browser


class RenderedFetcher:
    """Fetches a page with a headless browser, for sources whose content only
    exists after JavaScript runs.

    This is the last step of the source-escalation policy, not the first: it is
    used only where realistic headers and an official open-data route have both
    been tried. It never attempts to defeat a CAPTCHA or bot challenge -- a
    source that presents one stays blocked.
    """

    def __init__(
        self,
        launcher: Optional[Callable[[], object]] = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        settle_ms: int = SETTLE_MS,
        wait_until: str = WAIT_UNTIL,
    ):
        self.launcher = launcher or _default_launcher
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms
        self.wait_until = wait_until

    def fetch(self, url: str) -> str:
        try:
            browser = self.launcher()
        except Exception as exc:
            raise RenderError(f"could not start a browser: {exc}") from exc

        try:
            page = browser.new_page(user_agent=BROWSER_HEADERS["User-Agent"])
            page.goto(url, timeout=self.timeout_ms, wait_until=self.wait_until)
            page.wait_for_timeout(self.settle_ms)
            return page.content()
        except Exception as exc:
            raise RenderError(f"rendering {url} failed: {exc}") from exc
        finally:
            try:
                browser.close()
            except Exception:
                pass
            owner = getattr(browser, "_owning_playwright", None)
            if owner is not None:
                try:
                    owner.stop()
                except Exception:
                    pass
