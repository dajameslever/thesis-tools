"""Local JSON-backed index of files the Library Indexer has processed.

Deliberately a plain JSON file rather than a database: it's small enough
for a personal thesis library, human-readable, diffable in git if the user
chooses to commit it, and needs zero extra dependencies.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..sources.base import Paper

INDEX_VERSION = 1


def hash_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of the file's bytes, used to detect unchanged/duplicate files."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class LibraryEntry:
    file_path: str
    file_hash: str
    file_type: str
    size_bytes: int
    indexed_at: str
    confidence: str  # "verified-doi" | "verified-title-match" | "unresolved"
    doi: Optional[str]
    paper: Paper
    # Lightweight {"doi", "title", "year"} records for papers this entry cites
    # (fetched at index time, only when --fetch-references was used).
    references: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "LibraryEntry":
        data = dict(data)
        paper = Paper(**data.pop("paper"))
        return LibraryEntry(paper=paper, **data)


class LibraryIndex:
    def __init__(self, entries: Optional[List[LibraryEntry]] = None):
        self.entries: List[LibraryEntry] = list(entries) if entries else []

    def by_hash(self) -> Dict[str, LibraryEntry]:
        return {e.file_hash: e for e in self.entries}

    def upsert(self, entry: LibraryEntry) -> None:
        """Replace an entry that matches by hash or by path, else append."""
        for i, existing in enumerate(self.entries):
            if existing.file_hash == entry.file_hash or existing.file_path == entry.file_path:
                self.entries[i] = entry
                return
        self.entries.append(entry)

    def prune_missing(self) -> int:
        """Drop entries whose source file no longer exists. Returns count removed."""
        before = len(self.entries)
        self.entries = [e for e in self.entries if Path(e.file_path).exists()]
        return before - len(self.entries)

    def duplicates_by_doi(self) -> Dict[str, List[LibraryEntry]]:
        """Group entries that share a DOI — usually the same paper downloaded twice."""
        groups: Dict[str, List[LibraryEntry]] = {}
        for entry in self.entries:
            doi = entry.doi or entry.paper.doi
            if doi:
                groups.setdefault(doi.strip().lower(), []).append(entry)
        return {doi: group for doi, group in groups.items() if len(group) > 1}

    @classmethod
    def load(cls, path: Path) -> "LibraryIndex":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [LibraryEntry.from_dict(e) for e in data.get("entries", [])]
        return cls(entries)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": INDEX_VERSION, "entries": [e.to_dict() for e in self.entries]}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
