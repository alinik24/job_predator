# JobPredator - AI-Powered Job Application Assistant

A practical, simple tool to manage your digital CV, apply cover letter rules, and automate job application form filling.

## 🎯 What This Does

1. **Digital CV Management**: Your CV stored as markdown - easy to read, update, and query
2. **Cover Letter Rules**: Master prompt with all your experience, projects, and tailoring logic
3. **Form Filling**: Automatically fill job application forms using your CV data
4. **Agents**: Python agents that use your CV + cover letter rules to help with applications

## 🚀 Quick Start

### 1. Setup

```powershell
# Clone and enter directory
cd C:\mydesktop\resproj_thesis\job_predator

# Install dependencies
pip install -r requirements.txt

# Start Docker services (PostgreSQL + pgvector)
docker-compose up -d

# Initialize database
python init_db.py
```

### 2. Update Your CV

Edit your digital CV:
```powershell
# Open in your editor
code profile/cv.md
```

The CV is in markdown format with YAML frontmatter. Update:
- Personal info (name, email, phone, location)
- Current role and employer
- Work experience
- Projects
- Skills
- Languages

### 3. Update Cover Letter Rules

Your cover letter master prompt is at:
```
cover_letter/Ali_Nazarikhah_Cover_Letter_Master_Prompt.md
```

This contains:
- Fixed paragraphs (education, closing)
- Project selection rules
- Skills by role type
- Tone and style guidelines
- Handling missing experience

Update this file to modify how cover letters are generated.

### 4. Fill Application Forms

**Option A: Let JobPredator open a browser**
```powershell
python main.py fill-form --url "https://jobs.company.com/apply/123"
```

**Option B: Use your existing Chrome browser (recommended)**

```powershell
# Start Chrome with debugging
.\start_chrome_debug.bat

# Navigate to the application page in Chrome
# Then run:
python main.py fill-form --url "https://..." --use-existing-browser
```

See `FORM_FILLER_GUIDE.md` for detailed instructions.

### 5. Generate Application Materials

```powershell
# Generate cover letter + skills analysis for a job
python main.py apply --job-url "https://jobs.company.com/posting/123"
```

---

## 📁 Project Structure

```
job_predator/
├── profile/                    # YOUR DATA (update these!)
│   ├── cv.md                  # Your digital CV (markdown + YAML)
│   ├── cv_reader.py           # CV parser (don't edit)
│   └── cover_letter_rules.py  # Rules loader (don't edit)
│
├── cover_letter/               # Cover letter rules
│   └── Ali_Nazarikhah_Cover_Letter_Master_Prompt.md
│
├── agents/                     # Application agents
│   ├── form_filler_agent.py   # Form filling automation
│   ├── job_application_agent.py # Application package generator
│   └── profile_builder_agent.py # (legacy, being refactored)
│
├── core/                       # Core infrastructure
│   ├── config.py              # Configuration
│   ├── database.py            # Database connection
│   └── models.py              # Database models
│
├── cv/                         # CV utilities
│   ├── cv_parser.py           # (legacy PDF parsing)
│   └── cover_letter_learner.py
│
├── main.py                     # CLI entry point
├── docker-compose.yml          # PostgreSQL + Neo4j
├── init_db.py                  # Database initialization
└── requirements.txt            # Python dependencies
```

---

## 🛠️ Key Commands

### CV Management

```powershell
# View your CV sections
python -c "from profile.cv_reader import get_cv; cv = get_cv(); print(cv.full_name, cv.current_title)"

# Search your CV
python -c "from profile.cv_reader import search_cv; results = search_cv('machine learning'); print(results[:3])"

# Get your skills
python -c "from profile.cv_reader import get_cv_skills; print(get_cv_skills()[:10])"
```

### Cover Letter Rules

```powershell
# View master prompt
python -c "from profile.cover_letter_rules import get_master_prompt; print(get_master_prompt()[:500])"

# Get fixed education paragraph
python -c "from profile.cover_letter_rules import get_fixed_education; print(get_fixed_education())"

# Get project rules
python -c "from profile.cover_letter_rules import get_project_selection_rules; print(list(get_project_selection_rules().keys()))"
```

### Form Filling

```powershell
# Fill form in new browser
python main.py fill-form --url "https://..."

# Fill form in your Chrome
.\start_chrome_debug.bat
python main.py fill-form --url "..." --use-existing-browser

# Fill and auto-submit (careful!)
python main.py fill-form --url "..." --use-existing-browser --submit
```

### Database

```powershell
# Start database
docker-compose up -d

# Stop database
docker-compose down

# Access database UI
# http://localhost:8080 (Adminer)
# Server: postgres
# Username: postgres
# Password: postgres
# Database: job_predator
```

---

## 📖 Documentation

- **FORM_FILLER_GUIDE.md** - Detailed form filling instructions
- **ARCHITECTURE.md** - System architecture and design
- **DEVELOPMENT.md** - Development workflow and guidelines

---

## 🔧 Configuration

Create or edit `.env` file:

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/job_predator

# OpenAI/Azure (for AI features)
LLM_API_BASE_URL=https://your-azure-endpoint.openai.azure.com/
LLM_API_KEY=your-api-key
LLM_MODEL_NAME=gpt-5-chat
LLM_API_VERSION=2024-08-01-preview

# Neo4j (optional)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=jobpredator123
```

---

## 🎓 How It Works

### 1. Digital CV (Markdown)

Your CV is stored as `profile/cv.md`:
- **Human-readable**: Edit in any text editor
- **Version-controlled**: Track changes with git
- **Queryable**: Agents can search and extract data
- **Structured**: YAML frontmatter + markdown sections

### 2. Cover Letter Master Prompt

The file `cover_letter/Ali_Nazarikhah_Cover_Letter_Master_Prompt.md` contains:
- Fixed paragraphs that appear in every letter
- Project descriptions and when to use them
- Skills lists by role type
- Rules for tone, structure, and handling missing experience

This is the **source of truth** for all cover letter generation.

### 3. Agents

Python agents that:
- Read your CV using `profile/cv_reader.py`
- Apply cover letter rules using `profile/cover_letter_rules.py`
- Fill forms automatically using Playwright
- Generate tailored cover letters
- Create application packages

---

## 🐛 Troubleshooting

### Database connection error

```powershell
# Check Docker is running
docker ps

# If postgres is not running
docker-compose up -d

# Recreate database
docker-compose down -v
docker-compose up -d
python init_db.py
```

### Form filling not working

```powershell
# Check Chrome debugging is enabled
.\start_chrome_debug.bat

# Check endpoint
curl http://127.0.0.1:9222/json/version

# If port is blocked, try different port
chrome.exe --remote-debugging-port=9223
python main.py fill-form --url "..." --use-existing-browser --cdp-url "http://127.0.0.1:9223"
```

### CV not loading

```powershell
# Check CV file exists
ls profile/cv.md

# Test CV reader
python -c "from profile.cv_reader import get_cv; print(get_cv().full_name)"
```

---

## 🚧 Upcoming Features

- [ ] OpenWebUI integration for chat interface
- [ ] Job scraping from multiple sources
- [ ] Automatic job matching and scoring
- [ ] Email outreach automation
- [ ] Application tracking dashboard

---

## 📄 License

MIT License - See LICENSE file

---

## 🤝 Contributing

This is a personal tool, but feel free to fork and adapt for your own use.

---

**Last Updated**: April 27, 2026
