# Cover Letter PDF Generator with Comprehensive CV Knowledge Base

**Date:** 2026-04-27
**Author:** Ali Nazarikhah
**Status:** Design Approved

---

## 1. Executive Summary

This document specifies the design for an intelligent cover letter generation system that:

- Analyzes job descriptions and matches them against a comprehensive CV knowledge base
- Selects relevant PROJECTS, EXPERIENCE,SKILLS,education,  research interests.
- Generates a human-editable markdown template for review
- Converts the approved template to HTML and then to PDF with exact design fidelity
- Maintains a learning knowledge base that improves with each application

The system replaces manual cover letter tailoring with an intelligent, guided workflow while preserving complete user control and exact visual design specifications.

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌─────────────────┐     ┌──────────────────┐
│ Job Description │     │  Tailored CV     │
│    (text/file)  │     │   (markdown)     │
└────────┬────────┘     └────────┬─────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │  generator.py         │
         │  - Load & parse       │
         │  - Match using KB     │
         │  - Select CV sections │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │ kb_mappings.yaml      │
         │ - Semantic categories │
         │ - Project mappings    │
         │ - Skills hierarchy    │
         │ - Historical examples │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │ Editable Markdown     │
         │ temp/job_draft.md     │
         │ [USER EDITS HERE]     │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │ HTML Rendering        │
         │ - Jinja2 template     │
         │ - index.html + CSS    │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │ HTML Preview          │
         │ temp/job_preview.html │
         │ [USER REVIEWS]        │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │ Playwright PDF Gen    │
         │ - A4 format           │
         │ - Exact design specs  │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │ Final PDF Output      │
         │ Ali_Nazarikhah_...pdf │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │ Optional KB Update    │
         │ Master_Prompt.md      │
         └───────────────────────┘
```

### 2.2 Directory Structure

```
job_predator/
├── cover_letter/
│   ├── generator.py                    # Main generator script
│   ├── kb_mappings.yaml               # Knowledge base
│   ├── templates/
│   │   ├── index.html                 # HTML template (Jinja2)
│   │   ├── style.css                  # Design stylesheet
│   │   └── editable_template.md      # Markdown template scaffold
│   ├── asset/
│   │   ├── signature.png             # Digital signature
│   │   ├── photo_2026-02-01_17-02-14.jpg  # Profile photo
│   │   ├── email.png                 # Contact icons
│   │   ├── phone-call.png
│   │   ├── linkedin.png
│   │   └── simple black minimalist office desk setup.jpg  # Header bg
│   ├── temp/                          # Generated templates
│   │   ├── job_YYYY-MM-DD_HHMM_draft.md
│   │   └── job_YYYY-MM-DD_HHMM_preview.html
│   ├── output/                        # Final PDFs
│   │   └── Ali_Nazarikhah_Cover_Letter_[Position].pdf
│   └── Ali_Nazarikhah_Cover_Letter_Master_Prompt.md
├── cv/
│   ├── cv.md                          # Full CV (source)
│   └── cv_tailored_[position].md     # Tailored versions
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-04-27-cover-letter-pdf-generator-design.md
```

---

## 3. Knowledge Base Design

### 3.1 KB Structure (`kb_mappings.yaml`)

The knowledge base is organized into **position categories**, each containing:

1. **Keywords**: Primary and secondary keywords for job matching
2. **Projects**: Prioritized project selections with context
3. **Research Interests**: Relevant interests from CV
4. **Skills**: Hierarchical skill selections (primary/secondary)
5. **Experience**: Relevant roles with emphasis points
6. **Education**: What aspects to emphasize
7. **Additional Content**: Special paragraphs or acknowledgments
8. **Avoidance Rules**: What to exclude
9. **Historical Examples**: Past successful applications

### 3.2 Sample KB Categories

The system will support these initial position categories:

- AI/ML/GenAI
- FinTech/Finance/Market Analysis
- Energy Systems/Renewable Energy/Sustainability
- Manufacturing/Production Systems/Industry 4.0
- Data Science/Empirical Research
- HCI/UX/Cognitive Science
- Software Engineering (can be added)
- Robotics/Control Systems (can be added)

### 3.3 KB Matching Algorithm

**Keyword-based scoring:**

1. Extract keywords from job description (lowercased, stemmed)
2. For each category: score primary keywords (weight: 3) and secondary keywords (weight: 1)
3. Return category with highest score
4. If score < threshold, prompt user to select manually

---

## 4. Generator Workflow

### 4.1 Complete User Flow

```
1. User provides: job description file + tailored CV
2. System loads and parses both inputs
3. System analyzes job description (position, institution, keywords)
4. System matches job to position category from KB
5. System selects relevant CV sections (projects, skills, interests, etc.)
6. System generates editable markdown template
7. User edits markdown template
8. User approves edited template
9. System renders HTML from template
10. System shows HTML preview in browser
11. User approves HTML preview
12. System generates PDF via Playwright
13. System optionally updates master prompt KB
14. Complete!
```

### 4.2 Key Design Decisions

**Why editable markdown first?**

- Human-readable format
- Easy to modify without HTML knowledge
- Clear section markers ([FIXED], [GENERATED])
- User maintains full control

**Why HTML preview before PDF?**

- Visual verification before final generation
- Catch formatting issues early
- Browser-accurate rendering preview

**Why Playwright over other PDF generators?**

- Perfect CSS rendering (matches browser exactly)
- Handles web fonts, images, backgrounds correctly
- Maintains exact spacing, borders, colors
- Industry-standard tool

---

## 5. Design Specifications

### 5.1 PDF Visual Design (Exact Preservation)

**Page:**

- Size: A4 (210mm × 297mm)
- Margins: 0 (handled internally by CSS)

**Typography:**

- Primary font: Georgia, "Times New Roman", serif
- Body font size: 9.3pt
- Line height: 1.42 (approximately 13.2pt)
- Paragraph spacing: 4mm bottom margin (exactly half of ~8mm font height)

**Colors:**

- Body text: `#1f252c` (dark blue-gray)
- Sidebar text: `#303a45` (slightly lighter)
- Background: `white`
- Header overlay: text shadow with `rgba(0,0,0,0.7)`

