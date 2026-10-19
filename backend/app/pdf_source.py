from pathlib import Path

from app.block_merge import merge_small_blocks
from app.pdf_handlers import DEFAULT_HANDLER, get_handler
from app.schemas import SourceIndex

SOURCE_INDEX_VERSION = 4


def parse_pdf_blocks(pdf_path: Path, document_sha256: str, pdf_handler: str = DEFAULT_HANDLER) -> SourceIndex:
    return SourceIndex(
        document_sha256=document_sha256,
        blocks=merge_small_blocks(get_handler(pdf_handler).parse(pdf_path)),
        index_version=SOURCE_INDEX_VERSION,
        pdf_handler=pdf_handler,
    )
