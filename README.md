# JobPredator

An AI-powered adaptive job hunter for Germany. Scrapes 21+ job boards, scores every position against your full CV profile with **context-aware semantic understanding**, learns from your feedback, and generates ATS-optimized tailored cover letters.

## 🚀 New Enhanced Features

### 🧠 Context-Aware Semantic Matching
- **Beyond keywords**: Understands that "Wind Design Engineer" relates to "Energy Engineering"
- **Knowledge Graph**: 100+ domain relationships (energy → wind/solar/grid, ML → deep learning/neural networks)
- **Hybrid scoring**: Combines domain knowledge (30%) + LLM reasoning (70%) for accurate matching

### 🔍 GitHub Job Mining
- Scrapes job postings from **GitHub repositories**
- Finds "We're hiring" in READMEs, career page links
- Filters by topics (machine-learning, energy, data-science) and company stars
- Perfect for finding startup and open-source company jobs

### 📄 ATS Optimization (0-100 Score)
- Analyzes resumes for **Applicant Tracking System** compatibility
- Keyword density analysis and missing keyword detection
- Formatting issue detection (tables, special characters, columns)
- Pre-submission optimization suggestions

### 🤖 LinkedIn Easy Apply Automation
- **GPT-powered form filling** for LinkedIn applications
- Intelligent answer generation for screening questions
- Multi-step application handling with human-like delays
- Based on Auto_Jobs_Applier_AIHawk (20k+ GitHub stars)

### 📊 Enhanced Coverage
- **21 job boards** (was 20): Added GitHub
- Semantic HTML parsing with trafilatura
- Better anti-bot evasion with playwright-stealth

---

## Project Structure

```
job_predator/
├── main.py                     # CLI entry point (Typer + Rich)
├── requirements.txt            # Python dependencies
├── docker-compose.yml          # PostgreSQL + pgvector setup
│
├── core/                       # Core infrastructure
│   ├── config.py              # Environment configuration
│   ├── database.py            # SQLAlchemy async setup
│   ├── models.py              # Database models (jobs, cv_profile, user_memory, etc.)
│   └── user_profile.py        # User profile YAML manager
│
├── scrapers/                   # Job board scrapers (20+ platforms)
│   ├── aggregator.py          # Parallel scraping orchestrator
│   ├── stepstone_scraper.py   # StepStone
│   ├── xing_scraper.py        # XING
│   ├── fraunhofer_scraper.py  # Fraunhofer Institute
│   ├── euraxess_scraper.py    # EURAXESS (EU research)
│   ├── helmholtz_scraper.py   # Helmholtz Association
│   ├── wellfound_scraper.py   # Wellfound (startups)
│   ├── heise_scraper.py       # Heise Jobs (tech)
│   ├── academics_scraper.py   # Academics.de
│   ├── zeit_scraper.py        # Zeit Jobs
│   ├── jobspy_scraper.py      # LinkedIn, Indeed, Glassdoor wrapper
│   └── ...                    # 10+ more platforms
│
├── cv/                         # CV parsing and position generation
│   ├── cv_parser.py           # Main CV parser (orchestrates extractors)
│   ├── pdf_extractor.py       # PDF → text extraction
│   ├── latex_extractor.py     # LaTeX/Overleaf → structured data
│   ├── position_generator.py  # LLM-based job title suggestions
│   └── cover_letter_learner.py # Learns writing style from existing CLs
│
├── matching/                   # Job scoring and analysis
│   ├── scorer.py              # LLM-based CV-job matching (0-10 score)
│   ├── embedder.py            # Semantic embeddings (sentence-transformers)
│   ├── job_skills_analyzer.py # Per-job skills matrix + ATS scoring
│   └── cover_letter_generator.py # Tailored cover letter generation
│
├── agents/                     # LangGraph workflow
│   └── graph.py               # 7-node DAG (parse → scrape → score → analyze)
│
├── applications/               # Auto-application modules
│   ├── linkedin_applier.py    # LinkedIn Easy Apply automation
│   ├── stepstone_applier.py   # StepStone form filler
│   ├── indeed_applier.py      # Indeed Quick Apply
│   └── form_ai.py             # Generic form field detection
│
├── outreach/                   # HR contact finding + email outreach
│   └── ...
│
├── cover_letter/               # Cover letter generation
│   ├── generator.py           # Main CL generator
│   └── exporter.py            # PDF/DOCX export
│
├── documents/                  # Document Q&A
│   ├── store.py               # Vector store (pgvector)
│   └── qa.py                  # RAG-based document retrieval
│
├── api/                        # FastAPI REST API
│   └── main.py                # API routes
│
├── templates/                  # Jinja2 templates (cover letters, emails)
├── scripts/                    # Utility scripts
├── user_documents/             # User CVs, cover letters (gitignored)
├── output/                     # Generated files (gitignored)
└── memory/                     # RLHF state (gitignored)
```

