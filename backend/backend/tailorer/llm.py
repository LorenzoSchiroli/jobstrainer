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


FILL_SYSTEM_PROMPT = (
    "You fill job application form fields from the applicant's profile and CV.\n\n"
    "Interactive elements are listed as: [index]<type attributes>text</>\n"
    "Use the numeric index to reference each element.\n\n"
    "Return a JSON array of fill commands. Each command is one of:\n"
    '  {"index": N, "value": "<text value>"}                          -- text/textarea/combobox\n'
    '  {"index": N, "value": "true"}                                   -- checkbox/radio (truthy = check)\n'
    '  {"index": N, "value": "<option text>"}                         -- select/dropdown\n'
    '  {"index": N, "value": "__CV__", "generate": true|false}        -- CV/resume file input\n'
    '  {"index": N, "value": "__COVER_LETTER__", "generate": true|false} -- cover letter file input\n\n'
    "Document status is provided in the prompt. Set generate=true only if the document has not yet been\n"
    "generated this session, or if the user explicitly asked for a new version.\n\n"
    "Add \"uncertain\": true to any command where you are not confident of the correct value.\n\n"
    "Rules:\n"
    "- NEVER fill authentication/login fields\n"
    "- Omit fields you have no data for\n"
    "- Return ONLY the JSON array, no prose, no markdown fences\n"
)
