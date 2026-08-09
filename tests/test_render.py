import pytest

from src.retrieve.render import RenderError, RenderedFetcher, is_render_worthwhile


def test_a_js_shell_is_worth_rendering():
    shell = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    assert is_render_worthwhile(shell)


def test_a_server_rendered_page_is_not_worth_rendering():
    page = "<html><body>" + "<p>Real content here.</p>" * 60 + "</body></html>"
    assert not is_render_worthwhile(page)


def test_a_link_dense_index_is_not_worth_rendering():
    # The NIRF year index has no visible text but is perfectly machine-usable;
    # rendering it would spend a browser launch for nothing.
    index = "<html><body>" + "".join(f'<a href="/c{n}.html"></a>' for n in range(20)) + "</body></html>"
    assert not is_render_worthwhile(index)


def test_fetcher_reports_a_clear_error_when_the_browser_is_unavailable(monkeypatch):
    fetcher = RenderedFetcher(launcher=lambda: (_ for _ in ()).throw(OSError("no browser")))

    with pytest.raises(RenderError) as caught:
        fetcher.fetch("https://example.test/")

    assert "no browser" in str(caught.value)


def test_fetcher_returns_the_rendered_html():
    class FakePage:
        def goto(self, url, **kwargs):
            self.url = url

        def wait_for_timeout(self, ms):
            pass

        def content(self):
            return "<html><body><p>rendered</p></body></html>"

    class FakeBrowser:
        def new_page(self, **kwargs):
            return FakePage()

        def close(self):
            self.closed = True

    browser = FakeBrowser()
    fetcher = RenderedFetcher(launcher=lambda: browser)

    assert "rendered" in fetcher.fetch("https://example.test/")


def test_fetcher_closes_the_browser_even_when_navigation_fails():
    class FakePage:
        def goto(self, url, **kwargs):
            raise RuntimeError("navigation timeout")

    closed = []

    class FakeBrowser:
        def new_page(self, **kwargs):
            return FakePage()

        def close(self):
            closed.append(True)

    fetcher = RenderedFetcher(launcher=lambda: FakeBrowser())

    with pytest.raises(RenderError):
        fetcher.fetch("https://example.test/")

    assert closed == [True]