---

## Architecture

```
JobPredator — AI-Powered Adaptive Job Hunter
├── CV parsing           — PDF / LaTeX / Overleaf → structured profile
├── Position generator   — LLM analyses your CV → suggests job titles to search
├── Enhanced Scraping    — 21+ boards including GitHub job mining
│   ├── Traditional boards   — StepStone, XING, LinkedIn, Indeed, etc.
│   ├── Research platforms   — EURAXESS, Fraunhofer, Helmholtz
│   └── NEW: GitHub jobs     — mines hiring from READMEs, career pages
│
├── Hybrid Semantic Scoring — Context-aware matching beyond keywords
│   ├── Knowledge Graph      — understands "wind engineer" → "energy"
│   ├── Domain relationships — energy → wind/solar/grid/power systems
│   └── LLM + embeddings     — 70% LLM + 30% semantic for final score
│
├── ATS Optimization     — maximizes resume pass-through rate
│   ├── Keyword density      — extract & match job-specific keywords
│   ├── Formatting check     — detects ATS-unfriendly elements
│   └── ATS score (0-100)    — pre-submission optimization
│
├── Adaptive memory      — RLHF loop: learns from your feedback each round
├── Gap tracker          — identifies missing skills across all top jobs
├── Skills analyzer      — per-job: have / missing / niche keywords / ATS score
├── Cover letter gen     — tailored letters in your own writing style + ATS keywords
├── LinkedIn Easy Apply  — GPT-powered auto-application (AIHawk-inspired)
└── Outreach             — HR contact finder + personalised emails
```

---

## First-Time Setup

### 1. Install

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure `.env`

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/job_predator
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/job_predator
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-api-key
LLM_API_VERSION=2024-01-01
LLM_MODEL_NAME=gpt-4
```

> **Windows/Docker important**: Always use `127.0.0.1`, never `localhost`.
> `localhost` resolves to IPv6 `::1` on Windows but Docker PostgreSQL only binds IPv4.

### 3. Upload your CV

```bash
python main.py upload-cv my_cv.pdf
# or from Overleaf directory:
python main.py upload-cv cv/
```

### 5. Create your personal profile (beyond the CV)

```bash
python main.py profile --init
```

This creates `output/user_profile.yaml`. **Edit this file** — it teaches the AI:
- Your personal motivation and career goals
- Extra context for specific experiences ("what I actually learned / am proud of")
- Skills with concrete evidence (project-level proof)
- Dealbreakers, remote preferences, availability
- Cover letter writing preferences (language, tone)

The more you fill in, the more personalised your cover letters and scoring become.

### 6. Learn your writing style (run once)

```bash
python main.py learn-style --dir "C:/mydesktop/Career Application/Cover Letters"
```

Reads all your PDFs, analyses tone, structure, recurring strengths, and characteristic phrases. Future cover letters will match your authentic style.

---

## Core Workflow

### Step 1 — Generate position suggestions from your CV

```bash
python main.py suggest-positions --cv my_cv.pdf
```

The LLM analyses **everything** in your CV: education level and field, thesis topic, skills, experience, projects, publications, languages, certifications. It suggests:

| Category | Examples |
|----------|---------|
| **Primary roles** | Energy Data Scientist, ML Engineer for Energy Systems |
| **Adjacent roles** | MLOps Engineer, Research Software Engineer |
| **Research roles** | Fraunhofer / Helmholtz / EURAXESS positions |
| **German-specific** | Werkstudent Energieinformatik, KI Ingenieur, German job titles |
| **Extra keywords** | "KI Energiesysteme", "Python Machine Learning Energie" |

Output: `output/suggested_positions.yaml`

---

### Step 2 — Review and approve positions

Open `output/suggested_positions.yaml` and set `approved: true/false`:

```yaml
instructions: |
  Set 'approved: true' for positions you want to search.
  Add new positions manually under any category.
  Then run: python main.py scrape-from-suggestions

