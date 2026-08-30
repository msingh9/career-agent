"""Request dependency that resolves the active profile from the X-User-Id header."""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User


def get_current_user(
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> User:
    if x_user_id is None:
        raise HTTPException(
            status_code=400,
            detail="No profile selected. Pick or create a profile first.",
        )
    user = db.query(User).filter(User.id == x_user_id).one_or_none()
    if user is None:
        raise HTTPException(
            status_code=400,
            detail="Unknown profile. Pick or create a profile first.",
        )
    return user
