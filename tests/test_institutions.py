from src.institutions.nirf_institutions import extract_institutions

RANKING_HTML = """
<html><body>
<table>
  <tr><th>Institute ID</th><th>Name</th><th>City</th><th>State</th><th>Score</th><th>Rank</th></tr>
  <tr>
    <td>IR-E-U-0456</td><td>Indian Institute of Technology Madras</td>
    <td>TLR (100)</td><td>RPC (100)</td><td>GO (100)</td><td>OI (100)</td><td>PERCEPTION (100)</td>
    <td>95.70</td><td>90.74</td><td>82.29</td><td>63.25</td><td>100.00</td>
    <td>Chennai</td><td>Tamil Nadu</td><td>88.72</td><td>1</td>
  </tr>
  <tr>
    <td>IR-E-I-1074</td><td>Indian Institute of Technology Delhi</td>
    <td>TLR (100)</td><td>RPC (100)</td><td>GO (100)</td><td>OI (100)</td><td>PERCEPTION (100)</td>
    <td>85.89</td><td>93.47</td><td>81.67</td><td>62.01</td><td>93.97</td>
    <td>New Delhi</td><td>Delhi</td><td>85.74</td><td>2</td>
  </tr>
  <tr><td>TLR (100)</td><td>RPC (100)</td></tr>
</table>
</body></html>
"""


def test_extracts_one_institution_per_ranked_row():
    assert len(extract_institutions(RANKING_HTML, year="2025", category="Engineering")) == 2


def test_reads_identity_from_the_leading_columns():
    first = extract_institutions(RANKING_HTML, year="2025", category="Engineering")[0]
    assert first.nirf_id == "IR-E-U-0456"
    assert first.canonical_name == "Indian Institute of Technology Madras"


def test_reads_location_and_rank_from_the_trailing_columns():
    # The score-breakdown cells sit between name and city and vary in number, so
    # location and rank are read from the end of the row rather than a fixed index.
    first = extract_institutions(RANKING_HTML, year="2025", category="Engineering")[0]
    assert first.city == "Chennai"
    assert first.state == "Tamil Nadu"
    assert first.nirf_rank == 1


def test_ignores_rows_that_are_score_breakdown_fragments():
    names = [i.canonical_name for i in extract_institutions(RANKING_HTML, "2025", "Engineering")]
    assert "RPC (100)" not in names


def test_records_provenance_on_every_institution():
    first = extract_institutions(RANKING_HTML, year="2025", category="Engineering")[0]
    assert first.discovered_from_source_id == "NIRF"
    assert first.ranking_year == "2025"
    assert first.ranking_category == "Engineering"


def test_ui_affordance_text_is_stripped_from_the_name():
    # Verbatim from the live 2025 University table: the name cell embeds a
    # details/close widget whose text get_text() pulls in, and the trailing junk
    # runs past "More Details" into "Close | | TLR...", so cutting has to start at
    # the marker rather than anchor to the end of the string.
    html = RANKING_HTML.replace(
        "<td>Indian Institute of Technology Madras</td>",
        "<td>Jamia Millia Islamia More Details Close | | TLR (100)</td>",
    )
    first = extract_institutions(html, "2025", "University")[0]
    assert first.canonical_name == "Jamia Millia Islamia"


def test_a_bare_close_affordance_is_also_stripped():
    # Not every row carries the full "More Details Close" pair; the Engineering
    # table yields "Indian Institute of Technology Madras Close".
    html = RANKING_HTML.replace(
        "<td>Indian Institute of Technology Madras</td>",
        "<td>Indian Institute of Technology Madras Close</td>",
    )
    first = extract_institutions(html, "2025", "Engineering")[0]
    assert first.canonical_name == "Indian Institute of Technology Madras"


def test_institution_id_is_stable_for_the_same_nirf_id():
    a = extract_institutions(RANKING_HTML, "2025", "Engineering")[0]
    b = extract_institutions(RANKING_HTML, "2025", "Engineering")[0]
    assert a.institution_id == b.institution_id


def test_one_institution_ranked_in_several_categories_gets_one_id():
    # NIRF ids are category-scoped, not institution-scoped: Jamia Millia Islamia
    # is IR-A-U-0108 under Architecture, IR-E-U-0108 under Engineering and
    # IR-O-U-0108 under University. The numeric suffix is the stable institution
    # key; keying on the whole id would triple-count it.
    architecture = extract_institutions(
        RANKING_HTML.replace("IR-E-U-0456", "IR-A-U-0108"), "2025", "Architecture"
    )[0]
    engineering = extract_institutions(
        RANKING_HTML.replace("IR-E-U-0456", "IR-E-U-0108"), "2025", "Engineering"
    )[0]

    assert architecture.institution_id == engineering.institution_id
    assert architecture.nirf_id != engineering.nirf_id


def test_different_institutions_keep_different_ids():
    a = extract_institutions(RANKING_HTML, "2025", "Engineering")[0]
    b = extract_institutions(RANKING_HTML, "2025", "Engineering")[1]
    assert a.institution_id != b.institution_id


SCORELESS_HTML = """
<html><body>
<table>
  <tr><th>Institute ID</th><th>Name</th><th>City</th><th>State</th><th>Rank</th></tr>
  <tr>
    <td>IR-I-U-0456</td><td>Indian Institute of Technology Madras</td>
    <td>Chennai</td><td>Tamil Nadu</td><td>1</td>
  </tr>
</table>
</body></html>
"""


def test_a_ranking_table_without_a_score_column_is_still_extracted():
    # The live Innovation table has five columns and no Score. Requiring six
    # silently dropped the whole category.
    found = extract_institutions(SCORELESS_HTML, "2025", "Innovation")
    assert len(found) == 1


def test_scoreless_rows_read_location_and_rank_correctly():
    only = extract_institutions(SCORELESS_HTML, "2025", "Innovation")[0]
    assert only.city == "Chennai"
    assert only.state == "Tamil Nadu"
    assert only.nirf_rank == 1
    assert only.nirf_score is None


def test_the_number_alone_does_not_identify_an_institution():
    # Live collision: IR-M-S-6 is IIM Sambalpur and IR-C-N-6 is Queen Mary's
    # College. The trailing number is scoped by the institution-type letter (3rd
    # position), so keying on the number alone merges two unrelated institutions.
    iim = extract_institutions(RANKING_HTML.replace("IR-E-U-0456", "IR-M-S-6"), "2025", "Management")[0]
    college = extract_institutions(RANKING_HTML.replace("IR-E-U-0456", "IR-C-N-6"), "2025", "College")[0]

    assert iim.institution_id != college.institution_id