**Layout:**

- Two-column grid: `48mm sidebar | 5mm gap | remainder for letter`
- Hero header height: `39mm`
- Content padding: `4mm 6mm 8mm 3mm`

**Borders:**

- Recipient box border: `1.2mm solid #303a45`
- Border radius: `8mm`

**Components:**

- Profile photo: `29mm × 29mm` circle, grayscale filter
- Signature: `30mm` width
- Hero background: full-width cover
- Contact icons: inline with text

### 5.2 Editable Template Format

**Structure:**

```markdown
# Cover Letter Draft - [Position]

## INSTRUCTIONS
- Edit any section below
- Sections marked [FIXED] come from master prompt
- Sections marked [GENERATED] are auto-selected
- Save when done

---

## Recipient Information
**To:**
[Name, Title]
[Institution]
[Address lines]

**Date:** YYYY-MM-DD

---

## Subject Line
Application for [Position] ([Reference])

---

## Greeting
Dear [Name],

---

## Opening Paragraph [GENERATED]
[Auto-generated opening based on job analysis]

---

## Education Paragraph [FIXED]
[Fixed paragraph from master prompt]

---

## Experience Paragraph [GENERATED]
### Selected Projects:
- **Project 1**: Reason
- **Project 2**: Reason

### Relevant Skills:
Primary: [list]
Secondary: [list]

### Research Interests:
- Interest 1
- Interest 2

**Draft paragraph:**
[Auto-generated paragraph]

---

## Motivation Paragraph [GENERATED]
[Auto-generated based on position category]

---

## Closing Paragraph [FIXED]
[Fixed paragraph from master prompt]

---

## Signature
Sincerely,
Ali Nazarikhah

---

## Metadata
- Category: [...]
- Date: YYYY-MM-DD
```

---

## 6. Implementation Components

### 6.1 Core Modules

**generator.py** - Main orchestrator

- CLI argument parsing
- User interaction flow
- Module coordination

**cv_parser.py** - CV parsing

- Extract education, projects, skills, experience, honors
- Return structured data

**job_analyzer.py** - Job description analysis

- Extract position, institution, keywords
- Parse requirements

**kb_loader.py** - Knowledge base management

- Load and validate YAML
- Provide query interface

**matcher.py** - CV-to-job matching

- Category detection
- Section selection
- Confidence scoring

**template_generator.py** - Template generation

- Create editable markdown
- Format selected sections

**template_parser.py** - Template parsing

- Parse user-edited markdown
- Extract structured data

**html_renderer.py** - HTML generation

- Jinja2 templating
- Design preservation

**pdf_generator.py** - PDF creation

- Playwright integration
- A4 format, exact specs

**kb_updater.py** - Master prompt updates

- Append successful mappings
- Historical tracking

### 6.2 Data Structures

**CVData:**

```python
{
    'education': [{'degree': '...', 'gpa': '...', 'thesis': '...'}],
    'research_interests': {'EE': [...], 'EiCS': [...]},
    'experience': [{'role': '...', 'organization': '...', 'description': '...'}],
    'projects': {'EE': [...], 'EiCS': [...], 'CE': [...]},
    'skills': {'AI_ML': [...], 'Data_Science': [...], 'EE_CE': [...]},
    'honors': [{'name': '...', 'organization': '...'}],
    'languages': [{'language': '...', 'level': '...'}],
    'contact': {'name': '...', 'email': '...', 'phone': '...'}
}
```

**JobAnalysis:**

