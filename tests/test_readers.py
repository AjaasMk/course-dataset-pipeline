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


def test_read_html_skips_empty_sections(tmp_path):
    html_path = tmp_path / "empty_heading.html"
    html_path.write_text(
        "<html><body><h2>Empty Section</h2><h2>Real Section</h2><p>Real content.</p></body></html>",
        encoding="utf-8",
    )

    sections = read_html(html_path)

    assert len(sections) == 1
    assert sections[0].heading_title == "Real Section"
