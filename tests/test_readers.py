from unittest.mock import Mock, patch

from src.extract.readers import read_html, read_pdf


def _mock_pdf_reader(page_texts):
    pages = []
    for text in page_texts:
        page = Mock()
        page.extract_text = Mock(return_value=text)
        pages.append(page)
    reader = Mock()
    reader.pages = pages
    return reader


@patch("src.extract.readers.PdfReader")
def test_read_pdf_returns_one_pagetext_per_page(mock_reader_cls):
    mock_reader_cls.return_value = _mock_pdf_reader(["Page one text", "Page two text"])

    pages = read_pdf("fake.pdf")

    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert pages[1].page_number == 2


@patch("src.extract.readers.PdfReader")
def test_read_pdf_strips_lines_repeated_on_three_or_more_pages(mock_reader_cls):
    header = "AICTE revised Model Curriculum for UG Degree Course in Mechanical Engineering"
    mock_reader_cls.return_value = _mock_pdf_reader([
        f"{header}\n1\n\nPREAMBLE\nSome real content here.",
        f"{header}\n2\n\nMore real content on page two.",
        f"{header}\n3\n\nEven more content on page three.",
    ])

    pages = read_pdf("fake.pdf")

    for page in pages:
        assert header not in page.text


@patch("src.extract.readers.PdfReader")
def test_read_pdf_keeps_lines_not_repeated_across_pages(mock_reader_cls):
    mock_reader_cls.return_value = _mock_pdf_reader([
        "PREAMBLE\nUnique content on page one.",
        "SYLLABUS\nUnique content on page two.",
        "REFERENCES\nUnique content on page three.",
    ])

    pages = read_pdf("fake.pdf")

    assert "PREAMBLE" in pages[0].text
    assert "Unique content on page one." in pages[0].text
    assert "SYLLABUS" in pages[1].text


