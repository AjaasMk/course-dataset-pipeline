from typing import Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel

SEATMATRIX_URL = "https://josaa.admissions.nic.in/applicant/seatmatrix/seatmatrixinfo.aspx"

_BRANCH_SELECT_ID = "ctl00_ContentPlaceHolder1_ddlBranch"
# A real data row is 18 cells with "Gender-Neutral" at index 3 -- confirmed
# live 2026-08-09. Other row shapes on this page (the header row, the
# 1-2 cell rowspan-continuation rows, the "Female-only" breakdown sub-row)
# are all a different cell count or a different index-3 value, so this
# single check cleanly separates real data rows from everything else
# without needing to track row position/state across the table.
_DATA_ROW_CELL_COUNT = 18
_SEAT_POOL_INDEX = 3
_SEAT_POOL_VALUE = "Gender-Neutral"


class SeatMatrixRow(BaseModel):
    """One institute x programme row from JoSAA's real seat matrix
    (State/All India Seats, Gender-Neutral pool only -- the Female-only
    sub-breakdown each real row also carries is not parsed here)."""

    institute_name: str
    programme_name: str
    open_seats: int
    open_pwd_seats: int
    gen_ews_seats: int
    gen_ews_pwd_seats: int
    sc_seats: int
    sc_pwd_seats: int
    st_seats: int
    st_pwd_seats: int
    obc_ncl_seats: int
    obc_ncl_pwd_seats: int
    total_seats: int
    seat_capacity: int
    female_supernumerary: int


def _int_or_zero(text: str) -> int:
    stripped = text.strip()
    return int(stripped) if stripped.isdigit() else 0


def parse_seat_matrix_table(html: str) -> list[SeatMatrixRow]:
    """Pure parsing function -- no network access. Given the real table's
    outerHTML (captured via Playwright, see fetch_seat_matrix below),
    returns one SeatMatrixRow per real institute x programme entry.

    The rowspan="2" "Program-Total" cell (index 15) concatenates its two
    stacked values with no separator ("822" for capacity=82 +
    supernumerary=2) -- confirmed live, this is real page markup, not a
    parsing bug. The clean values are the row's own last two cells
    (indices -2, -1), used instead of that cell.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[SeatMatrixRow] = []

    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) != _DATA_ROW_CELL_COUNT:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        if texts[_SEAT_POOL_INDEX] != _SEAT_POOL_VALUE:
            continue

        rows.append(
            SeatMatrixRow(
                institute_name=texts[0],
                programme_name=texts[1],
                open_seats=_int_or_zero(texts[4]),
                open_pwd_seats=_int_or_zero(texts[5]),
                gen_ews_seats=_int_or_zero(texts[6]),
                gen_ews_pwd_seats=_int_or_zero(texts[7]),
                sc_seats=_int_or_zero(texts[8]),
                sc_pwd_seats=_int_or_zero(texts[9]),
                st_seats=_int_or_zero(texts[10]),
                st_pwd_seats=_int_or_zero(texts[11]),
                obc_ncl_seats=_int_or_zero(texts[12]),
                obc_ncl_pwd_seats=_int_or_zero(texts[13]),
                total_seats=_int_or_zero(texts[14]),
                seat_capacity=_int_or_zero(texts[-2]),
                female_supernumerary=_int_or_zero(texts[-1]),
            )
        )
    return rows


def fetch_seat_matrix(branch_label: str, launcher: Optional[object] = None) -> str:
    """Playwright-driven fetch -- not unit-tested (see
    tests/test_josaa_seatmatrix.py for the pure parser tests; this function
    is live-verified instead, per this project's convention for anything
    requiring a real browser).

    Leaves Institute Type/Institute at their default "ALL" and selects only
    the branch -- confirmed live to be the efficient query shape: one query
    returns every JoSAA-participating institute offering that branch,
    rather than one query per institute.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page.goto(SEATMATRIX_URL, timeout=60_000, wait_until="domcontentloaded")
            page.wait_for_timeout(2_000)
            # force=True: the real <select> is hidden behind the "Chosen" JS
            # dropdown-styling library, so Playwright's default
            # visibility check fails even though the element is real and
            # setting it does fire the page's own onchange->postback logic.
            page.select_option(f"#{_BRANCH_SELECT_ID}", label=branch_label, force=True)
            page.wait_for_timeout(5_000)
            submit = page.query_selector("input[value='Submit'], button:has-text('Submit')")
            if submit is None:
                raise RuntimeError("JoSAA seat matrix page: Submit control not found")
            submit.click()
            page.wait_for_timeout(4_000)

            tables = page.query_selector_all("table")
            if not tables:
                return ""
            return tables[0].evaluate("el => el.outerHTML")
        finally:
            browser.close()
