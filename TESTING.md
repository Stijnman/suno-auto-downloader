# Testing suno-auto-downloader

Use Python 3.11 or 3.12. From the repository root:

```sh
python -m pip install -r requirements.txt
python -m compileall -q suno_downloader.py
python -m unittest discover -s tests -v
```

The tests exercise local behavior without real credentials or live network calls.
GitHub Actions runs both Python versions and keeps documentation and secrets checks.
The secrets scan uses the event commit range and full history so a push does not
compare the default branch with itself. RAPTOR is a separate optional workflow.

These checks do not prove live provider availability or complete end-to-end behavior.
