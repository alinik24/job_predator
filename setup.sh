#!/bin/bash
# JobPredator Setup Script
# Run this once to set up the full environment

set -e
echo "=== JobPredator Setup ==="

# 1. Install Python dependencies
echo "-> Installing Python dependencies..."
pip install -r requirements.txt

# 2. Install Playwright browsers
echo "-> Installing Playwright browsers..."
playwright install chromium
playwright install-deps chromium

# 3. Start PostgreSQL + pgvector + Adminer via Docker
echo "-> Starting database containers..."
docker-compose up -d
echo "-> Waiting for PostgreSQL to be ready..."
sleep 5

# 4. Install psycopg2 for Alembic (sync driver)
pip install psycopg2-binary

# 5. Run database migrations
echo "-> Running Alembic migrations..."
# For first run, use autogenerate:
# alembic revision --autogenerate -m "initial"
alembic upgrade head

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env and add your credentials"
echo "  2. Upload your CV:"
echo "     python main.py upload-cv path/to/your/cv.pdf"
echo "  3. Test scraping (dry run):"
echo "     python main.py scrape --position 'Data Engineer' --location 'Berlin'"
echo "  4. Score jobs:"
echo "     python main.py score"
echo "  5. Run full pipeline (dry run first!):"
echo "     python main.py run --cv path/to/cv.pdf --position 'Data Engineer' --dry-run"
echo "  6. Start API server:"
echo "     python main.py api"
echo ""
echo "Adminer (DB viewer): http://localhost:8080"
echo "  Server: postgres | DB: job_predator | User: postgres | Pass: postgres"
echo "API docs: http://localhost:8000/docs"
