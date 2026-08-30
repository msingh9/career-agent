from sqlalchemy.orm import Session

from ..models import Job, SearchProfile, User
from ..schemas_user import UserRead
from .companies import seed_default_companies
from .profile import get_or_create_profile


def user_to_read(db: Session, user: User) -> UserRead:
    profile = (
        db.query(SearchProfile).filter(SearchProfile.user_id == user.id).one_or_none()
    )
    job_count = db.query(Job).filter(Job.user_id == user.id).count()
    return UserRead(
        id=user.id,
        name=user.name,
        has_resume=bool(profile and profile.resume_filename),
        job_count=job_count,
        created_at=user.created_at,
    )


def list_users(db: Session) -> list[UserRead]:
    users = db.query(User).order_by(User.created_at.asc(), User.id.asc()).all()
    return [user_to_read(db, user) for user in users]


def create_user(db: Session, name: str) -> UserRead:
    clean = name.strip()
    if not clean:
        raise ValueError("Profile name is required.")
    existing = db.query(User).filter(User.name == clean).one_or_none()
    if existing:
        raise ValueError("A profile with that name already exists.")

    user = User(name=clean)
    db.add(user)
    db.commit()
    db.refresh(user)

    # Give the new profile its own default search profile and target companies.
    get_or_create_profile(db, user.id)
    seed_default_companies(db, user.id)

    return user_to_read(db, user)


def delete_user(db: Session, user_id: int) -> None:
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        raise ValueError("Profile not found.")
    if db.query(User).count() <= 1:
        raise ValueError("Cannot delete the last profile.")

    # Remove the profile's data.
    job_ids = [row[0] for row in db.query(Job.id).filter(Job.user_id == user_id).all()]
    from ..models import ApplyAttempt, JobEvent, TargetCompany

    if job_ids:
        db.query(ApplyAttempt).filter(ApplyAttempt.job_id.in_(job_ids)).delete(
            synchronize_session=False
        )
        db.query(JobEvent).filter(JobEvent.job_id.in_(job_ids)).delete(
            synchronize_session=False
        )
        db.query(Job).filter(Job.id.in_(job_ids)).delete(synchronize_session=False)
    db.query(TargetCompany).filter(TargetCompany.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(SearchProfile).filter(SearchProfile.user_id == user_id).delete(
        synchronize_session=False
    )
    db.delete(user)
    db.commit()
