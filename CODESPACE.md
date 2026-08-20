# Bring these updates into your Codespace

This environment cannot push to GitHub. In **your** Codespace, replace the files listed below, then pull is not needed — you already have them locally. Commit from the Codespace if you want them on GitHub.

## Files to replace / add

- `app.py`
- `requirements.txt`
- `src/config.py`
- `src/geo.py`
- `src/pipeline.py`
- `src/export.py`
- `tests/test_units.py`

## In the Codespace terminal

```bash
# if the app is running
# Ctrl+C

pip install -r requirements.txt
bash run.sh
```

New dependency: `plotly` (drag-zoom on the profile).
