# Security policy

Chordex is a self-hosted hobby project. It has no accounts or payments and
stores no personal data beyond the audio you upload, which is deleted after
about an hour. Bugs still matter, especially in the parts that touch the
network: file uploads, the YouTube link fetcher (`backend/youtube.py`) and
the job API.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through GitHub:
**Security → Report a vulnerability** on this repository. Include steps to
reproduce and the commit you tested.

You should get a reply within a week. Fixes land on `main`. There are no
long-term support branches.

## Running it safely

- Chordex is built to run on your own machine. If you expose it on the
  internet, put it behind authentication and rate limiting: analysis jobs are
  GPU/CPU-heavy, and `/api/analyze-url` makes outbound requests to YouTube.
- Never commit secrets. Configuration lives in `backend/.env` (gitignored),
  and `backend/.env.example` documents every variable.
