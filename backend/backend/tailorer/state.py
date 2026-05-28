from typing import TypedDict


class TailorerState(TypedDict):
    # Session context (set at start, read-only)
    job_id: str
    user_id: str
    job_title: str
    job_description: str
    company_homepage: str
    profile: dict          # serialized ApplicantProfile fields
    cv_text: str

    # Agent state (mutated during execution)
    apply_url: str
    current_page: int
    filled_fields: dict[str, str]
    cv_bytes: bytes
    cl_bytes: bytes
    cl_text: str
    last_snapshot: dict | None    # cached DOM snapshot, cleared after navigate_next
    pending_correction: str | None  # set when user sends user_correction
    retry_count: int
    status: str  # navigating | tailoring | filling | filling_correction | done | failed
