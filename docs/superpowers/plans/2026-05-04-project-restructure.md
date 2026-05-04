# Project Restructure: retriever→offer, enricher→company Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `retriever/` → `offer/scraping/` and split `enricher/` into `company/scraping/` (fetcher, searcher) and `company/parsing/` (extractor), with a top-level `company/company.py` orchestrator.

**Architecture:** Simple file moves + import string updates. The only non-trivial part is splitting `enricher/` into two sub-packages.

---

## Import changes

| Old | New |
|---|---|
| `retriever.models` | `offer.scraping.models` |
| `retriever.filters` | `offer.scraping.filters` |
| `retriever.deduplicator` | `offer.scraping.deduplicator` |
| `retriever.sources.base` | `offer.scraping.sources.base` |
| `retriever.sources.*` | `offer.scraping.sources.*` |
| `retriever.cli` | `offer.scraping.cli` |
| `enricher.models` | `company.models` |
| `enricher.fetcher` | `company.scraping.fetcher` |
| `enricher.searcher` | `company.scraping.searcher` |
| `enricher.extractor` | `company.parsing.extractor` |
| `enricher.enricher` | `company.company` |

Patch targets in `tests/enricher/test_enricher.py` also need updating: `"enricher.enricher.*"` → `"company.company.*"`.

---

## Task 1: Create `offer/` from `retriever/`

- [ ] Create dirs and move files

```bash
mkdir -p offer/scraping/sources offer/parsing
touch offer/__init__.py offer/scraping/__init__.py offer/scraping/sources/__init__.py offer/parsing/__init__.py

# Move files
cp retriever/models.py       offer/scraping/models.py
cp retriever/filters.py      offer/scraping/filters.py
cp retriever/deduplicator.py offer/scraping/deduplicator.py
cp retriever/sources/base.py              offer/scraping/sources/base.py
cp retriever/sources/adzuna_source.py     offer/scraping/sources/adzuna_source.py
cp retriever/sources/arbeitnow_source.py  offer/scraping/sources/arbeitnow_source.py
cp retriever/sources/jobspy_source.py     offer/scraping/sources/jobspy_source.py
cp retriever/sources/remotive_source.py   offer/scraping/sources/remotive_source.py
cp retriever/cli.py          offer/scraping/cli.py
```

- [ ] Create `offer/__main__.py`

```python
from offer.scraping.cli import main

if __name__ == "__main__":
    main()
```

- [ ] Update all imports in the copied files (bulk sed)

```bash
# All files under offer/ that reference retriever.*
find offer/ -name "*.py" -exec sed -i '' \
  -e 's/from retriever\.models/from offer.scraping.models/g' \
  -e 's/from retriever\.filters/from offer.scraping.filters/g' \
  -e 's/from retriever\.deduplicator/from offer.scraping.deduplicator/g' \
  -e 's/from retriever\.sources\.base/from offer.scraping.sources.base/g' \
  -e 's/from retriever\.sources\./from offer.scraping.sources./g' \
  -e 's/from retriever\.cli/from offer.scraping.cli/g' \
  {} +
```

- [ ] Verify

```bash
python -c "from offer.scraping.cli import main; print('ok')"
```

---

## Task 2: Create `company/` from `enricher/`

- [ ] Create dirs and move files

```bash
mkdir -p company/scraping company/parsing
touch company/__init__.py company/scraping/__init__.py company/parsing/__init__.py

cp enricher/models.py   company/models.py
cp enricher/fetcher.py  company/scraping/fetcher.py
cp enricher/searcher.py company/scraping/searcher.py
cp enricher/extractor.py company/parsing/extractor.py
cp enricher/enricher.py  company/company.py
```

- [ ] Create `company/__main__.py`

Copy `enricher/__main__.py`, changing:
- `from enricher.enricher import enrich` → `from company.company import enrich`
- Usage string: `python -m enricher` → `python -m company`

- [ ] Update all imports in the copied files

```bash
find company/ -name "*.py" -exec sed -i '' \
  -e 's/from enricher\.models/from company.models/g' \
  -e 's/from enricher\.fetcher/from company.scraping.fetcher/g' \
  -e 's/from enricher\.searcher/from company.scraping.searcher/g' \
  -e 's/from enricher\.extractor/from company.parsing.extractor/g' \
  -e 's/from enricher\.enricher/from company.company/g' \
  {} +
```

- [ ] Verify

```bash
python -c "from company.company import enrich; print('ok')"
```

---

## Task 3: Migrate tests + delete old packages

- [ ] Create new test directories

```bash
mkdir tests/offer tests/company
touch tests/offer/__init__.py tests/company/__init__.py

cp tests/retriever/test_deduplicator.py  tests/offer/
cp tests/retriever/test_filters.py       tests/offer/
cp tests/retriever/test_adzuna_source.py tests/offer/
cp tests/retriever/test_arbeitnow_source.py tests/offer/
cp tests/retriever/test_jobspy_source.py tests/offer/
cp tests/retriever/test_remotive_source.py tests/offer/

cp tests/enricher/test_enricher.py tests/company/test_company.py
cp tests/enricher/test_extractor.py tests/company/
cp tests/enricher/test_fetcher.py   tests/company/
cp tests/enricher/test_models.py    tests/company/
cp tests/enricher/test_searcher.py  tests/company/
```

- [ ] Update imports in test files (bulk sed)

```bash
find tests/offer/ tests/company/ -name "*.py" -exec sed -i '' \
  -e 's/from retriever\./from offer.scraping./g' \
  -e 's/from enricher\.enricher/from company.company/g' \
  -e 's/from enricher\.models/from company.models/g' \
  -e 's/from enricher\.extractor/from company.parsing.extractor/g' \
  -e 's/from enricher\.fetcher/from company.scraping.fetcher/g' \
  -e 's/from enricher\.searcher/from company.scraping.searcher/g' \
  -e 's/"enricher\.enricher\./"company.company./g' \
  {} +
```

Note: the last sed line updates the `patch()` target strings inside `test_company.py`.

- [ ] Run tests

```bash
python -m pytest tests/offer/ tests/company/ -v --tb=short
```

Expected: same pass count as `tests/retriever/` + `tests/enricher/` before.

- [ ] Delete old packages

```bash
rm -rf enricher/ retriever/ tests/enricher/ tests/retriever/
```

- [ ] Final verification + commit

```bash
python -m pytest tests/ -v --tb=short
git add -A
git commit -m "$(cat <<'EOF'
refactor: rename retriever→offer/scraping, split enricher→company/{scraping,parsing}

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```
