import os

from langchain_openai import ChatOpenAI

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def make_llm(model: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        api_key=os.environ["GROQ_API_KEY"],
        base_url=_GROQ_BASE_URL,
    )


def large_llm() -> ChatOpenAI:
    return make_llm(os.environ["GROQ_MODEL_LARGE"])


NAV_SYSTEM_PROMPT = (
    "You are navigating a company website to find the job application form.\n\n"
    "# Input Format\n"
    "Interactive elements are listed as: [index]<type attributes>text</>\n"
    "Only elements with [index] are interactive. Use the index to reference them.\n\n"
    "# Response Format\n"
    'Return ONLY valid JSON:\n'
    '{"current_state": {"evaluation_previous_goal": "<Success|Failed|Unknown — why>", '
    '"memory": "<what you have done, what remains>", '
    '"next_goal": "<immediate next action>"}, '
    '"action": [{"action": "<name>", ...params}]}\n\n'
    "# Available actions\n"
    '{"action": "click_element", "index": N}\n'
    '{"action": "go_to_url", "url": "<absolute url>"}\n'
    '{"action": "scroll_to_bottom"}\n'
    '{"action": "scroll_to_top"}\n'
    '{"action": "next_page"}\n'
    '{"action": "input_text", "index": N, "text": "<value>"}\n'
    '{"action": "send_keys", "keys": "Enter"}\n'
    '{"action": "go_back"}\n'
    '{"action": "at_form"}  -- you are ON the application form\n'
    '{"action": "stuck", "reason": "<why blocked>"}\n\n'
    "# Rules\n"
    "- Return at_form if you see application form fields: name, email, phone, file upload for resume/CV\n"
    "- A file input (type=file) for resume is a DEFINITIVE signal — return at_form immediately\n"
    "- Do NOT return at_form for login-only pages\n"
    "- Avoid URLs/actions already in navigation history\n"
    "- Use scroll_to_bottom or next_page if the page might have more links below\n"
    "- Return stuck only as last resort\n"
    "- Return up to 2 actions maximum\n"
    "- Return ONLY valid JSON, no prose, no markdown"
)

FILL_SYSTEM_PROMPT = (
    "You fill job application form fields from the applicant's profile and CV.\n\n"
    "Interactive elements are listed as: [index]<type attributes>text</>\n"
    "Use the numeric index to reference each element.\n\n"
    "Return a JSON array of fill commands:\n"
    '  {"index": N, "value": "<value>", "action": "input_text", "uncertain": false}\n'
    '  {"index": N, "action": "select_option", "text": "<option text>", "uncertain": false}\n'
    '  {"index": N, "value": "__CV__", "action": "file_upload"}  -- for CV/resume file input\n'
    '  {"index": N, "value": "__COVER_LETTER__", "action": "file_upload"}  -- for cover letter\n\n'
    "Rules:\n"
    "- NEVER fill authentication/login fields\n"
    "- uncertain=true if you are not sure of the correct value\n"
    "- Omit fields you have no data for\n"
    "- For select dropdowns, use exact option text\n"
    "- Return ONLY the JSON array, no prose\n"
)

CORRECTION_SYSTEM_PROMPT = (
    "Correct job application fill commands based on user feedback. "
    "Commands use 'index' (int) to reference form elements. "
    "Return the corrected JSON array only."
)
