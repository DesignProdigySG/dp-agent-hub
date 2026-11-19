"""The Spatial view's brick layout. Anyone who can see the hub can see it; the admin edits it.

Saves are versioned: each one names the version it was edited from and is refused (409) if
the layout changed since, and every replaced layout is kept (the last 20) so it can be
restored.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func
from sqlmodel import select

from app.db import SceneLayout, SceneLayoutVersion, audit, session
from app.events.schema import utcnow
from app.security import require_admin, require_viewer

viewer = APIRouter(dependencies=[Depends(require_viewer)])
admin = APIRouter(dependencies=[Depends(require_admin)])

MAX_PIECES = 2000
KEEP_VERSIONS = 20
BrickColor = Literal["cream", "green", "yellow", "orange", "red", "blue", "sky", "purple",
                     "black", "grey", "slate", "steel", "white", "clay", "brown", "tan"]


class Piece(BaseModel):
    # a Kenney brick, or a Brick Lab build ("lab-server-rack")
    piece: str = Field(pattern=r"^((round|none)-hq-(brick|plate)-[a-z0-9-]+|lab-[a-z0-9-]+)$",
                       max_length=60)
    color: BrickColor
    x: float = Field(ge=-60, le=60)  # studs
    y: int = Field(ge=0, le=60)  # plate layers
    z: float = Field(ge=-60, le=60)
    rot: Literal[0, 1, 2, 3] = 0  # quarter turns


class Layout(BaseModel):
    pieces: list[Piece] | None = Field(None, max_length=MAX_PIECES)  # None = the default decor


class LayoutOut(Layout):
    version: int = 0
    updated_at: datetime | None = None


class LayoutIn(Layout):
    # The version this layout was edited from. A save from an older copy (another tab, a
    # page that failed to load the layout, a stale browser) is refused instead of
    # overwriting newer work.
    base_version: int


class Restore(BaseModel):
    base_version: int


def _current(s) -> tuple[SceneLayout | None, int]:
    row = s.get(SceneLayout, "default")
    if row:
        return row, row.version
    last = s.exec(select(func.max(SceneLayoutVersion.version))).one()
    return None, int(last or 0)


def _out(row: SceneLayout | None, version: int) -> LayoutOut:
    if row is None or not row.pieces:
        return LayoutOut(pieces=None, version=version, updated_at=row.updated_at if row else None)
    return LayoutOut(pieces=row.pieces, version=version, updated_at=row.updated_at)


def _replace(s, row: SceneLayout | None, version: int, pieces: list[dict]) -> SceneLayout:
    """Archive the current layout, then make `pieces` ([] = default decor) current."""
    if row is not None:
        s.add(SceneLayoutVersion(version=version, pieces=list(row.pieces),
                                 saved_at=row.updated_at))
    row = row or SceneLayout()
    row.pieces, row.version, row.updated_at = pieces, version + 1, utcnow()
    s.add(row)
    s.flush()
    keep = [v.id for v in s.exec(select(SceneLayoutVersion)
                                 .order_by(SceneLayoutVersion.version.desc())
                                 .limit(KEEP_VERSIONS))]
    s.exec(delete(SceneLayoutVersion).where(SceneLayoutVersion.id.not_in(keep or [0])))
    return row


def _conflict(version: int) -> HTTPException:
    return HTTPException(409, {"message": "The layout was saved somewhere else since you "
                               "loaded it. Load the latest before saving; your edits are kept "
                               "as a draft.", "version": version})


@viewer.get("/scene")
def get_scene() -> LayoutOut:
    with session() as s:
        return _out(*_current(s))


@admin.put("/scene")
async def put_scene(body: LayoutIn, request: Request) -> LayoutOut:
    with session() as s:
        row, version = _current(s)
        if body.base_version != version:
            raise _conflict(version)
        pieces = [p.model_dump() for p in body.pieces] if body.pieces is not None else []
        row = _replace(s, row, version, pieces)
        s.commit()
        out = _out(row, row.version)
    audit("scene_updated", f"version {out.version}: " + (
        "reset to default" if not pieces else f"{len(pieces)} pieces"))
    return out


@viewer.get("/scene/history")
def scene_history() -> list[dict]:
    with session() as s:
        return [{"id": v.id, "version": v.version, "pieces": len(v.pieces),
                 "saved_at": v.saved_at, "replaced_at": v.replaced_at}
                for v in s.exec(select(SceneLayoutVersion)
                                .order_by(SceneLayoutVersion.version.desc()))]


@admin.post("/scene/history/{version_id}/restore")
async def restore_scene(version_id: int, body: Restore) -> LayoutOut:
    with session() as s:
        old = s.get(SceneLayoutVersion, version_id)
        if old is None:
            raise HTTPException(404, "version not found")
        row, version = _current(s)
        if body.base_version != version:
            raise _conflict(version)
        restored = old.version
        row = _replace(s, row, version, list(old.pieces))
        s.commit()
        out = _out(row, row.version)
    audit("scene_updated", f"version {out.version}: restored version {restored}")
    return out
