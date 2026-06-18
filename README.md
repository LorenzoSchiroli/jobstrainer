# jobstrainer

## Commands

### Offer

Fetch recent job offers matching a search query.

```bash
uv run python -m offer "machine learning engineer"
uv run python -m offer "machine learning engineer" --hours 48
uv run python -m offer "machine learning engineer" --sources jobspy,adzuna
```

Available sources: `jobspy`, `adzuna`, `arbeitnow`, `remotive` (default: all).

### Company

Enrich a company profile with metadata (size, funding, financial health, etc.).

```bash
uv run python -m company "Stripe"
uv run python -m company "Stripe" "San Francisco"
uv run python -m company "Stripe" --debug
```

Requires `GROQ_API_KEY` in `.env`.

### Tailor

Generate tailored CV versions (LLM-focused and Computer Vision-focused) from the base CV.

```bash
uv run python tailor_cv.py
```

Outputs to `tailor/lorenzo_schiroli_cv_llm.docx` and `tailor/lorenzo_schiroli_cv_cv.docx`.

## Design

search
input: cv + query (what i'm looking for)
output: rank of offers

Architecture:
- scraper + parsing (jobs and companies, actively interrogate the backend);
    - clean text before saving
- backend (holding the database and data, holding the ranker operation, fully passive); tools: postgresql + opensearch (bm25 on full text + embedding on summary + crossencoder, no chunking because llm summary seems to be better)
- frontend (just ui, react)

Next:
- fix scraper? add llanggraph (or temporal) as a crawler orchestrator?
- llanggraph:
    - advanced query search with miltistep refinement (very fiew steps) + fit evaluation for final result (using also memory of user preferences or past session)
    - tailor for cv, cl, custom message, "autofill" with human-in-the-loop job offer page (to avoid scaling problems we can leverage user's browser through an extension, otherwise we need plawright workers to scale or playwright apis)
    - advanced crawling / discovery / orchestration around scraping (find links, retries, fallbacks): only on edge cases / unknown websites, like hidden job discovery or company discover
- deploying it on aws or similar
- trining (do at the end): use llm to generate 1-5k examples for the training + 500 test (hard negatives are important)
- company discover

jobshrinker.com

Try to see nanobrowser.


Things to change:
- focus on the filling part only (let's disble the navigation part at the moment like finding the job offer or going to the next fill page, remove the "start agent" and ad a button called "fill" right above the search bar, always present as a quick task)
- let the model have a view of the whole page, not just the visible part (and remove the navitation like scroll down or scroll up, it's not needed anymore)
- fill should work on as many type of pages as possible (react, simple page, other, etc)
- fill should work on any kind of object / element like free test, checkbox, dropdown, file upload, etc...
- the steps should be simplified like one single fill function (that is eventually repeated)
- if it fails the fill it should retry autonomously correcting the fill
- the agent should be ready for a correction from the user (the usual bar)
- take inspiration from battle tested tools
