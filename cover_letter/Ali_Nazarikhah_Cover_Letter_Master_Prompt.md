# Ali Nazarikhah — Reusable Cover Letter Tailoring Prompt

Use this prompt whenever you want to generate a tailored cover letter, application email, file names, and form answers for a job, PhD position, research role, HiWi role, or industry position.

---

## Master Prompt

```text
You are helping me tailor application materials for a specific position.

I will paste a job description. Before writing anything, carefully analyze the job description and map it to my CV, projects, experience, thesis, skills, and application rules below.

Your task is to produce:
1. A tailored cover letter.
2. A ready-to-send email, if an email address is available or if the job asks for email submission.
3. A proper PDF file name for the cover letter and/or full application package.
4. If the application form asks questions, provide concise, ready-to-paste answers.
5. A short note explaining which parts of my profile you used and why.

Do not use generic wording. Do not include irrelevant experience. Do not overclaim.

---

# 1. My Fixed Cover Letter Rules

## Address format
Use the correct recipient and institutional address.

If a professor or named contact person is given, include that person in the address and greeting.

Address format must be comma-separated like this:

[Recipient Name and Title], [Group/Chair/Department], [Institute], [Faculty if available], [University/Organization], [Street and Number if available], [Postal Code City], [Country]

Example:
Prof. Dr. Gitta Kutyniok, Chair of Mathematical Foundations of Artificial Intelligence, Faculty of Mathematics, Informatics and Statistics, Ludwig-Maximilians-Universität München, Geschwister-Scholl-Platz 1, 80539 München, Germany

If no person is given, use the institution/department address only and use:
Dear Hiring Committee,

Never use “Admissions Committee” for jobs. Use “Admissions Committee” only for study program applications.

---

## Subject line
Always include a clear subject line.

Format:
Application for [Exact Position Title] ([Reference Number])

If there is no reference number, omit it.

---

## Opening paragraph
Do not start with:
“I am writing to express my interest...”

Instead, start directly and confidently with why the role aligns with my background and the core requirements.

Example style:
The [position title] strongly aligns with my background in [relevant areas], particularly where [job-specific topic] intersects with [my relevant experience].

---

## Fixed education paragraph
Include this paragraph exactly as written in every cover letter. Do not modify it:

I completed my Master’s degree in Energy Engineering at Sapienza University of Rome with highest distinction (110/110), while simultaneously pursuing a second Master’s degree in Computer Engineering at Sapienza University and Paderborn University through a selective dual-track program for top-performing students. Managing both programs in parallel within the standard timeframe strengthened my ability to approach complex technical systems analytically and to combine engineering system understanding with computational modelling and data-driven methods.

---

## Fixed closing paragraph
Include this closing section exactly as written in every cover letter:

Given the inherent limitations of a cover letter, I understand that certain aspects of my profile may require further clarification. Please feel free to contact me if you need any additional information. I look forward to your feedback and the opportunity to further discuss my application.

Thank you for your time and consideration.

---

# 2. Core Tailoring Logic

For every application:

1. Read the job description carefully.
2. Identify the main domain:
   - AI / ML / GenAI
   - Data science / empirical research
   - Energy systems / thermodynamics / process engineering
   - Manufacturing / production systems
   - Robotics / control / optimization
   - Finance / FinTech / market data
   - Cognitive science / behavioral modeling
   - Software / automation / digitalization
   - Teaching / student support
3. Select only the relevant experience from my CV.
4. Do not mention projects that are not directly useful for the role.
5. If I lack direct experience in one requirement, acknowledge it briefly and compensate with related background, fast learning, and transferable experience.
6. If the job has industry, transfer, startup, product, or real-world implementation potential, include my interest in real-world impact and startup/industry translation.

---

# 3. My Profile Summary

## Education
- M.Sc. Energy Engineering, Sapienza University of Rome, 110/110, highest distinction.
- Second M.Sc. Engineering in Computer Science, Sapienza University of Rome / Paderborn University, coursework completed, thesis pending.
- B.Sc. Chemical Engineering, Sahand University of Technology.

## Energy Engineering thesis
Use this only when relevant to energy, process engineering, manufacturing, industrial systems, optimization, thermodynamics, or physical system modeling:

Energy Demand Modeling of Industrial Furnaces for Energy Efficiency Assessment; Specification and Validation in a Roller Hearth Furnace.

## Current role
Research Assistant, GenAI Incubator, Fraunhofer IEM.
Relevant wording depending on job:
- For AI/ML roles: generative AI, ML-driven solutions, Python, PyTorch, data-driven modeling, decision-support systems.
- For industry roles: automation, operational efficiency, system integration, data pipelines.
- For research roles: modeling pipelines, computational methods, structured data, applied ML.
- For startup/transfer roles: real-world implementation, industrial transfer, scalable solutions.

---

# 4. Project Selection Rules

Only use projects that match the job.

## Benteler project
Digital Project Management Transformation at Benteler.
Use for:
- Data structuring
- RAG systems
- Digital transformation
- Knowledge base design
- Project knowledge retrieval
- Enterprise data workflows

Recommended wording:
In the Benteler project on Digital Project Management Transformation, I worked on legacy Excel digitalization, structured data modeling, centralized project knowledge base creation, and RAG-based information retrieval design.

---

## FORVIA HELLA project
Predictive Quality Modeling for SMT Production.
Use for:
- Machine learning
- Predictive quality
- Manufacturing data
- Semiconductor/electronics-adjacent roles
- Explainable AI
- Defect detection
- Industrial AI
- Empirical ML/data science roles

Recommended wording:
In the FORVIA HELLA project on Predictive Quality Modeling for SMT Production, I worked on developing a machine learning pipeline for early defect detection in PCB manufacturing using supervised learning and explainable AI to classify product quality and support interpretable decision-making.

---

## HIK project
Electrical Schema Digitalization for Industrial Automation.
Use only for:
- Automation
- Electrical systems
- Industrial digitalization
- System integration
- Engineering data representation
- Machine-readable schemas

Recommended wording:
In the HIK project on Electrical Schema Digitalization for Industrial Automation, I worked on converting electrical schematics into structured, machine-readable schemas to support automation, interoperability, and downstream engineering integration.

Do not use HIK for finance or psychology unless no better project exists.

---

## Battery Cell Production project
Machine Parameter Identification and Data Mapping in Battery Cell Production.
Use for:
- Production systems
- Manufacturing
- Battery research
- Industrial process data
- Parameter mapping
- Data consistency
- Scalable workflows

Recommended wording:
In the project on Machine Parameter Identification and Data Mapping in Battery Cell Production, I focused on structuring, optimization, and consistency analysis of machine parameters to support scalable digital production workflows.

---

## Physiognomy / HCI project
Physiognomy-Based Personality Analysis Application and HCI report.
Use for:
- Human-computer interaction
- Cognitive science
- Behavioral modeling
- User studies
- Psychology-related AI
- Experimental design
- ANOVA/statistical evaluation
- UX, decision-making, interaction analysis

Recommended wording:
In a Human-Computer Interaction project centered on a physiognomy-based personality analysis application, I worked on requirements analysis, user profiling, task modeling, usability evaluation, think-aloud studies, and a controlled experiment using ANOVA to assess user interaction and decision-making patterns.

---

## Personalized Deep-Research Platform
Use for:
- Research systems
- Market analysis
- Data-driven decision support
- FinTech/strategy/research roles
- Information retrieval

Recommended wording:
In the Personalized Deep-Research Platform for Idea Scouting project, I worked on a data-driven research system for personalized information retrieval, structured market analysis, and early-stage idea evaluation.

---

## Senior+ AI-driven HR Platform
Use for:
- HR tech
- Knowledge retention
- Onboarding
- Personalized systems
- Human-centered AI

---

## Energy / Engineering projects
Use selectively:
- Solar-powered hybrid RO-MED desalination: renewable energy, techno-economic assessment.
- Wind turbine CFD with Python/OpenFOAM: simulation, CFD, numerical modeling.
- Hybrid renewable microgrid in Namibia: resilience, HOMER, uncertainty.
- Energy audit at Campus X: real-time performance analysis.
- DüsselPulse: AI-driven smart city solutions, uncertainty quantification, data-driven decision-making.
- SOEC heat recovery: hydrogen, techno-economic analysis.
- Flare gas recovery and process simulation: process optimization, Aspen HYSYS.

---

# 5. Skills to Use by Job Type

## AI / ML / GenAI roles
Mention only if relevant:
- Python
- PyTorch
- TensorFlow
- Hugging Face
- LangChain
- RAG
- diffusion models
- LLMs
- fine-tuning / quantization
- MLflow / W&B
- Docker/Kubernetes
- SQL / PySpark / Polars

## Data science / empirical research roles
Mention:
- Python
- R
- SQL including BigQuery
- Polars / PySpark
- statistical analysis
- structured datasets
- experimental design if applicable

## Energy / process roles
Mention:
- thermodynamics
- energy demand modeling
- efficiency assessment
- renewable integration
- Python, MATLAB
- OpenFOAM, COMSOL, Aspen HYSYS, HOMER, PVsyst, RETScreen

## Manufacturing / production roles
Mention:
- industrial process modeling
- battery cell production data mapping
- predictive quality modeling
- parameter consistency analysis
- structured production workflows
- Python, data pipelines

## Software / automation roles
Mention:
- Python
- Linux if present in CV or known from experience
- SQL
- FastAPI
- Docker/Kubernetes
- workflow automation
- structured data modeling
- system integration
- legacy data transformation

## Finance / FinTech roles
Mention:
- empirical data analysis
- Python/R/SQL
- financial systems as complex data-rich environments
- structured market analysis project
- machine learning and decision-making
- do not overclaim finance experience if not directly in CV

## Cognitive / behavioral modeling roles
Mention:
- HCI project
- user studies
- think-aloud evaluation
- controlled experiment
- ANOVA
- Yale Introduction to Psychology course if relevant
- cognition, perception, decision-making
- AI/statistics/computational modeling

---

# 6. Handling Missing Experience

If I do not have direct experience in a required area, do not hide it and do not overclaim.
Use this pattern:

While I have not yet worked directly on [specific missing area], my background in [closest relevant experience] has provided me with transferable skills in [skill 1], [skill 2], and [skill 3]. I am highly motivated and able to quickly acquire the domain-specific knowledge required for this role.

Examples:
- No radar testbeds: mention Python, system modeling, data-driven systems, fast learning, willingness to learn lab equipment.
- No semiconductor process experience: mention industrial process modeling, predictive quality modeling, production data, fast learning.
- No pure finance background: mention empirical data, ML, structured market analysis, interest in financial systems as data-rich environments.
- No pure mathematics background: mention technical modeling, ML, programming, motivation to deepen theoretical foundations.

---

# 7. Industry / Startup / Real-World Impact Paragraph

Include this idea when the job involves applied research, technology transfer, industrial collaboration, product development, startup ecosystem, or innovation.

Use a natural version such as:

Through my interdisciplinary background, I have developed strong analytical thinking skills and the ability to approach problems from both theoretical and practical perspectives. I am highly motivated to work in environments where research and technical development can translate into real-world applications, industrial impact, or startup-oriented innovation.

For academic roles, make it softer:

I am especially motivated by research environments where scientific advances can later translate into real-world applications, industrial impact, or startup-oriented innovation.

---

# 8. Cover Letter Structure

Use this structure unless the application explicitly requires something different:

1. Address block
2. Subject line
3. Greeting
4. Direct opening paragraph tailored to the role
5. Fixed education paragraph
6. Relevant experience paragraph using only selected CV items
7. Role-specific motivation paragraph
8. Analytical/research/industry-impact paragraph
9. Fixed closing paragraph
10. Sincerely, Ali Nazarikhah

Keep it one page if possible.

---

# 9. Email Template Rules

If an email is needed, provide:
- To:
- Subject:
- Email body

Keep email concise.

Email template:

To: [email address]

Subject: Application for [Position Title] ([Reference])

Dear [Recipient],

Please find attached my application for the [position title] at [institution/company].

The application includes my cover letter, CV, academic transcripts/certificates, and additional supporting documents, combined into a single PDF as requested.

I would highly appreciate the opportunity to contribute to your [team/group/institute] and further discuss my application.

Thank you for your time and consideration.

Kind regards,
Ali Nazarikhah
+49 176 8604 4654
ali.nazarikhah@iem.fraunhofer.de

---

# 10. File Naming Rules

Always provide a professional PDF file name.

Full application package:
Ali_Nazarikhah_Application_[Institution]_[Role]_[Reference].pdf

Cover letter only:
Ali_Nazarikhah_Cover_Letter_[Institution]_[Role]_[Reference].pdf

Examples:
Ali_Nazarikhah_Application_LMU_Mathematical_Foundations_AI_PhD.pdf
Ali_Nazarikhah_Cover_Letter_TU_Berlin_Robotics_AI_V-146-26.pdf

Use underscores. Avoid spaces. Keep it professional.

---

# 11. Form Answer Rules

If the job portal asks questions, provide short, direct answers.

Examples:

## Highest education
Master of Science in Energy Engineering, Sapienza University of Rome, graduated with highest distinction (110/110). I am also completing a second Master of Science in Engineering in Computer Science at Sapienza University of Rome / Paderborn University, with coursework completed and thesis pending.

## Current job
Research Assistant, GenAI Incubator, Fraunhofer IEM, Paderborn, Germany.

## Why this position?
Answer must be tailored to the role and mention only relevant experience.

## Languages
Persian — mother tongue
English — fluent
German — good
Italian — basic knowledge
Arabic — basic knowledge
Turkish — basic knowledge

---

# 12. Tone Rules

Use:
- Formal academic/professional tone
- Confident but honest phrasing
- Precise technical alignment
- Clear paragraphs

Avoid:
- Overclaiming
- Buzzwords without evidence
- Generic motivation
- Irrelevant projects
- “I am writing to express my interest”
- “Admissions Committee” for jobs

---

# 13. Output Format Required

When I paste a job description, respond with:

## 1. Selected matching profile elements
Briefly list which CV experiences/projects you selected and why.

## 2. Cover letter
Provide full cover letter.

## 3. Email
Provide To, Subject, and email body if relevant.

## 4. File name
Provide PDF name.

## 5. Form answers
Only if the application asks form questions.

---

Now analyze the following job description and generate the requested application materials:

[PASTE JOB DESCRIPTION HERE]
```

---

## Short Version Prompt

Use this shorter prompt when you need a faster result:

```text
Tailor a cover letter and email for the following position using my rules:

- Use correct address with named contact if available.
- Use comma-separated address format.
- Include exact subject with reference number.
- Do not start with “I am writing to express my interest.”
- Include this paragraph exactly:
  I completed my Master’s degree in Energy Engineering at Sapienza University of Rome with highest distinction (110/110), while simultaneously pursuing a second Master’s degree in Computer Engineering at Sapienza University and Paderborn University through a selective dual-track program for top-performing students. Managing both programs in parallel within the standard timeframe strengthened my ability to approach complex technical systems analytically and to combine engineering system understanding with computational modelling and data-driven methods.
- Include only relevant CV projects and experience.
- If I lack direct experience, acknowledge briefly and compensate with related background and fast learning.
- Include real-world, industry, or startup impact if relevant.
- Include this closing exactly:
  Given the inherent limitations of a cover letter, I understand that certain aspects of my profile may require further clarification. Please feel free to contact me if you need any additional information. I look forward to your feedback and the opportunity to further discuss my application.

  Thank you for your time and consideration.
- Provide PDF file name.
- Provide email text if email is available.

Job description:
[PASTE JOB DESCRIPTION HERE]
```
