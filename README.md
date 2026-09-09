## Project setup

```
python3 -m venv .venv
source .venv/bin/activate
pip intall -r requirements.txt
python3 station_simulator.py
uvicorn backend.app.main:app --reload
```

Then open http://localhost:8000 in a browser.