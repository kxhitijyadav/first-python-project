# LXR resume downloader

Downloads all 330 candidate resumes from the LXR export into two folders.

## How to run it

1. Put **`get_resumes.py`** and the **`.md` file from the email** in the same
   folder (your Desktop is fine).
2. Double-click **`Download Resumes (Mac).command`** or
   **`Download Resumes (Windows).bat`** from that same folder.
   (Or from a terminal: `python3 get_resumes.py`)
3. Wait. It prints each file as it lands.

You get:

```
Resumes/
├── Software Engineer Candidates/    211 resumes
└── Machine Learning Engineer/       119 resumes
```

## What it takes care of

- Unwraps the Outlook safelinks around every iCIMS link.
- Retries the whole remaining list **three times automatically**, so a link
  that times out is picked up without you doing anything.
- Checks each file's real format, so a resume named `.pdf` that is really a
  Word file is saved as `.docx` instead of a file that will not open.
- Skips whatever is already downloaded, so re-running only fills the gaps.
- Writes **`Resumes/MISSING.txt`** listing anything that did not come
  through, with the reason and the original link.

## If something is missing

The links are one-time iCIMS tracking links from a specific email. Some may
have expired or may need the browser session that received the email. Re-run
the script first — most transient failures clear. Anything still listed in
`MISSING.txt` can be opened by hand in that browser.

Requires Python 3.8+ and nothing else — no `pip install`.
