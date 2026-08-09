from src.retrieve.probe import ProbeVerdict, classify

SPA_SHELL = """
<html><head><title>Loading</title></head>
<body><div id="root"></div><script src="/static/app.js"></script></body></html>
"""

SERVER_RENDERED = (
    "<html><body><h1>Approved Institutions</h1>"
    + "".join(f'<p>Institution number {n} is approved for the 2026-27 session.</p>' for n in range(40))
    + "".join(f'<a href="/inst/{n}">Institution {n}</a>' for n in range(30))
    + "</body></html>"
)


def test_empty_spa_shell_is_js_required():
    result = classify(200, SPA_SHELL)
    assert result.verdict is ProbeVerdict.JS_REQUIRED
    assert "root" in " ".join(result.spa_markers)


def test_content_rich_page_is_server_rendered():
    result = classify(200, SERVER_RENDERED)
    assert result.verdict is ProbeVerdict.SERVER_RENDERED
    assert result.link_count == 30


def test_forbidden_status_is_blocked():
    assert classify(403, "").verdict is ProbeVerdict.BLOCKED


def test_rate_limited_status_is_blocked():
    assert classify(429, "").verdict is ProbeVerdict.BLOCKED


def test_server_error_is_error():
    assert classify(500, "").verdict is ProbeVerdict.ERROR


def test_thin_page_without_spa_markers_is_still_js_required():
    assert classify(200, "<html><body><p>hi</p></body></html>").verdict is ProbeVerdict.JS_REQUIRED


def test_link_dense_index_page_is_usable_despite_little_visible_text():
    # NIRF's /Rankings/<year>/Ranking.html is a real nav page whose anchors carry
    # no text, so a text-length heuristic alone wrongly rejects it. Every source
    # genuinely blocked by JS in the live probe returned 0-1 links.
    html = (
        "<html><body>"
        + "".join(f'<a href="/Rankings/2025/Cat{n}Ranking.html"></a>' for n in range(17))
        + "</body></html>"
    )
    assert classify(200, html).verdict is ProbeVerdict.SERVER_RENDERED
