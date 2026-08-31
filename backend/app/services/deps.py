# Copyright 2026 Manish Singh
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