market_insight: |
  Strong positioning at the intersection of energy engineering and AI/ML.
  German market has high demand for candidates who understand both domains.
  Fraunhofer, Helmholtz, and energy companies (E.ON, RWE, Siemens) are top targets.

primary_roles:
  - title: Energy Data Scientist
    title_de: Energiedaten Wissenschaftler
    rationale: Core match — MSc Energy + Python + ML experience
    confidence: 0.92
    sectors: [Energy, Research, Tech]
    seniority: junior/mid
    approved: true          # ← already approved by default

  - title: Grid Intelligence Engineer
    title_de: Netzintelligenz Ingenieur
    confidence: 0.85
    approved: true

adjacent_roles:
  - title: MLOps Engineer
    confidence: 0.70
    approved: false         # ← not approved by default; set true to include

research_roles:
  - title: Research Software Engineer
    title_de: Wissenschaftlicher Softwareentwickler
    rationale: Ideal for Fraunhofer/DFG/Max Planck — research background
    confidence: 0.90
    approved: true          # ← research roles approved by default

german_specific_roles:
  - title: Werkstudent Energietechnik
    title_de: Werkstudent Energietechnik
    approved: true

extra_search_keywords:
  - "KI Energiesysteme"
  - "Python Machine Learning Energie"
  - "Smart Grid Data Engineer"
  - "Predictive Maintenance Power Grid"

avoid_titles:
  - "Frontend Developer — no web UI experience in CV"
```

---

### Step 3 — Scrape all platforms using approved positions

```bash
python main.py scrape-from-suggestions
```

Reads every `approved: true` title and keyword and searches all 20+ platforms in parallel.
Both the English and German versions of each title are used.

---

### Step 4 — Score all scraped jobs

```bash
python main.py score
# After giving feedback (recommended):
python main.py score --memory
```

Scoring uses ALL CV fields (education level, thesis, projects, publications) and your profile
context. The `--memory` flag additionally applies preference adjustments learned from your
feedback (see Adaptive Memory section below).

---

### Step 5 — Browse results

```bash
python main.py list-jobs --min-score 7.5
python main.py list-jobs --min-score 7.0 --limit 50 --gaps
python main.py list-jobs --source fraunhofer --min-score 0
```

---

## Per-Job Deep Analysis

### Analyse skills matrix + niche keywords

```bash
# Single job
python main.py analyze-job --job-id <uuid>

# All top-scored jobs (batch)
python main.py analyze-job --all --min-score 7.5 --limit 15
```

Produces for each job:
- **Skills matrix**: every required skill → whether you have it (with CV evidence)
- **Missing skills**: gaps + concrete workarounds to mention anyway
- **Niche keywords**: company/domain-specific terms to learn (e.g. if the company uses digital twins for grid simulation, you get that specific context — not just "data engineering")
- **ATS score estimate**: how well your CV would score in their ATS
- **CV sections to emphasise**: which experiences/projects to highlight
- **Interview preparation topics**

### View skills for a job

```bash
python main.py job-skills --job-id <uuid>
```

Example output:
```
=================================================================
SKILLS ANALYSIS: Energy Data Scientist @ E.ON Digital Technology
=================================================================
ATS Match Score: 8.2/10
Summary: Strong fit — energy domain + Python ML directly relevant...

