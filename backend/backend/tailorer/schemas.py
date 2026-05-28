import uuid
from datetime import datetime
from pydantic import BaseModel


class ProfileUpsert(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    work_auth: str | None = None
    urls: dict | None = None
    extra_qa: dict | None = None


class ProfileResponse(ProfileUpsert):
    id: uuid.UUID
    user_id: uuid.UUID
    cv_text: str | None = None
    has_cv: bool
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_profile(cls, p) -> "ProfileResponse":
        return cls(
            id=p.id,
            user_id=p.user_id,
            first_name=p.first_name,
            last_name=p.last_name,
            email=p.email,
            phone=p.phone,
            city=p.city,
            country=p.country,
            work_auth=p.work_auth,
            urls=p.urls,
            extra_qa=p.extra_qa,
            cv_text=p.cv_text,
            has_cv=p.cv_text is not None,
            updated_at=p.updated_at,
        )
