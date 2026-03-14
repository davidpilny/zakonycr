# zakonycr

A scraper that maintains an up-to-date copy of all Czech laws, sourced from the
official **e-Sbírka** REST API (<https://api.e-sbirka.cz>).

Scraped laws are stored as Markdown files under `laws/{year}/{number}.md` so
that AI agents (e.g. GitHub Copilot) and human contributors can read them,
suggest changes, and open pull-requests against the repository.

---

## Repository layout

```
zakonycr/
├── scraper/
│   ├── client.py      # e-Sbírka REST API client
│   ├── scraper.py     # sync orchestration (full & incremental)
│   ├── storage.py     # Markdown file storage + sync-state tracking
│   └── cli.py         # command-line interface
├── laws/
│   ├── {year}/
│   │   └── {number}.md   # one file per law
│   └── _state.json        # auto-generated sync state
├── tests/             # pytest test suite
├── .github/
│   └── workflows/
│       └── scrape.yml # automated daily sync
├── requirements.txt
└── pyproject.toml
```

Each law file uses YAML front-matter followed by the full text:

```markdown
---
cislo: 89
rok: 2012
nazev: Zákon č. 89/2012 Sb., občanský zákoník
datum_ucinnosti: 2014-01-01
url: https://api.e-sbirka.cz/...
---

§ 1
...
```

---

## Quick-start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Obtain an API key

Register at the Ministry of Interior and request access to the e-Sbírka API:
<https://e-sbirka.gov.cz/restful-api>

Set the key as an environment variable:

```bash
export ESBIRKA_API_KEY="your-api-key-here"
```

### 3. Run a sync

```bash
# Full sync (first run)
python -m scraper.cli sync

# Incremental sync (only laws changed since last run)
python -m scraper.cli sync --incremental

# Force a full re-sync, ignoring stored state
python -m scraper.cli sync --force

# Fetch a single law (e.g. 89/2012 – Občanský zákoník)
python -m scraper.cli fetch 89 2012

# Show storage statistics
python -m scraper.cli stats
```

---

## Automated sync (GitHub Actions)

The workflow `.github/workflows/scrape.yml` runs automatically every day at
03:00 UTC. It performs an **incremental** sync by default and commits any
updated law files back to the repository.

To trigger a full re-sync manually, go to
**Actions → Scrape Czech Laws → Run workflow** and enable the *force_full*
input.

**Required secret:** Add `ESBIRKA_API_KEY` in
*Settings → Secrets and variables → Actions*.

---

## Interacting with the agent / suggesting improvements

Because every law lives as a plain-text Markdown file, AI tools (GitHub
Copilot, ChatGPT, etc.) can read, summarise, and annotate them directly in the
repository.  The intended workflow for suggesting improvements is:

1. Fork or create a branch.
2. Edit the relevant `laws/{year}/{number}.md` file.
3. Open a pull-request describing the proposed change.

The automated sync workflow will never overwrite a manually edited law file
without going through the normal PR review process.

---

## Development

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
python -m pytest tests/ -v
```

---

## License

The scraper code is MIT-licensed.  The law texts themselves are official Czech
government documents published in the *Sbírka zákonů a mezinárodních smluv*
and are in the public domain.
