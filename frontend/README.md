# Conduit Frontend

This directory contains the Next.js frontend UI for Conduit. It provides the user interface for monitoring data pipelines, reviewing AI-generated transformation proposals, exploring the knowledge graph, and tracking lineage events.

## Technology Stack

* **Framework:** Next.js 14 (App Router)
* **Language:** TypeScript
* **Styling:** Tailwind CSS & Vanilla CSS
* **Design Tokens:** Neutral grey palette with action/status highlights (success, warning, danger).

## Getting Started

### 1. Prerequisites
Ensure you have Node.js (v20+) installed.

### 2. Install Dependencies
Navigate to the frontend directory and install npm packages:
```bash
cd frontend
npm install
```

### 3. Start Development Server
Run the local dev server:
```bash
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser to view the application.

## API Proxying

Next.js is configured to proxy all `/api/*` requests directly to the backend server running at `http://localhost:8000/api/*`. This configuration can be adjusted or verified in `next.config.js`.

## Folder Layout

* `src/app/`: Next.js pages representing dashboard views:
  * `/`: Overview dashboard (resolve rate, source state, metrics).
  * `/ingest`: File dropzone and ingest process state machine.
  * `/proposals`: Ingestion proposals queue and reviews.
  * `/graph`: Neo4j relationship graph viewer.
  * `/lineage`: Chronological audit lineage.
  * `/skills`: Reusable transformation skill registry.
* `src/components/`: Reusable React components (CodeBlock, PageHeader, status badges, etc.).
* `src/lib/`: API client endpoints, typescript interface declarations, and formatter utilities.
