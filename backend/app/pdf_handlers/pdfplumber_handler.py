"""pdfplumber (pdfminer) text lines fed through the same paragraph and heading rules as PyMuPDF."""

import statistics
from pathlib import Path

from app.pdf_block_builder import Line, build_blocks_from_lines
from app.schemas import SourceBlock


def parse(pdf_path: Path) -> list[SourceBlock]:
    import pdfplumber

    all_lines: dict[int, list[Line]] = {}
    heights: dict[int, float] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            heights[page_number] = float(page.height)
            lines: list[Line] = []
            # The default absolute 3pt word gap glues words together in tightly set protocol text.
            for row in page.extract_text_lines(strip=True, return_chars=True, x_tolerance_ratio=0.15):
                text = row["text"].strip()
                if not text:
                    continue
                sizes = [float(char["size"]) for char in row.get("chars", []) if char.get("size")]
                bbox = (float(row["x0"]), float(row["top"]), float(row["x1"]), float(row["bottom"]))
                lines.append(
                    Line(
                        page=page_number,
                        text=text,
                        bbox=bbox,
                        size=statistics.median(sizes) if sizes else 10.0,
                        y0=bbox[1],
                        y1=bbox[3],
                    )
                )
            lines.sort(key=lambda line: (line.y0, line.bbox[0]))
            all_lines[page_number] = lines
    return build_blocks_from_lines(all_lines, heights)