✓ YOU HAVE (12 skills):
   ★★★★★ Python [tech] — extensive use in thesis + Fraunhofer work
   ★★★★★ Energy Systems Knowledge [domain] — MSc in energy engineering
   ★★★★  Machine Learning [tech] — applied in thesis for energy forecasting

✗ MISSING (3 skills):
   ★★★★  Apache Kafka [must / tech]
   ★★★   Azure Cloud [nice / tech]

GAP WORKAROUNDS:
   • Apache Kafka: mention Python async + message queuing concepts

EMPHASISE IN APPLICATION:
   → Master thesis on power system optimisation
   → Fraunhofer working student experience

NICHE KEYWORDS TO LEARN:
   [Digital Twin of Energy Grid]
     Why: Core technology this team uses for grid operations
     Learn: IEEE papers on digital twins; ENTSO-E standards docs

ATS KEYWORDS TO ADD:
   energy management system, EMS, SCADA, time series forecasting

PREPARE FOR INTERVIEW:
   • Questions about power flow algorithms
   • Why E.ON vs. competitors (Siemens Energy, RWE, EnBW)

Generate cover letter: python main.py cover-letter --job-id abc123
```

---

## Cover Letter Generation

### Generate a tailored cover letter

```bash
python main.py cover-letter --job-id <uuid>
python main.py cover-letter --job-id <uuid> --lang de --output cl.txt
```

The generator combines:
1. Your full CV (all sections, rich mode — education, thesis, projects, publications)
2. `output/user_profile.yaml` context (motivation, experience context, skills evidence)
3. Your **learned writing style** (tone, structure, characteristic phrases from your real CLs)
4. Deep job analysis (top requirements, company mission, cultural cues, killer keywords)
5. Skills matrix (most relevant CV sections to highlight for this specific role)

The result:
- In your authentic voice (not generic)
- Specific to THIS company and role
- Mentions your most relevant project/education/experience
- Contains ATS-targeted keywords
- In German or English (auto-detected from job posting)
- One page (~400 words)

---

## Adaptive Memory & RLHF Learning

JobPredator learns from every interaction. Over 3–5 feedback rounds it converges on your actual preferences.

### Give feedback on jobs

```bash
python main.py feedback --job-id <uuid> --decision apply --reason "Energy + ML fit"
python main.py feedback --job-id <uuid> --decision skip --reason "Too much frontend"
python main.py feedback --job-id <uuid> --decision interested --user-score 8.5
```

**Decisions**: `apply`, `interested`, `skip`, `blacklist_company`

What happens internally:
- **apply/interested**: updates your preference embedding (EMA of liked-job embeddings). Future jobs similar to this one get a score boost
- **skip**: similar future jobs are penalised
- **blacklist_company**: that company is permanently skipped
- **user-score**: overrides the LLM score for this specific job

### Claim skills the AI missed

```bash
python main.py remember --skill "Apache Kafka" --status have_it
python main.py remember --skill "Azure Cloud" --status learning
python main.py remember --skill "React" --status not_interested
```

After claiming skills, re-run: `python main.py score --memory`

The CV summary injected into the LLM prompt will include your claimed skills alongside CV evidence.

### How the learning loop works

```
Round 1: LLM scores jobs from CV only
         → You browse results, give feedback on 5-10 jobs
         → Claim skills the AI missed

Round 2: python main.py score --memory
         → Enriched CV (claimed skills visible)
         → Score adjustment: cosine similarity to liked/disliked embeddings
         → Hard penalty for blacklisted companies
         → Scores shift toward your actual preferences

Round 3+: Each round improves as more feedback accumulates
          The k-NN comparison pool grows → adjustments become more precise
