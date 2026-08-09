from src.retrieve.josaa_seatmatrix import SeatMatrixRow, parse_seat_matrix_table

# A trimmed, real DOM shape captured live 2026-08-09 from
# https://josaa.admissions.nic.in/applicant/seatmatrix/seatmatrixinfo.aspx
# (ALL institutes + "Computer Science and Engineering (4 Years, Bachelor of
# Technology)" branch, Submit clicked) -- two real institutes' worth of rows,
# including the header row and the "Female-only" sub-row real pages also
# contain, to prove the parser correctly skips both.
REAL_TABLE_HTML = """
<table>
<tr>
  <td>Institute Name</td><td>Program Name</td><td>State/All India Seats</td><td>Seat Pool</td>
  <td>OPEN</td><td>OPEN-PwD</td><td>GEN-EWS</td><td>GEN-EWS-PwD</td><td>SC</td><td>SC-PwD</td>
  <td>ST</td><td>ST-PwD</td><td>OBC-NCL</td><td>OBC-NCL-PwD</td>
  <td>Total (includes Female Supernumerary)</td>
  <td colspan="2">Program-Total<div>Seat Capacity</div><div>Female Supernumerary</div></td>
</tr>
<tr><td>Program-Total</td></tr>
<tr><td>Seat Capacity</td><td>Female Supernumerary</td></tr>
<tr>
  <td rowspan="2">Indian Institute  of Technology Bhubaneswar</td>
  <td rowspan="2">Computer Science and Engineering (4 Years, Bachelor of Technology)</td>
  <td rowspan="2">All India</td>
  <td>Gender-Neutral</td>
  <td>27</td><td>0</td><td>6</td><td>0</td><td>9</td><td>1</td><td>5</td><td>0</td><td>17</td><td>1</td>
  <td>66</td>
  <td rowspan="2">822</td><td>82</td><td>2</td>
</tr>
<tr><td>82</td><td>2</td></tr>
<tr>
  <td>Female-only (including Supernumerary)</td>
  <td>8</td><td>1</td><td>2</td><td>0</td><td>2</td><td>0</td><td>1</td><td>0</td><td>4</td><td>0</td>
  <td>18(including "2" Supernumerary)</td>
</tr>
<tr>
  <td rowspan="2">Indian Institute  of Technology Bombay</td>
  <td rowspan="2">Computer Science and Engineering (4 Years, Bachelor of Technology)</td>
  <td rowspan="2">All India</td>
  <td>Gender-Neutral</td>
  <td>61</td><td>3</td><td>15</td><td>1</td><td>23</td><td>1</td><td>12</td><td>0</td><td>41</td><td>2</td>
  <td>159</td>
  <td rowspan="2">17029</td><td>170</td><td>29</td>
</tr>
<tr><td>170</td><td>29</td></tr>
<tr>
  <td>Female-only (including Supernumerary)</td>
  <td>15</td><td>1</td><td>4</td><td>0</td><td>6</td><td>0</td><td>2</td><td>1</td><td>11</td><td>0</td>
  <td>40(including "29" Supernumerary)</td>
</tr>
</table>
"""


def test_parses_only_the_real_data_rows_not_headers_or_female_only_subrows():
    rows = parse_seat_matrix_table(REAL_TABLE_HTML)
    assert len(rows) == 2


def test_extracts_institute_and_programme_names_correctly():
    rows = parse_seat_matrix_table(REAL_TABLE_HTML)
    assert rows[0].institute_name == "Indian Institute  of Technology Bhubaneswar"
    assert rows[0].programme_name == "Computer Science and Engineering (4 Years, Bachelor of Technology)"
    assert rows[1].institute_name == "Indian Institute  of Technology Bombay"


def test_extracts_category_seat_counts_correctly():
    row = parse_seat_matrix_table(REAL_TABLE_HTML)[0]
    assert row.open_seats == 27
    assert row.open_pwd_seats == 0
    assert row.gen_ews_seats == 6
    assert row.sc_seats == 9
    assert row.st_seats == 5
    assert row.obc_ncl_seats == 17
    assert row.total_seats == 66


def test_extracts_clean_seat_capacity_and_female_supernumerary_not_the_garbled_rowspan_cell():
    # The rowspan="2" cell ("822", "17029") concatenates two stacked values
    # with no separator -- confirmed live, this is real page markup, not a
    # parsing artifact. The clean values are the row's own last two cells.
    row0, row1 = parse_seat_matrix_table(REAL_TABLE_HTML)
    assert row0.seat_capacity == 82
    assert row0.female_supernumerary == 2
    assert row1.seat_capacity == 170
    assert row1.female_supernumerary == 29


def test_returns_empty_list_for_a_table_with_no_data_rows():
    assert parse_seat_matrix_table("<table><tr><td>nothing here</td></tr></table>") == []


def test_seat_matrix_row_is_a_real_model_not_a_dict():
    row = parse_seat_matrix_table(REAL_TABLE_HTML)[0]
    assert isinstance(row, SeatMatrixRow)
