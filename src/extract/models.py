from typing import Literal, Optional, Union

from pydantic import BaseModel

from src.retrieve.models import Segment


class PageText(BaseModel):
    page_number: int
    text: str


class Section(BaseModel):
    heading_title: Optional[str] = None
    page_number: Optional[int] = None  # PDF only, None for HTML
    paragraphs: list[str]


class Chunk(BaseModel):
    chunk_id: int
    text: str
    source_document: str
    source_url: str
    page_number: Optional[int] = None
    heading_title: Optional[str] = None
    token_count: int
    # Classified once per Section and propagated into every chunk that
    # section produces, so every fragment self-identifies its segment
    # without depending on chunk 0 or on overlap text carrying context
    # forward -- see docs/superpowers/specs for the NIRF header-loss finding
    # this replaces.
    segment_id: Union[Segment, Literal["unclassified"]] = "unclassified"
    segment_match_confidence: float = 0.0
    # The tier of the document this chunk came from. Optional because chunks
    # written before this field existed do not carry it, but retrieval treats a
    # missing tier as unusable for a canonical role rather than assuming the
    # best case -- an unknown provenance is not an authoritative one.
    source_tier: Optional[str] = None
