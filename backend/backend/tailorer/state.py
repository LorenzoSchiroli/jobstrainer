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
    # last_snapshot shape: {url, title, elements, scroll_y, viewport_height, scroll_height}
    last_snapshot: dict | None
    pending_correction: str | None  # set when user sends user_correction
    retry_count: int
    status: str  # navigating | tailoring | filling | filling_correction | done | failed

    # Navigation phase tracking (used by navigate_to_apply to step through pages)
    nav_phase: str        # "start" | "deciding" | "executing" | "snapshot" | "nav_done"
    nav_snapshot: dict | None   # snapshot of current page
    nav_action: dict | None     # LLM decision to execute (avoids double LLM call on replay)
    nav_history: list           # list of visited URLs to detect loops
    nav_memory: str       # running memory string maintained across navigate_to_apply steps
    no_progress_count: int  # consecutive actions that left URL+elements unchanged; resets on progress
