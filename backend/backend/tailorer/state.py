from typing import TypedDict


class TailorerState(TypedDict):
    # Session context (set at graph start, never mutated)
    job_id: str
    user_id: str
    job_title: str
    job_description: str
    profile: dict
    cv_text: str

    # Document bytes (built lazily by node_map when LLM requests generate=true)
    cv_bytes: bytes
    cl_bytes: bytes
    cl_text: str

    # Fill pass state (reset each pass via start_or_fill input)
    last_snapshot: dict | None      # whole-page snapshot sent with start_or_fill
    fill_commands: list[dict]        # declarative commands output by node_map
    last_feedback: str | None        # user's typed instruction for this pass
    retry_count: int                 # apply-loop counter; capped at 2
    status: str                      # mapping | applying | filled | failed