```python
{
    'position': 'Research Assistant - FinTech',
    'institution': 'Ludwig-Maximilians-Universität München',
    'reference': 'V-146-26',
    'keywords': ['FinTech', 'financial data', 'empirical research'],
    'requirements': {
        'must_have': [...],
        'nice_to_have': [...]
    },
    'recipient': {
        'name': 'Professor Riordan',
        'title': 'Institute Director',
        'address': [...]
    }
}
```

**MatchedData:**

```python
{
    'category': 'FinTech/Finance',
    'confidence': 0.87,
    'projects': [
        {'name': 'Personalized Deep-Research', 'reason': '...', 'context': '...'},
        {'name': 'FORVIA HELLA', 'reason': '...', 'context': '...'}
    ],
    'skills': {
        'primary': ['Python', 'R', 'SQL', 'BigQuery'],
        'secondary': ['Polars', 'PySpark']
    },
    'research_interests': ['Data-Driven Decision-Making'],
    'experience': [
        {'role': '...', 'emphasize': [...]}
    ],
    'education_emphasis': {'dual_programs': True, 'interdisciplinary': True},
    'honors': [{'name': '...', 'reason': '...'}],
    'additional_paragraphs': [
        {'type': 'acknowledgment', 'content': '...'},
        {'type': 'motivation', 'content': '...'}
    ]
}
```

---

## 7. Error Handling

### 7.1 Input Validation

- **Missing job file**: Clear error with expected path
- **Missing CV file**: Clear error with expected path
- **Invalid job description**: Minimum length check, keyword presence validation
- **Invalid CV format**: Section header validation

### 7.2 Matching Issues

- **No category match**: Prompt user to select from available categories
- **Low confidence (<50%)**: Warn user, show alternatives
- **Missing CV sections**: Use fallbacks, warn user

### 7.3 Generation Errors

- **Template rendering failure**: Show Jinja2 error with line number
- **HTML parsing error**: Show parsing issue with context
- **PDF generation failure**: Fallback to WeasyPrint, then error

### 7.4 File System Issues

- **Missing asset files**: Check and report missing images/fonts
- **Permission errors**: Clear instructions to fix permissions
- **Disk space**: Check before PDF generation

---

## 8. Testing Strategy

### 8.1 Unit Tests

- CV parsing accuracy
- Job analysis keyword extraction
- KB category matching
- Template generation structure
- Template parsing correctness

### 8.2 Integration Tests

- End-to-end for each category (AI/ML, FinTech, Energy, etc.)
- User input simulation
- File generation verification

### 8.3 Visual Regression Tests

- PDF design fidelity (fonts, spacing, colors, borders)
- Comparison with reference PDFs
- A4 size verification

---

## 9. Dependencies

```txt
pyyaml>=6.0
jinja2>=3.1.0
playwright>=1.40.0
python-dateutil>=2.8.0
```

**Installation:**

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## 10. Success Criteria

### 10.1 Functional

✅ CV parsing extracts all sections correctly
✅ KB matching achieves >80% accuracy
✅ Template generation includes all required sections
✅ User can edit markdown template
✅ HTML preview matches design exactly
✅ PDF output is pixel-perfect
✅ Master prompt updates correctly

### 10.2 Design Preservation

✅ Font: Georgia, 9.3pt, line-height 1.42
✅ Paragraph spacing: exactly 4mm
✅ Colors: #1f252c (body), #303a45 (sidebar)
✅ Border: 1.2mm solid #303a45, radius 8mm
✅ Layout: 48mm sidebar + content
✅ A4 page size (210mm × 297mm)
✅ Visual fidelity >98%

### 10.3 Performance

✅ Generation time < 10 seconds
✅ PDF file size < 500KB
✅ Works offline (after Playwright install)

---

## 11. Future Enhancements

### 11.1 Phase 2 (Optional)

- LLM integration for semantic analysis
- Multi-language support (German, Italian)
- Email generation from templates
- Form filling automation
- Application tracking and analytics
- Web interface for non-technical users

### 11.2 KB Learning

- Track application outcomes
- Adjust confidence scores over time
- Store negative examples (unsuccessful applications)
- Dynamic keyword extraction with NLP

---

## 12. Conclusion

This design provides a complete, integrated system for intelligent cover letter generation that:

1. **Analyzes comprehensively**: All CV sections, not just projects
2. **Matches intelligently**: Semantic KB with historical learning
3. **Maintains control**: Editable templates for user review
4. **Preserves design**: Exact visual specifications in PDF
5. **Learns continuously**: Updates KB with successful mappings

The two-stage editing workflow (markdown → HTML → PDF) ensures users maintain full control while benefiting from intelligent assistance. The system balances automation with human oversight, producing high-quality, tailored cover letters efficiently.

**Key Innovations:**

- Comprehensive CV section analysis
- Human-readable editable templates
- Semantic category matching with confidence scoring
- Historical learning from past applications
- Exact design preservation via Playwright

**Implementation Priority:**

1. Core generator and CV parsing
2. KB matching and template generation
3. HTML rendering and PDF pipeline
4. Testing and validation
5. Documentation and polish