```

### Show memory state

```bash
python main.py memory
```

---

## Skill Gap Analysis

### Analyse missing skills across all top jobs

```bash
python main.py gaps --min-score 7.5
python main.py gaps --min-score 7.0 --limit 200
```

Uses LLM-based semantic normalisation (not regex). Groups similar gap descriptions:

```
Top Missing Skills (across all high-scoring jobs):
  1. MLOps / Production ML Deployment   (33 jobs)
  2. Cloud Platforms (AWS/GCP/Azure)     (30 jobs)
  3. German Language Proficiency         (17 jobs)
  4. Commercial AI/ML Experience         (16 jobs)
  5. CI/CD Pipelines                     (13 jobs)
```

### Get CV improvement suggestions for Overleaf

```bash
python main.py cv-suggestions --output overleaf_additions.tex
```

Generates LaTeX snippets you can paste into your Overleaf CV:

```latex
% ADD TO SKILLS / EXPERIENCE SECTION:
% MLOps / Production ML Deployment
\item Deployed ML pipeline to production using containerised Python services;
  monitored model drift with structured logging (applicable from thesis work).

% Cloud Platforms
\item Familiar with Azure cloud services (storage, compute) from Fraunhofer
  HPC projects; experienced with cloud-native data processing concepts.
```

### Claim a gap skill you actually have

```bash
python main.py remember --skill "MLOps" --status have_it
```

---

## Job Boards Coverage

| Category | Platforms |
|----------|-----------|
| **Major German** | StepStone, XING, Indeed.de, Monster.de, Jobware |
| **German Niche** | Heise Jobs (tech), Academics.de (research), Ingenieur.de, Absolventa (entry-level), Jobs.de, Karriere.at, EuroEngineerJobs |
| **Research & Academic** | EURAXESS (EU-wide, 43 countries), Fraunhofer (76 institutes), Helmholtz Association (18 centres), Zeit Jobs |
| **International** | LinkedIn, Glassdoor, ZipRecruiter (via JobSpy) |
| **Startup** | Wellfound (ex-AngelList, 130k+ startup jobs) |
| **Government** | Bundesagentur für Arbeit |

### Why research platforms are critical for technical profiles

- **EURAXESS**: EU Commission portal — PhD positions, postdocs, research engineers. Marie Skłodowska-Curie fellowships. 43 European countries.
- **Fraunhofer**: Germany's largest applied research org (76 institutes). Fraunhofer IEE, IEG, IOSB are directly relevant for energy + AI profiles. Working students, thesis students, engineers.
- **Helmholtz**: 18 centres. FZJ (energy/supercomputing), DLR (aerospace/energy), KIT (tech).
- **Zeit Jobs**: Die Zeit's board — strong for academic, research, and senior specialist roles.
- **Wellfound**: Shows salary and equity upfront. Strong EU/Berlin startup coverage (N26, Klarna, Personio, etc.).

---

## Complete Command Reference

```bash
# ── SETUP ──────────────────────────────────────────────────────────────────
python main.py upload-cv my_cv.pdf
python main.py profile --init                   # Create personal context template
python main.py profile --show                   # Preview what the AI will see
python main.py learn-style --dir "path/to/CLs"  # Learn writing style from existing CLs

# ── POSITION WORKFLOW ──────────────────────────────────────────────────────
python main.py suggest-positions --cv my_cv.pdf
# → edit output/suggested_positions.yaml (set approved: true/false)
python main.py scrape-from-suggestions
python main.py scrape-from-suggestions --suggestions custom_positions.yaml

# ── MANUAL SCRAPE ──────────────────────────────────────────────────────────
python main.py scrape -p "Data Engineer" -l Deutschland
python main.py scrape -p "Energy Data Scientist" -p "Grid AI" -l München -l Berlin
python main.py scrape -p "Werkstudent Python" --source fraunhofer --source euraxess
python main.py scrape -p "Research Engineer" --source euraxess --source helmholtz

# ── SCORING ────────────────────────────────────────────────────────────────
python main.py score                             # Score unscored jobs (LLM only)
python main.py score --memory                   # Score with adaptive memory adjustments
python main.py score --all                      # Rescore all jobs

