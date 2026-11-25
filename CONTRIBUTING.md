# Contributing to ListingQ

Thanks for helping. ListingQ is small on purpose, so the rules are simple.

## Before you start

- Open an issue first for anything bigger than a small fix, so we can agree on the approach.
- Never commit real supplier files, customer data, API keys or marketplace credentials. Use fictional demo data like `jobs/demo-001`.

## Setup

```bash
pip install -r requirements.txt
python3 -m pytest -q
```

All tests must pass before you open a pull request.

## Good places to help

- A config for another marketplace template (see `config/amazon_in_home_kitchen.yaml`).
- Better parsing of messy supplier PDFs and spreadsheets.
- More tests for the checks in `listingq/validate.py`.
- Clearer docs and examples.

## Pull requests

- Keep each pull request to one change.
- Explain what it does and how you tested it.
- Add or update tests for any change to the engine.
