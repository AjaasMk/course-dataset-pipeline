from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

from src.extract.models import PageText, Section

_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_MIN_REPEATED_PAGE_COUNT = 3


def read_pdf(path: Path) -> list[PageText]:
    reader = PdfReader(path)
    raw_pages = [page.extract_text() for page in reader.pages]
    cleaned_pages = _strip_repeated_lines(raw_pages)
    return [PageText(page_number=i + 1, text=text) for i, text in enumerate(cleaned_pages)]


def _strip_repeated_lines(pages: list[str]) -> list[str]:
    page_lines = [[line.strip() for line in page.split("\n")] for page in pages]

    line_counts: Counter = Counter()
    for lines in page_lines:
        for line in set(lines):
            if line:
                line_counts[line] += 1

    repeated = {line for line, count in line_counts.items() if count >= _MIN_REPEATED_PAGE_COUNT}

    return ["\n".join(line for line in lines if line not in repeated) for lines in page_lines]


def read_html(path: Path) -> list[Section]:
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    elements = soup.find_all(list(_HEADING_TAGS.keys()) + ["p", "li"])

    # Real pages (Careers360, Wikipedia) put navigation/share-widget headings
    # (e.g. "Popular Searches", "Share this via") before the real <h1> title —
    # verified against the actual downloaded Mechanical Engineering page.
    # Discard everything before the first <h1>. If there's no <h1> at all,
    # keep everything rather than discarding the whole document.
    has_h1 = any(el.name == "h1" for el in elements)
    seen_h1 = not has_h1

    sections: list[Section] = []
    current_heading = None
    current_paragraphs: list[str] = []

    def flush():
        if current_paragraphs:
            sections.append(Section(heading_title=current_heading, paragraphs=list(current_paragraphs)))

    for el in elements:
        if el.name == "h1":
            seen_h1 = True
        if not seen_h1:
            continue

        if el.name in _HEADING_TAGS:
            flush()
            current_paragraphs = []
            current_heading = el.get_text(strip=True)
        else:
            text = el.get_text(strip=True)
            if text:
                current_paragraphs.append(text)

    flush()
    return sections
