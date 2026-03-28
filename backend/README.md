# PaperEasy Backend

Minimal FastAPI backend foundation for the PaperEasy frontend.

## Prerequisites

- Python 3.10+

## Install dependencies

```bash
pip install -r requirements.txt
```

## Environment variables

The backend reads configuration from `.env` in the `backend/` directory.

```env
APP_NAME=PaperEasy Backend
DEBUG=true
```

## Run the development server

```bash
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/health` to confirm the API is running.

## Notes

- CORS is enabled for `http://localhost:3000`
- Request logging and basic error handling middleware are included
