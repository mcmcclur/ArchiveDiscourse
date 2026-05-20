# ArchiveDiscourse

Archive a Discourse site into static HTML.

Forked and adapted from: https://github.com/mcmcclur/ArchiveDiscourse

Example archive: https://discuss-learn.media.mit.edu/

## Setup

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set configuration with environment variables:

```bash
export DISCOURSE_BASE_URL="https://your-discourse.example"
export DISCOURSE_API_KEY="1d6340b8ec5aea07bd3ceff3b4e8f682f96c8091a95e3e1f12b4623ca2b4597a"
export DISCOURSE_API_USERNAME="your-archive-user"
```

Optional settings:

```bash
export DISCOURSE_OUTPUT_DIR="export"
export DISCOURSE_ARCHIVE_BLURB="Archived May, 2026."
export DISCOURSE_MAX_PAGES="99"
export DISCOURSE_REQUEST_DELAY="1"
export DISCOURSE_PROGRESS_EVERY="5"
```

Run:

```bash
python archive-discourse.py
```

Optional title override:

```bash
python archive-discourse.py --title "Discourse forum for Calc III, Spring 2026"
```

Optional basic anonymization:

```bash
python archive-discourse.py --anonymize-users
```

Preserve selected usernames while anonymizing everyone else:

```bash
python archive-discourse.py --anonymize-users --preserve-user audrey --preserve-user alice,bob
```

## API key recommendations

For a public repo, do not store credentials in `archive-discourse.py`.

- Use a dedicated Discourse account for archiving.
- Generate a `Single User` API key for that account.
- Prefer a `Read-only` key unless you need broader access.
- Keep secrets in environment variables or an untracked `.env` file.
- Rotate the key if it is ever exposed.

If no API key is set, the script will still run against public content, but private categories and topics will not be included.

## Notes

- The script uses `/site/basic-info.json` to pick up the site title and configured logo when available.
- Topic pages and the index include MathJax 4 from jsDelivr and automatically convert Discourse math tags like `<span class="math">...</span>` and `<div class="math">...</div>` into MathJax delimiters before typesetting.
- `--anonymize-users` replaces displayed post usernames and cooked `@mentions` with stable aliases such as `User 001`.
- `--preserve-user` keeps selected usernames visible while anonymizing everyone else.
- Anonymized users get generated letter avatars with stable per-user colors; preserved users keep their original avatars.
