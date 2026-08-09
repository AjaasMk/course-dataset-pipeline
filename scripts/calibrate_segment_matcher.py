import sys
from pathlib import Path

from src.extract.chunker import detect_pdf_sections
from src.extract.readers import read_html, read_pdf
from src.extract.segment_match import classify_heading

sys.stdout.reconfigure(encoding="utf-8")

REAL_SOURCES = [
    ("pdf", "data/raw/AICTE/revised_model_curriculum_for_ug_degree_course_in_mechanical_engineering.pdf"),
    ("html", "data/raw/NIRF/nirf_2025_engineering_ranking.html"),
    ("html", "data/raw/NIRF/nirf_2025_medical_ranking.html"),
    ("html", "data/raw/NTA/joint_entrance_examination.html"),
    ("html", "data/raw/NTA/national_eligibility_cum_entrance_test.html"),
]

# Genuinely ambiguous headings excluded from the content/noise floor-ceiling
AMBIGUOUS_HEADINGS = {"INTRODUCTION", "Introduction"}

# Hand-labelled from inspection: is this real heading actually a content
# section (should classify), or noise (front matter / nav chrome / a
# heading-detector false positive on a person's name) that must land in
# unclassified? This is the ground truth the threshold is calibrated against.
NOISE_HEADINGS = {
    "MESSAGE", "PREFACE", "PREAMBLE", "'40-45 DD/D'", "40-45 DD/D",
    "PROF.  MANOJ HARBOLA IIT KANPUR", "PATRA IIT KANPUR ENGINEERING GRAPHICS",
    "KRISHNAN IITM", "BASU IIT KHARAGPUR", "IQBAL IIT MADRAS",
    "ISBN: 978-93-91505-332", "(ISBN: 978-93-91505-219)", "ISBN 978-93-87034-53-",
    "ISBN: 978-93-91505-13-4", "ISBN: 978-93-91505-059",
    "1 ENGINEERING MECHANICS PROF.  MANOJ HARBOLA IIT KANPUR",
    "2 QUANTUM MECHANICS I PROF.  P.  RAMADEVI IIT BOMBAY",
    "2 MIT OCW:",
    "/Department of Higher Education", "LATEST NEWS", "Public Notices",
    "News & Events", "Candidate Activity", "Helpdesk", "Additional Links",
    "Important Links", "/", "IISER PUNE",
}


def main() -> int:
    rows = []
    for kind, path in REAL_SOURCES:
        p = Path(path)
        if kind == "pdf":
            sections = detect_pdf_sections(read_pdf(p))
        else:
            sections = read_html(p)
        for section in sections:
            heading = section.heading_title
            if not heading:
                continue
            segment, score = classify_heading(heading)
            is_noise = heading in NOISE_HEADINGS
            if heading not in AMBIGUOUS_HEADINGS:
                rows.append((heading, segment, score, is_noise))

    rows.sort(key=lambda r: -r[2])
    print(f"{'score':>6}  {'noise?':>6}  {'-> segment':32} heading")
    for heading, segment, score, is_noise in rows:
        seg_label = segment if segment == "unclassified" else segment.value
        print(f"{score:6.2f}  {str(is_noise):>6}  {seg_label:32} {heading[:60]!r}")

    print()
    content_scores = sorted((r[2] for r in rows if not r[3]), reverse=True)
    noise_scores = sorted((r[2] for r in rows if r[3]), reverse=True)
    print(f"content headings ({len(content_scores)}): scores range {min(content_scores):.2f}-{max(content_scores):.2f}")
    print(f"noise headings   ({len(noise_scores)}): scores range {min(noise_scores):.2f}-{max(noise_scores):.2f}")

    # Highest-scoring noise heading and lowest-scoring content heading bound
    # the safe threshold window, if one exists.
    print(f"\nhighest noise score:   {max(noise_scores):.2f}")
    print(f"lowest content score:  {min(content_scores):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
