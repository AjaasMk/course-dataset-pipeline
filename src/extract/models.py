from typing import Optional

from pydantic import BaseModel


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
