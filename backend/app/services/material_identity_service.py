"""Resolve backwards-compatible material identifiers without leaking ownership."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.material import Material


def resolve_owned_material(
    db: Session, material_identifier: str | int, user_id: int,
) -> Material | None:
    """Resolve a legacy numeric ID or immutable UUID-like public identity.

    Numeric routes keep their historic semantics: a numeric value resolves by
    row ID first.  A UUID (or any non-numeric public id) resolves only against
    ``public_id``.  In both cases ownership is part of the same SQL query.
    """
    value = str(material_identifier)
    if value.isdecimal():
        numeric = db.query(Material).filter(
            Material.id == int(value), Material.user_id == user_id,
        ).first()
        if numeric is not None:
            return numeric
    return db.query(Material).filter(
        Material.public_id == value, Material.user_id == user_id,
    ).first()
