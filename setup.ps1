# JobPredator Setup Script for Windows PowerShell
# Run: .\setup.ps1

Write-Host "=== JobPredator Setup ===" -ForegroundColor Green

# Step 1: Install Python dependencies
Write-Host "`n[1/5] Installing Python dependencies..." -ForegroundColor Cyan
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed" -ForegroundColor Red; exit 1 }

# Step 2: Install Playwright + Chromium browser
Write-Host "`n[2/5] Installing Playwright browsers..." -ForegroundColor Cyan
playwright install chromium
playwright install-deps chromium 2>$null  # may not work on Windows, that's ok

# Step 3: Install psycopg2 for Alembic (sync driver needed for migrations)
Write-Host "`n[3/5] Installing psycopg2 for Alembic migrations..." -ForegroundColor Cyan
pip install psycopg2-binary

# Step 4: Start PostgreSQL + pgvector + Adminer via Docker
Write-Host "`n[4/5] Starting database containers (Docker required)..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "docker compose failed — is Docker Desktop running?" -ForegroundColor Red
    exit 1
}

Write-Host "Waiting 8 seconds for PostgreSQL to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 8

# Step 5: Run Alembic migrations
Write-Host "`n[5/5] Running database migrations..." -ForegroundColor Cyan
alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Host "Alembic migration failed" -ForegroundColor Red; exit 1 }

Write-Host "`n=== Setup Complete! ===" -ForegroundColor Green
Write-Host @"

Next steps:
  1. Edit .env — fill in your credentials (LinkedIn, Hunter.io, SMTP, etc.)
  2. Check your Azure deployment name in .env  (AZURE_OPENAI_DEPLOYMENT)
  3. Upload your CV:
       python main.py upload-cv path\to\your_cv.pdf
  4. Test scraping (safe — no applications sent):
       python main.py scrape --position "Data Engineer" --location "Berlin"
  5. Score jobs:
       python main.py score
  6. Full pipeline dry run:
       python main.py run --cv path\to\cv.pdf --position "Data Engineer" --dry-run
  7. Start the web API:
       python main.py api

URLs after setup:
  Adminer (DB viewer) : http://localhost:8080
    Server: postgres | DB: job_predator | User: postgres | Pass: postgres
  API docs            : http://localhost:8000/docs  (after running 'python main.py api')
"@
