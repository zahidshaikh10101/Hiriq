HIRIQ PHASE 3: RESUME PARSER + CANDIDATE POOL
=============================================

1. Commit what you have first (so this change is one clean diff). Keep .env out of git.
2. Unzip this folder anywhere (NOT over your project).
3. From inside the unzipped folder run, using the folder that holds `backend` and `frontend`:

      python apply_phase3_patch.py "E:\path\to\hiriq\hiriq" --check     (shows what it will do, writes nothing)
      python apply_phase3_patch.py "E:\path\to\hiriq\hiriq"

4. In your backend virtual environment:   pip install pdfplumber python-docx
5. Restart uvicorn, hard-refresh the recruiter page (Ctrl+F5), open Candidates.
6. Optional: from the backend folder run   python -m pytest tests -q   (90 new tests included)

No database change is needed: the candidates table already exists.
If the script says a file "does not look like the version this patch was made for", nothing was written;
send me that file's current text.