def test_read_html_extracts_heading_hierarchy_and_paragraphs(tmp_path):
    html_path = tmp_path / "sample.html"
    html_path.write_text(
        """
        <html><body>
        <h1>Mechanical Engineering</h1>
        <p>What mechanical engineering is about.</p>
        <h2>Eligibility Criteria</h2>
        <p>Eligibility paragraph one.</p>
        <p>Eligibility paragraph two.</p>
        <h2>Course Fees</h2>
        <p>Fees paragraph.</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert sections[0].heading_title == "Mechanical Engineering"
    assert sections[0].page_number is None
    assert sections[0].paragraphs == ["What mechanical engineering is about."]

    assert sections[1].heading_title == "Eligibility Criteria"
    assert sections[1].paragraphs == ["Eligibility paragraph one.", "Eligibility paragraph two."]

    assert sections[2].heading_title == "Course Fees"
    assert sections[2].paragraphs == ["Fees paragraph."]


def test_read_html_keeps_everything_when_no_h1_tag_exists(tmp_path):
    html_path = tmp_path / "no_h1.html"
    html_path.write_text(
        "<html><body><p>Lead-in text, no heading at all.</p><h2>Only Section</h2><p>Content.</p></body></html>",
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert sections[0].heading_title is None
    assert sections[0].paragraphs == ["Lead-in text, no heading at all."]
    assert sections[1].heading_title == "Only Section"


def test_read_html_discards_navigation_content_before_first_h1(tmp_path):
    html_path = tmp_path / "with_nav_noise.html"
    html_path.write_text(
        """
        <html><body>
        <h3>Popular Searches</h3>
        <li>Some unrelated search link</li>
        <li>Another unrelated search link</li>
        <h4>Share this via</h4>
        <li>Facebook</li><li>Twitter</li><li>WhatsApp</li>
        <h1>Mechanical Engineering Course Details</h1>
        <p>Real course content starts here.</p>
        <h2>Eligibility Criteria</h2>
        <p>Real eligibility content.</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert sections[0].heading_title == "Mechanical Engineering Course Details"
    assert sections[0].paragraphs == ["Real course content starts here."]
    assert not any("Share this via" in (s.heading_title or "") for s in sections)
    assert not any("Popular Searches" in (s.heading_title or "") for s in sections)


def test_read_html_strips_wikipedia_language_switcher(tmp_path):
    # Real noise found on the actual Wikipedia Marketing page: a language-switcher
    # widget (id="p-lang-btn", MediaWiki's standard "portlet: language" convention)
    # sits right after the <h1>, containing 200+ <li> language names with no real
    # article content.
    html_path = tmp_path / "wiki_with_lang_switcher.html"
    html_path.write_text(
        """
        <html><body>
        <h1>Marketing</h1>
        <div id="p-lang-btn"><ul><li>Afrikaans</li><li>Aragonés</li></ul></div>
        <div id="mw-panel-toc" class="mw-table-of-contents-container"><ul><li>Definition</li><li>Concept</li></ul></div>
        <p>Marketing is the act of acquiring customers.</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert sections[0].heading_title == "Marketing"
    assert sections[0].paragraphs == ["Marketing is the act of acquiring customers."]


def test_read_html_restricts_to_mediawiki_content_container_when_present(tmp_path):
    # MediaWiki (Wikipedia) pages wrap the real article body in
    # id="mw-content-text" / class="mw-parser-output", with zero nav/tools
    # chrome inside it -- and notably no <h1> inside it either (the page
    # title lives outside, in the page header). Verified against the real
    # Marketing Wikipedia page. When this container exists, restrict
    # extraction to it entirely and skip the h1-based filtering (there's no
    # h1 inside to filter around).
    html_path = tmp_path / "mediawiki_page.html"
    html_path.write_text(
        """
        <html><body>
        <div id="mw-head"><ul><li>Article</li><li>Talk</li></ul></div>
        <h1>Marketing</h1>
        <div id="mw-content-text">
          <div class="mw-parser-output">
            <table class="sidebar hlist"><tr><td><ul><li>Account-based marketing</li><li>Digital marketing</li></ul></td></tr></table>
            <p>Marketing is the act of acquiring customers.</p>
            <h2>Definition</h2>
            <p>Marketing is defined by the AMA.</p>
          </div>
        </div>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert sections[0].heading_title is None
    assert sections[0].paragraphs == ["Marketing is the act of acquiring customers."]
    assert sections[1].heading_title == "Definition"
    assert sections[1].paragraphs == ["Marketing is defined by the AMA."]
    assert not any("Article" in p or "Talk" in p for s in sections for p in s.paragraphs)
    assert not any("Account-based marketing" in p for s in sections for p in s.paragraphs)


def test_read_html_excludes_qna_forum_block_by_stable_id(tmp_path):
    # Real noise found on the actual Chemical Engineering Careers360 page:
    # the "Questions related to X" forum block lives in a container with a
    # stable, unique id="qna". Individual FAQ questions use the SAME
    # class="blockHeading" as this section's own heading, so a class-based
    # check can't distinguish them -- id-based decompose is what's safe here.
    html_path = tmp_path / "with_qna_noise.html"
    html_path.write_text(
        """
        <html><body>
        <h1>Chemical Engineering</h1>
        <p>Real course content.</p>
        <div id="qna">
          <h2 class="blockHeading">Questions related to Chemical Engineering</h2>
          <a><h3 class="cardSubHeading">Some forum question nobody asked</h3></a>
          <p>A forum answer with no course-fact value.</p>
        </div>
        <h2>Courses Similar to Chemical Engineering</h2>
        <p>Petrochemical Engineering, Polymer Engineering</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert not any("forum question" in p for s in sections for p in s.paragraphs)
    assert not any(s.heading_title == "Questions related to Chemical Engineering" for s in sections)
    # real content after the noise block is still captured, not cut off
    assert any(s.heading_title == "Courses Similar to Chemical Engineering" for s in sections)


def test_read_html_keeps_faq_questions_that_share_a_class_with_noise_headings(tmp_path):
    # Real bug caught live: individual FAQ questions use the exact same
    # class="blockHeading" as the forum/footer noise headings. A class-based
    # noise check wrongly excluded these. Must survive using the id/text-
    # anchored decompose approach instead.
    html_path = tmp_path / "with_faq.html"
    html_path.write_text(
        """
        <html><body>
        <h1>Chemical Engineering</h1>
        <p>Real course content.</p>
        <h2>Frequently Asked Questions (FAQs)</h2>
        <h3 class="blockHeading"><strong>Question:</strong> Can I do a diploma?</h3>
        <p>Yes, after Class 10.</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert any("Can I do a diploma?" in (s.heading_title or "") for s in sections)
    assert any("Yes, after Class 10." in s.paragraphs for s in sections)


def test_read_html_excludes_popular_colleges_directory_by_text_pattern(tmp_path):
    # Real noise found on the actual Chemical Engineering Careers360 page:
    # "Popular Chemical Engineering Colleges in India" is photo/rating/
    # brochure directory cards, sharing the same class as real content
    # headings -- needs a text-pattern match, not a class check.
    html_path = tmp_path / "with_college_cards.html"
    html_path.write_text(
        """
        <html><body>
        <h1>Chemical Engineering</h1>
        <p>Real course content.</p>
        <div>
          <h2>Popular Chemical Engineering Colleges in India</h2>
          <div><li>IIT Bombay</li><li>95 Reviews</li><li>Rated AAAAA</li></div>
        </div>
        <h2>Frequently Asked Questions (FAQs)</h2>
        <p>An FAQ answer worth keeping.</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert not any("95 Reviews" in p for s in sections for p in s.paragraphs)
    assert not any(s.heading_title == "Popular Chemical Engineering Colleges in India" for s in sections)
    # FAQs come right after the noise section and must still be captured
    assert any(s.heading_title == "Frequently Asked Questions (FAQs)" for s in sections)


def test_read_html_excludes_explore_colleges_footer_directory(tmp_path):
    html_path = tmp_path / "with_footer_directory.html"
    html_path.write_text(
        """
        <html><body>
        <h1>Chemical Engineering</h1>
        <p>Real course content.</p>
        <div>
          <h2>Explore Engineering colleges in other popular locations</h2>
          <li>Hyderabad</li><li>Bangalore</li><li>Pune</li>
        </div>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert not any("Hyderabad" in p for s in sections for p in s.paragraphs)
    assert not any(
        s.heading_title == "Explore Engineering colleges in other popular locations" for s in sections
    )


def test_read_html_excludes_site_footer_tag(tmp_path):
    html_path = tmp_path / "with_footer_tag.html"
    html_path.write_text(
        """
        <html><body>
        <h1>Chemical Engineering</h1>
        <p>Real course content.</p>
        <footer class="footer-section">
          <h5>Top Exams</h5><li>JEE Main</li>
          <h5>Resources</h5><li>NCERT</li>
        </footer>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert not any(s.heading_title in ("Top Exams", "Resources") for s in sections)
    assert not any("JEE Main" in p for s in sections for p in s.paragraphs)


def test_read_html_excludes_signin_modal_and_app_promo_and_sidebar(tmp_path):
    html_path = tmp_path / "with_ui_chrome.html"
    html_path.write_text(
        """
        <html><body>
        <h1>Chemical Engineering</h1>
        <p>Real course content.</p>
        <div id="commonSignin"><h3>Sign In/Sign Up</h3><p>noise</p></div>
        <section class="new-fat-footer-bg-container">
          <h4>Scan and download the app</h4><p>noise</p>
        </section>
        <div class="right-sidebar"><h3>Popular Degrees</h3><li>B.Tech</li></div>
        <h2>Eligibility Criteria</h2>
        <p>Real eligibility content.</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert not any(
        s.heading_title in ("Sign In/Sign Up", "Scan and download the app", "Popular Degrees")
        for s in sections
    )
    assert any(s.heading_title == "Eligibility Criteria" for s in sections)


def test_read_html_extracts_related_courses_wrapped_in_nested_h3_tags(tmp_path):
    # Real structure found on the actual Chemical Engineering Careers360 page:
    # each related course name is its own <h3><a>Name</a></h3>, not a <li>.
    html_path = tmp_path / "with_related_courses.html"
    html_path.write_text(
        """
        <html><body>
        <h1>Chemical Engineering</h1>
        <p>Real course content.</p>
        <h2>Courses Similar to Chemical Engineering</h2>
        <div class="course_name">
          <div class="block-inner"><h3 class="heading-h3"><a href="/x">Ceramic Engineering</a></h3></div>
          <div class="block-inner"><h3 class="heading-h3"><a href="/y">Petrochemical Engineering</a></h3></div>
          <div class="block-inner"><h3 class="heading-h3"><a href="/z">Polymer Engineering</a></h3></div>
        </div>
        <h2>Eligibility Criteria</h2>
        <p>Real eligibility content.</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    sections = read_html(html_path)

    related = next(s for s in sections if s.heading_title == "Courses Similar to Chemical Engineering")
    assert related.paragraphs == ["Ceramic Engineering", "Petrochemical Engineering", "Polymer Engineering"]
    # course names weren't ALSO picked up as their own stray top-level headings
    assert not any(s.heading_title == "Ceramic Engineering" for s in sections)
    assert not any(s.heading_title == "Polymer Engineering" for s in sections)
    # real content after this section is still captured
    assert any(s.heading_title == "Eligibility Criteria" for s in sections)


def test_read_html_skips_empty_sections(tmp_path):
    html_path = tmp_path / "empty_heading.html"
    html_path.write_text(
        "<html><body><h2>Empty Section</h2><h2>Real Section</h2><p>Real content.</p></body></html>",
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert len(sections) == 1
    assert sections[0].heading_title == "Real Section"
