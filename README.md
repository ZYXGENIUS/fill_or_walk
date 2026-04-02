# Fill or Walk

A lightweight fuel-economy decision helper.

The project tracks one representative domestic fuel price (Beijing 92# gasoline),
compares today with the last 365 days, and outputs:

- price percentile in the one-year window
- bargain index (higher means more economical to refuel)
- FILL / HOLD / WALK suggestion

## Project Structure

- docs/: static site for GitHub Pages
- scripts/updater.py: fetch + compute + write JSON
- docs/data/history.json: rolling one-year history
- docs/data/latest.json: latest metric snapshot
- .github/workflows/update_data.yml: scheduled data update
- .github/workflows/deploy_pages.yml: Pages deployment

## Local Development (Docker)

1. Build and run:

   docker compose up --build

2. Open browser:

   http://localhost:8000

The container will run updater first, then serve docs/.

## Manual Run Without Docker

1. Install dependencies:

   pip install -r requirements.txt

2. Update data:

   python scripts/updater.py

3. Serve static files:

   python -m http.server 8000 --directory docs

## GitHub Actions

- update_data.yml runs daily by cron and commits refreshed JSON data.
- deploy_pages.yml deploys docs/ to GitHub Pages on push to main.

## GitHub Pages Setup

1. Push this repository to GitHub.
2. In repository Settings -> Pages, set source to GitHub Actions.
3. Ensure Actions are enabled in repository settings.
4. Trigger workflows manually once to initialize first deployment.
