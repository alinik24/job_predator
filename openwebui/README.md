## Open WebUI Integration - Job Application Assistant

Complete RAG-powered chatbot integration for answering job application questions using your career documents.

## Features

🤖 **Hybrid RAG Retrieval**
- Combines Sismics (full-text) + Vector (semantic) + Knowledge Graph (entities)
- Reciprocal Rank Fusion (RRF) for optimal results
- Configurable weights per source

💬 **Application Q&A**
- Answer job application questions automatically
- Context-aware responses based on job title and company
- Supports all field types (text, yes/no, select, number)

🔍 **Document Search**
- Search through all your career documents
- Semantic similarity matching
- Source attribution (know where info comes from)

📊 **Profile Management**
- Extract complete profile from knowledge graph
- Skills, experience, education overview
- Always up-to-date from your documents

---

## Quick Start

### Option 1: Open WebUI Pipeline (Recommended)

1. **Ensure services are running:**
   ```bash
   docker-compose -f docker-compose.ingestion.yml up -d
   ```

2. **Install pipeline in Open WebUI:**
   - Open WebUI → Settings → Pipelines
   - Click "Add Pipeline"
   - Upload `openwebui/pipeline.py`
   - Or paste URL: `https://raw.githubusercontent.com/your-repo/pipeline.py`

3. **Configure valves:**
   - Set Sismics URL, username, password
   - Set Neo4j connection details
   - Adjust retrieval weights if needed

4. **Use in chat:**
   ```
   User: What are my Python skills?
   Assistant: [Based on your documents] You have experience with Python 3.x, 
              including frameworks like Django, Flask, and FastAPI. You've worked 
              on machine learning projects using scikit-learn and TensorFlow...
   ```

### Option 2: Standalone Functions

1. **Install functions:**
   - Open WebUI → Workspace → Functions
   - Import `openwebui/functions.py`

2. **Use via function calling:**
   ```
   User: Answer this question: What is your expected salary?
   Assistant: [Calls answer_application_question function]
              Based on your experience and location, competitive salary 
              in the range of €65,000 - €80,000 annually.
   ```

---

## Architecture

```
Open WebUI Chat
    ↓
Pipeline / Functions
    ↓
Hybrid RAG System
    ↓
┌──────────┬──────────────┬──────────────┐
│ Sismics  │ Vector Store │ Graph (Neo4j)│
│ Full-text│ Semantic     │ Entities     │
└──────────┴──────────────┴──────────────┘
    ↓           ↓              ↓
    └───────────┴──────────────┘
            RRF Fusion
                ↓
        Ranked Results
                ↓
        LLM Generation
                ↓
        User Answer
```

---

## Components

### 1. `hybrid_rag.py` - Hybrid Retrieval

**Core RAG system** combining three retrieval methods:

```python
from openwebui.hybrid_rag import HybridRAG

rag = HybridRAG()
await rag.initialize()

# Retrieve relevant documents
results = await rag.retrieve("What Python projects did I work on?", top_k=5)

# Get formatted context
context = await rag.get_context("Python experience", top_k=5, max_chars=4000)
```

**Features:**
- ✅ Sismics full-text search (keyword matching)
- ✅ Vector semantic search (embeddings)
- ✅ Knowledge graph queries (entity relationships)
- ✅ RRF fusion ranking
- ✅ Configurable weights per source

**Configuration:**
```python
rag = HybridRAG(
    use_sismics=True,
    sismics_url="http://localhost:8080",
    vector_db_dir="vector_db",
    neo4j_uri="bolt://localhost:7687",
    # Adjust weights (sum should be ~1.0)
    sismics_weight=0.3,  # 30% weight for keyword matching
    vector_weight=0.4,   # 40% weight for semantic similarity
    graph_weight=0.3     # 30% weight for entity relationships
)
```

---

### 2. `application_qa.py` - Question Answering

**Intelligent Q&A system** for job applications:

```python
from openwebui.application_qa import ApplicationQA

qa = ApplicationQA()
await qa.initialize()

# Answer a question
answer = await qa.answer(
    question="What is your Python experience?",
    job_title="Python Developer",
    company="Google"
)
# Returns: "I have 5+ years of Python development experience..."
```

**Smart question type detection:**
- Salary questions → retrieves compensation info from CV
- Yes/no questions → returns "Yes" or "No" only
- Experience questions → emphasizes work history
- Skills questions → focuses on technical abilities
- Education questions → queries knowledge graph for degrees

**Batch processing:**
```python
questions = [
    {"question": "What is your Python experience?", "field_type": "textarea"},
    {"question": "Do you have work authorization?", "field_type": "boolean"},
    {"question": "Expected salary?", "field_type": "number"}
]

answers = await qa.batch_answer(questions, job_title="Developer", company="Google")
# Returns dict: {"What is your Python...": "I have...", ...}
```

---

### 3. `pipeline.py` - Open WebUI Integration

**Complete Open WebUI pipeline** with two modes:

**Mode 1: Q&A**
```
User: Help me answer: Why do you want to work at Google?
Assistant: [Uses hybrid RAG + LLM]
           I am particularly interested in Google because of their leadership 
           in AI and machine learning, which aligns with my background in...
```

**Mode 2: Search**
```
Model selection: "Document Search"
User: Find my machine learning projects
Assistant: Found 5 results:
           1. 📄 CV.pdf - Developed ML models for...
           2. 🔍 Cover Letter Google - Applied machine learning to...
           ...
```

**Configuration (Valves):**

In Open WebUI settings, configure:
```
USE_SISMICS: true
SISMICS_URL: http://localhost:8080
SISMICS_USERNAME: admin
SISMICS_PASSWORD: admin

VECTOR_DB_DIR: vector_db

NEO4J_URI: bolt://localhost:7687
NEO4J_USER: neo4j
NEO4J_PASSWORD: jobpredator123

TOP_K: 5
MAX_CONTEXT_CHARS: 4000
TEMPERATURE: 0.2
```

---

### 4. `functions.py` - Callable Tools

**Open WebUI functions** that can be called from chat:

#### `answer_application_question()`
```python
# Called automatically when user asks
User: "Answer this: What is your availability?"
→ Function: answer_application_question(question="What is your availability?")
→ Returns: "Available to start immediately"
```

#### `search_my_documents()`
```python
User: "Search my documents for Python"
→ Function: search_my_documents(query="Python", top_k=5)
→ Returns: Formatted search results with sources
```

#### `get_my_profile()`
```python
User: "Show me my profile"
→ Function: get_my_profile()
→ Returns: Complete profile from knowledge graph
```

#### `get_my_skills()`
```python
User: "What are my programming skills?"
→ Function: get_my_skills(category="programming")
→ Returns: List of programming skills from graph
```

---

## Usage Examples

### Example 1: Answer Application Question

**Chat:**
```
User: I'm applying for a Python Developer role at Google. 
      Help me answer: "What is your Python experience?"