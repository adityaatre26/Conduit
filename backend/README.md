# Conduit Backend

This directory contains the Python-based FastAPI backend services for Conduit, an autonomous data engineering agent.

## Technology Stack

* **Framework:** FastAPI
* **Database ORM:** SQLAlchemy (Async)
* **Databases:** PostgreSQL (Warehouse and Metadata) & Neo4j (Knowledge Graph)
* **LLM Orchestration:** Groq (Llama 3.3 70B)
* **Validation & Types:** Pydantic & python-magic

## Getting Started Natively

If you prefer to run the backend natively without Docker:

### 1. Prerequisites
Ensure you have Python 3.11+, PostgreSQL 15+, and Neo4j installed and running.

### 2. Configure Environment
Copy the `.env.example` file to `.env`:
```bash
cp .env.example .env
```
Open `.env` and fill in your database credentials and `GROQ_API_KEY`.

### 3. Install & Start Backend
Create a virtual environment, install dependencies, and start the development server:
```bash
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The backend API will be available at [http://localhost:8000](http://localhost:8000). You can check health status via `/api/health`.

## Directory Layout

* `app/main.py`: Bootstraps FastAPI, configures CORS, and handles database/Neo4j connections.
* `app/models.py`: SQLAlchemy schemas representing PostgreSQL metadata tables (Ledger, Quarantine, Proposals).
* `app/routers/`: FastAPI routes defining endpoints for ingestion, graph queries, audit, proposals, lineage, and skills.
* `app/services/`: Core logic (AI code generator, gateway classifier, AST execution sandboxing, and graph traversal).
