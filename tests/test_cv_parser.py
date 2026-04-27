import pytest
from cover_letter.cv_parser import parse_cv

def test_parse_projects_from_cv():
    cv_text = """
# Projects

## EiCS — Engineering in Computer Science

### FORVIA HELLA
Development of ML pipeline for quality prediction.

### Benteler
Digital transformation and RAG systems.
"""
    result = parse_cv(cv_text)

    assert 'projects' in result
    assert 'EiCS' in result['projects']
    assert len(result['projects']['EiCS']) == 2
    assert result['projects']['EiCS'][0]['name'] == 'FORVIA HELLA'
    assert 'ML pipeline' in result['projects']['EiCS'][0]['description']

def test_parse_experience_from_cv():
    cv_text = """
# Experience

## Research Assistant

**Period:** Mar 2025 – Present
**Location:** Paderborn, Germany
**Organization:** GenAI Incubator, Fraunhofer IEM

Conducting research on Generative AI & ML-driven solutions.

## Energy Efficiency Consultant

**Period:** Jul 2021 – Oct 2021
**Location:** Tabriz, Iran
**Organization:** Talaaye Daaraane Moderne

Conducted industrial energy audits.
"""
    result = parse_cv(cv_text)

    assert 'experience' in result
    assert len(result['experience']) == 2
    assert result['experience'][0]['role'] == 'Research Assistant'
    assert result['experience'][0]['organization'] == 'GenAI Incubator, Fraunhofer IEM'
    assert 'Generative AI' in result['experience'][0]['description']

def test_parse_skills_from_cv():
    cv_text = """
# Skills

## EiCS

### AI/ML Engineering

LLMs, NLP, Generative AI, RAG, PyTorch, TensorFlow.

### Data Science

Python, Polars, PySpark, R, SQL, BigQuery.

## EE & CE

Python, MATLAB, OpenFOAM, HOMER Energy.
"""
    result = parse_cv(cv_text)

    assert 'skills' in result
    assert 'EiCS' in result['skills']
    assert 'AI/ML Engineering' in result['skills']['EiCS']
    assert 'PyTorch' in result['skills']['EiCS']['AI/ML Engineering']

def test_parse_education_from_cv():
    cv_text = """
# Education

## MSc — Energy Engineering [EE]

**Period:** 2022/23 – 2025/26
**Institution:** Sapienza University of Rome
**Details:**
- Thesis title: Energy Demand Modeling
- GPA: 110/110 [4.0/4.0]

## BSc — Chemical Engineering [CE]

**Period:** 2015/16 – 2020/21
**Institution:** Sahand University of Technology
"""
    result = parse_cv(cv_text)

    assert 'education' in result
    assert len(result['education']) == 2
    assert 'Energy Engineering' in result['education'][0]['degree']
    assert result['education'][0]['institution'] == 'Sapienza University of Rome'

def test_parse_research_interests_from_cv():
    cv_text = """
# Research Interests

## EE — Energy Engineering

- Energy Conversion and System Optimization
- Renewable Energy Systems
- Smart Grids

## EiCS — Engineering in Computer Science

- AI and ML Applications
- Data-Driven Decision-Making
"""
    result = parse_cv(cv_text)

    assert 'research_interests' in result
    assert 'EE' in result['research_interests']
    assert 'Energy Conversion' in result['research_interests']['EE'][0]
    assert len(result['research_interests']['EiCS']) == 2