# ── PER-JOB DEEP ANALYSIS ─────────────────────────────────────────────────
python main.py analyze-job --job-id <uuid>       # Full skills matrix + niche keywords
python main.py analyze-job --all --min-score 7.5 --limit 15  # Batch analysis
python main.py job-skills --job-id <uuid>        # View stored skills analysis
python main.py cover-letter --job-id <uuid>      # Generate tailored cover letter
python main.py cover-letter --job-id <uuid> --lang de --output cl.txt

# ── BROWSE RESULTS ─────────────────────────────────────────────────────────
python main.py list-jobs --min-score 7.5
python main.py list-jobs --min-score 7.0 --limit 50 --gaps
python main.py list-jobs --source fraunhofer --min-score 0
python main.py list-jobs --status queued

# ── MEMORY & LEARNING ──────────────────────────────────────────────────────
python main.py feedback --job-id <uuid> --decision apply --reason "..."
python main.py feedback --job-id <uuid> --decision skip
python main.py feedback --job-id <uuid> --decision interested --user-score 8.5
python main.py feedback --job-id <uuid> --decision blacklist_company
python main.py remember --skill "Apache Kafka" --status have_it
python main.py remember --skill "Azure" --status learning
python main.py remember --skill "React" --status not_interested
python main.py memory

# ── SKILL GAPS ─────────────────────────────────────────────────────────────
python main.py gaps --min-score 7.5
python main.py gaps --min-score 7.0 --limit 200
python main.py cv-suggestions --output overleaf.tex

# ── FULL PIPELINE ──────────────────────────────────────────────────────────
python main.py run --cv cv.pdf -p "Energy Data Scientist" -l Deutschland
python main.py run --cv cv.pdf -p "Data Engineer" --live   # actually apply

# ── API ────────────────────────────────────────────────────────────────────
python main.py api                               # Start FastAPI on :8000
python main.py api --port 8080
```

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `cv_profile` | Parsed CV (JSON fields for skills, education, experience, etc.) |
| `jobs` | All scraped jobs with score, status, match_reasons |
| `job_skills_matrix` | Per-job: required skills, user has/missing, niche keywords, ATS score |
| `cover_letters` | Generated cover letters per job |
| `cover_letter_style` | Learned writing style from existing cover letters |
| `user_memory` | RLHF state: claimed skills, preferences, preference embedding |
| `job_feedback` | User decisions (apply/skip/etc.) with embeddings for k-NN |
| `skill_gaps` | Aggregated missing skills across all jobs |
| `search_sessions` | Scraping run history |
| `documents` | Uploaded supporting documents |
| `applications` | Application tracking |
| `hr_contacts` | Found HR contacts per company |

---

## Troubleshooting

### `WinError 64: The specified network name is no longer available`

Use `127.0.0.1` instead of `localhost` in `.env`. On Windows, `localhost` resolves to IPv6 `::1`,
but Docker PostgreSQL only binds to IPv4.

### Playwright scrapers return no results

Some SPA job boards (Heise, StepStone, XING, Wellfound) require JavaScript rendering:
```bash
playwright install chromium
```
Set `HEADLESS_BROWSER=false` in `.env` to watch the browser for debugging.

### Cover letter style not being applied

Run `learn-style` first. Without it, the generator still works but uses generic style guidance.

### Gap analysis shows fragments like "mention of", "Unclear"

This was a known bug in older versions. Fixed: gaps now use LLM-based batch normalisation
instead of regex parsing. Run `python main.py gaps` again.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM | OpenAI API compatible (GPT-4, Claude, etc.) |
| Embeddings | sentence-transformers all-MiniLM-L6-v2 (384-dim) |
| Semantic search | pgvector (PostgreSQL extension) |
| Database | PostgreSQL 16 + pgvector |
| Async DB | SQLAlchemy 2.0 async + asyncpg + NullPool |
| Web scraping | httpx + BeautifulSoup + Playwright |
| Pipeline | LangGraph (7-node DAG) |
| CLI | Typer + Rich |
| API | FastAPI |
