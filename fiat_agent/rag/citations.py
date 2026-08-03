"""RAG citation model (phase E5, DEV_SPEC §6.5).

A `Citation` is the traceable provenance of one retrieved chunk: which
collection / doc / chunk it came from, plus a human-readable source label.
Keeping these explicit satisfies the acceptance criteria that sources are
retained and collection / doc_id / chunk_id stay traceable.
"""

from __future__ import annotations

from fiat_agent.schemas.common import FiatModel


class Citation(FiatModel):
    """Provenance of a single retrieved chunk."""

    collection: str = ""
    doc_id: str = ""
    chunk_id: str = ""
    source: str = ""  # human-readable label (title / uri / file name)
    snippet: str = ""  # quoted text of the chunk
    score: float | None = None  # retrieval relevance if provided
