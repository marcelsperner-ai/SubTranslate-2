# SubTranslate-2

Minimal Flask application scaffold for SubTranslate-2.

## Structure

```text
.
├── app/
│   ├── __init__.py
│   └── routes.py
├── tests/
│   └── test_app.py
├── requirements.txt
└── run.py
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python run.py
```

## Test

```bash
python -m unittest discover -s tests
```