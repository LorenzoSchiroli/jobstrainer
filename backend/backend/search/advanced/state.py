from typing import TypedDict


class AdvancedSearchState(TypedDict, total=False):
    query: str
    cv_text: str
    preference_memory: str
    clarify_questions: list[str]
    clarify_answers: list[str]
    hits: list[dict]
    refined_query: str | None
    refined_once: bool
    need_refine: bool
    results: list[dict]
