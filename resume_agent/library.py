"""A personal library of saved, named resumes (the user's "account").

Each saved resume is a folder under the library root (default ``~/.resume-agent/
resumes``) holding its LaTeX source, compiled PDF, and a small ``meta.json`` with
the user-chosen display name and timestamps. Names are user-facing and editable;
the on-disk folder is a slug derived from the name.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "resume"


def library_root() -> Path:
    home = Path(os.environ.get("RESUME_AGENT_HOME", "~/.resume-agent")).expanduser()
    return (home / "resumes").resolve()


@dataclass
class Resume:
    slug: str
    name: str
    dir: Path
    created: float
    updated: float

    @property
    def pdf(self) -> Path | None:
        pdfs = list(self.dir.rglob("*.pdf"))
        return max(pdfs, key=lambda p: p.stat().st_mtime) if pdfs else None

    def touch(self) -> None:
        self.updated = time.time()
        _write_meta(self)


def _meta_path(d: Path) -> Path:
    return d / "meta.json"


def _write_meta(r: Resume) -> None:
    _meta_path(r.dir).write_text(
        json.dumps({"name": r.name, "created": r.created, "updated": r.updated}, indent=2),
        encoding="utf-8",
    )


def _load(d: Path) -> Resume | None:
    if not d.is_dir():
        return None
    meta = _meta_path(d)
    if meta.exists():
        data = json.loads(meta.read_text(encoding="utf-8"))
        return Resume(
            slug=d.name,
            name=data.get("name", d.name),
            dir=d,
            created=data.get("created", d.stat().st_ctime),
            updated=data.get("updated", d.stat().st_mtime),
        )
    # Folder without meta (e.g. created by hand) — adopt it.
    return Resume(slug=d.name, name=d.name, dir=d, created=d.stat().st_ctime, updated=d.stat().st_mtime)


class ResumeLibrary:
    def __init__(self, root: Path | None = None):
        self.root = root or library_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[Resume]:
        items = [r for d in self.root.iterdir() if (r := _load(d))]
        return sorted(items, key=lambda r: r.updated, reverse=True)

    def get(self, name_or_slug: str) -> Resume | None:
        target = _slugify(name_or_slug)
        direct = self.root / target
        if direct.is_dir():
            return _load(direct)
        for r in self.list():
            if r.name.lower() == name_or_slug.strip().lower() or r.slug == target:
                return r
        return None

    def create(self, name: str) -> Resume:
        existing = self.get(name)
        if existing:
            return existing
        slug = _slugify(name)
        d = self.root / slug
        i = 2
        while d.exists():
            d = self.root / f"{slug}-{i}"
            i += 1
        d.mkdir(parents=True)
        now = time.time()
        r = Resume(slug=d.name, name=name.strip(), dir=d, created=now, updated=now)
        _write_meta(r)
        return r

    def get_or_create(self, name: str) -> Resume:
        return self.get(name) or self.create(name)

    def rename(self, old: str, new: str) -> Resume:
        r = self.get(old)
        if r is None:
            raise KeyError(f"No saved resume named '{old}'.")
        r.name = new.strip()
        r.updated = time.time()
        _write_meta(r)
        return r

    def delete(self, name: str) -> bool:
        import shutil

        r = self.get(name)
        if r is None:
            return False
        shutil.rmtree(r.dir)
        return True
