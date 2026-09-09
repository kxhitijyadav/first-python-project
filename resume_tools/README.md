# Resume bulk download

Downloads the ~330 candidate resumes linked from the recruiter markdown export
(`LXR_deduplicated.md`), sorted into one folder per heading in that file:

| Heading in the markdown        | Links | Folder                            |
| ------------------------------ | ----: | --------------------------------- |
| Software Engineer Candidates   |   211 | `resumes/Software_Engineer_Candidates/` |
| Machine Learning Engineer      |   119 | `resumes/Machine_Learning_Engineer/`     |

330 links, all unique, all pointing at `tracking.icims.com`: 300 `.pdf`,
29 `.docx`, 1 `.doc`.

## Run it

```bash
pip install -r resume_tools/requirements.txt

# sanity check: what will it fetch?
python3 resume_tools/resume_links.py path/to/LXR_deduplicated.md

# try five first, to confirm the links still work from your machine
python3 resume_tools/download_resumes.py path/to/LXR_deduplicated.md --limit 5

# the real run
python3 resume_tools/download_resumes.py path/to/LXR_deduplicated.md -o resumes

# anything that failed
python3 resume_tools/download_resumes.py path/to/LXR_deduplicated.md -o resumes --retry-failed
```

Useful flags: `-j/--workers` (default 4), `--delay` (random pause before each
request, default 0.5s), `--group "Machine Learning Engineer"`, `--timeout`,
`--retries`.

## What it handles

- **Outlook safelinks** are unwrapped back to the underlying iCIMS URL.
- **Restartable** — a finished file is skipped on the next run, so an
  interrupted run just picks up where it stopped. Partial downloads are written
  to `.part` and only renamed once complete.
- **Retries** transient failures (timeouts, 429, 5xx) with exponential backoff
  and jitter, four attempts by default.
- **Verifies each file** by magic bytes (`%PDF`, `PK` for .docx, OLE for .doc).
  An expired or sign-in-walled tracking link returns an HTML page; that is
  reported as a failure instead of being saved as a fake "PDF".
- **`manifest.json`** in the output folder records every link's status, size and
  path, and is kept across runs — that is the record of what actually landed.

## Notes before you run it

- The links are one-time-ish iCIMS *click-tracking* URLs from a specific
  email. They can expire, and opening one may register as a click for the
  original recipient. Run the `--limit 5` check first.
- Keep `--workers` low (4 is the default). Hammering the tracker with 330
  parallel requests is the fastest way to get rate-limited or blocked.
- Downloaded resumes are candidate PII. `resumes/` is git-ignored on purpose —
  do not commit the files, and do not commit the source markdown either (it
  contains candidate names plus tokenised links).
