# TruthLens AI
### Content Investigation & Fake News Analysis Platform

**TruthLens AI** is a Python-based Streamlit application designed to organise the early stages of digital content investigation. It helps reviewers extract content from different file formats, identify candidate factual claims, collect and compare related evidence, inspect source and image indicators, and preserve an investigation record.

> **Important:** TruthLens AI is an investigation-support prototype, not an autonomous fact-checking authority. It does not independently prove that a claim is true or false, establish a publisher's editorial reliability, or conclusively determine whether an image is AI-generated or manipulated. Human review of original sources and context remains essential.

## Table of Contents
- [Project Overview](#project-overview)
- [Problem Statement and Objectives](#problem-statement-and-objectives)
- [Features](#features)
- [Supported Inputs](#supported-inputs)
- [Workflow](#workflow)
- [Architecture and Modules](#architecture-and-modules)
- [Algorithms and Technical Approach](#algorithms-and-technical-approach)
- [Technology Stack](#technology-stack)
- [Installation and Setup](#installation-and-setup)
- [Configuration](#configuration)
- [Data Storage](#data-storage)
- [Security and Responsible Use](#security-and-responsible-use)
- [Limitations](#limitations)
- [Testing Status](#testing-status)
- [Future Enhancements](#future-enhancements)
- [Project Team](#project-team)
- [Academic Information](#academic-information)

---

## Project Overview

Digital information is shared through news articles, screenshots, scanned documents, presentations, spreadsheets, and social posts. Reviewing a claim across these formats can require several disconnected tools and make it difficult to retain a traceable record of the reasoning.

TruthLens AI brings several early-stage investigation tasks into one workspace: importing content, extracting text, generating candidate claims, reviewing evidence, recording evidence relationships, inspecting technical source/image indicators, and generating an investigation report.

The system is designed to make the investigation process more organised, explainable, and reviewable.

## Problem Statement and Objectives

Content reviewers may need to extract a statement from a document or image, locate its original context, compare supporting and conflicting material, and document their findings. Performing these tasks manually across separate applications can be slow and fragmented.

Project objectives:
- Provide a unified interface for preliminary digital content investigation.
- Support common document, image, text, and public webpage inputs.
- Apply OCR when a document does not contain usable embedded text.
- Identify candidate claims through transparent sentence-level rules.
- Help reviewers compare claim wording with evidence excerpts.
- Record supporting, contradicting, contextual, and unclear evidence.
- Display technical URL/domain and image-forensics indicators with caveats.
- Provide investigation history, analytics, profiles, and PDF reports where configured.

## Features

### Multi-format content ingestion
Accepts supported files, pasted text, and public webpage URLs. Format-specific readers route each input to the relevant extraction method.

### PDF extraction with OCR fallback
The PDF reader first attempts embedded-text extraction. If the extracted text is too short to be useful, pages can be rendered as images and passed to OCR.

### Image and scanned-document OCR
Uses Tesseract OCR through pytesseract. Image preprocessing is applied to improve readability before recognition.

### Candidate claim extraction
Sentence-level rules filter possible factual statements using word-count limits, factual cue words, question/opinion filters, text normalisation, and duplicate removal. The reviewer chooses which candidate to investigate.

### Evidence review and relationship labelling
Evidence excerpts can be labelled as:
- **Supports** — the reviewer considers the excerpt supportive of the selected claim.
- **Contradicts** — the reviewer considers the excerpt conflicting with the claim.
- **Context only** — the excerpt adds context but does not directly support or contradict.
- **Unclear** — the relationship cannot confidently be determined.

These labels are reviewer-entered assessments, not automatic proof.

### Evidence similarity assistance
A Jaccard lexical-overlap calculation can help prioritise excerpts for review. It measures shared words, not meaning or factual correctness.

### Source and URL indicators
The application inspects technical URL and domain characteristics, such as HTTPS use and configured domain categories. These are indicators only; HTTPS or a domain suffix does not guarantee accuracy.

### Image-forensics indicators
Includes image metadata inspection, edge/texture analysis, JPEG Error Level Analysis (ELA), and an experimental AI image-classification pipeline. Results should be interpreted cautiously.

### Optional AI Assistant
When the relevant Hugging Face configuration is available, an AI-assisted chat feature can be used. A deterministic local fallback is available when the optional service is not configured or cannot be reached.

### History, analytics, profiles, and reports
Supporting features allow users to review saved investigation records, view analytics, manage profile information, and generate PDF reports, subject to configured storage and runtime environment.

## Supported Inputs

| Input type | Typical handling |
|---|---|
| PDF | Embedded text extraction; OCR fallback for scanned/image-based pages |
| DOCX | Text extraction using python-docx |
| PPTX | Slide text extraction using python-pptx |
| XLSX | Spreadsheet reading using pandas and openpyxl |
| TXT | Direct text reading |
| JPG / JPEG / PNG / WEBP | Image preprocessing and OCR; image-forensics checks where applicable |
| Pasted text | Direct candidate-claim processing |
| Public webpage URL | Safe retrieval and HTML text extraction |

Actual extraction quality depends on file structure, language data, image quality, and runtime configuration.

## Workflow

1. **User input:** upload a supported file, paste text, or provide a public webpage URL.
2. **Content extraction:** the relevant reader extracts text from the supplied material.
3. **OCR fallback:** scanned/image-based content is processed through OCR when required.
4. **Candidate claims:** sentence-level rules identify possible factual statements.
5. **Human selection:** the reviewer selects the claim to investigate.
6. **Evidence review:** relevant webpage material and excerpts are collected for inspection.
7. **Relationship labels:** the reviewer records Supports, Contradicts, Context only, or Unclear.
8. **Assessment summary:** the application summarises the recorded evidence relationships.
9. **Investigation record:** history, analytics, and PDF report features help preserve the review.

Human judgement remains essential when checking extracted text, selecting claims, inspecting original sources, assigning evidence labels, and interpreting results.

## Architecture and Modules

TruthLens AI is organised as a Streamlit application with specialised Python modules.

- **Presentation layer:** Streamlit pages, forms, navigation, session state, and user-facing results.
- **Processing layer:** document readers, OCR, claim extraction, webpage parsing, evidence comparison, and image analysis.
- **Investigation layer:** evidence relationship records and assessment summaries.
- **Persistence layer:** SQLite for local application data, with optional Supabase REST integration for investigation/evidence storage.
- **Output layer:** investigation views, analytics, and PDF report generation.

| Module / area | Responsibility |
|---|---|
| app.py | Main Streamlit entry point, UI orchestration, and navigation |
| file_reader.py | Routes supported file types to suitable text extraction logic |
| ocr.py | OCR processing and image preprocessing |
| claim_extractor.py | Candidate sentence filtering, normalisation, and deduplication |
| verification.py | Claim/evidence investigation workflow support |
| web_reader.py | Public webpage retrieval, URL checks, and HTML text extraction |
| source_credibility.py | Technical URL/domain indicators |
| evidence_analyzer.py | Evidence review and relationship handling |
| evidence_similarity.py | Jaccard lexical-overlap calculation |
| claim_assessment.py | Summary logic based on recorded evidence labels |
| image_forensics.py | Metadata, image signals, and ELA-related analysis |
| ai_features.py | Optional AI-assisted functionality and fallback behaviour |
| auth.py | Authentication-related logic |
| user_profile.py | User profile functionality |
| database.py | Local SQLite persistence |
| cloud_store.py | Optional Supabase REST storage integration |
| report_generator.py | PDF report generation |

## Algorithms and Technical Approach

### 1. PDF extraction and OCR decision
The system first attempts embedded-text extraction from a PDF using PyMuPDF (fitz). If the trimmed extracted text contains at least 20 characters, it is retained. If it is below that heuristic threshold, the page can be rendered at 2× resolution and processed through OCR. The 20-character condition is a fallback heuristic, not a guarantee that extracted text is complete or meaningful.

### 2. OCR preprocessing
The documented OCR pipeline uses Pillow and Tesseract:
1. Convert the image to RGB where required.
2. Convert to grayscale.
3. Apply autocontrast.
4. Increase contrast using a configured factor of 1.5.
5. Run Tesseract with configured options, including --oem 3 --psm 6.
6. Check availability of configured language data such as English (eng) and Hindi (hin).

Tesseract and required language packs must be installed in the runtime environment. OCR can misread names, numbers, tables, and low-quality scans.

### 3. Candidate claim extraction
The candidate extractor uses transparent heuristics rather than claiming complete semantic fact verification:
- sentence splitting;
- candidate length range of 7–65 words;
- filtering questions and configured opinion cues;
- checking configured factual cue words in English and Hindi;
- text normalisation;
- set-based duplicate removal;
- default maximum of 25 candidate claims.

The output is a list of possible claims for human selection. A candidate is not automatically a verified fact.

### 4. Jaccard lexical similarity
The Jaccard coefficient compares two token sets:

**J(A,B) = |A ∩ B| / |A ∪ B| × 100**

Example:
- Claim tokens: {city, water, supply, increased}
- Evidence tokens: {city, water, supply, shortage}
- Common tokens: 3
- Total unique tokens: 5
- Jaccard overlap: 3 / 5 × 100 = **60%**

Configured interpretation bands:
- **High:** 50% or above
- **Moderate:** 20% to below 50%
- **Low:** below 20%

This is lexical overlap only. It does not establish semantic equivalence, support, contradiction, or truth.

### 5. Evidence assessment summary

| Recorded evidence relationships | Summary |
|---|---|
| No evidence | Insufficient Evidence |
| Both Supports and Contradicts | Mixed Evidence |
| Supports only | Supporting Evidence Recorded |
| Contradicts only | Contradicting Evidence Recorded |
| Other combinations, including context/unclear only | Inconclusive |

The logic preserves mixed evidence rather than forcing every investigation into a binary true/false result. Relationship labels are selected by the reviewer.

### 6. URL and webpage safety checks
The webpage retrieval component includes safeguards such as:
- accepting HTTP/HTTPS schemes only;
- requiring a valid hostname;
- rejecting URL credentials;
- blocking localhost and private/local IP destinations;
- revalidating redirect destinations;
- limiting redirects to a maximum of 5;
- applying request timeouts;
- limiting response size to 2 MB;
- extracting HTML content and removing irrelevant page elements.

These controls help reduce risks such as Server-Side Request Forgery (SSRF), where an attacker attempts to make a server request internal or private resources. They do not guarantee that every webpage is safe or trustworthy.

### 7. Source/domain indicators
The source indicator logic can identify configured government-style and education-style domain suffixes, a limited local-news publisher list, HTTPS usage, unknown domains, deep hostnames, long query strings, and URL shorteners.

These checks are technical clues only. A domain category or HTTPS connection is not a factual accuracy score and does not prove editorial quality.

### 8. Image-forensics indicators
- **EXIF metadata:** checks available metadata such as format, dimensions, colour mode, and camera fields when present.
- **Edge/texture signals:** uses Pillow edge processing and summary statistics.
- **JPEG Error Level Analysis (ELA):** recompresses an image at configured quality 90, compares pixel differences, and enhances the difference image for inspection.
- **Experimental image classifier:** uses a Hugging Face Transformers image-classification pipeline with PyTorch and device selection where available (MPS/CUDA/CPU).

Missing metadata, unusual ELA patterns, edge statistics, and classifier scores can all be misleading. These outputs are not conclusive proof of manipulation or AI generation.

### 9. Password handling
The documented authentication implementation uses salted PBKDF2-HMAC-SHA256 password hashing with a random 16-byte salt and 310,000 iterations. Password verification uses constant-time comparison through hmac.compare_digest.

## Technology Stack

| Technology / library | Role |
|---|---|
| Python | Core application and processing language |
| Streamlit | Web application interface and workflow |
| PyMuPDF (fitz) | PDF text extraction and page rendering |
| pytesseract + Tesseract OCR | Optical character recognition |
| Pillow (PIL) | Image loading and preprocessing |
| python-docx | DOCX text extraction |
| python-pptx | PPTX text extraction |
| pandas + openpyxl | XLSX spreadsheet processing |
| Requests | HTTP requests for public webpage retrieval |
| Beautiful Soup | HTML parsing and cleanup |
| PyTorch + Transformers | Experimental image-classification pipeline |
| ReportLab | PDF report generation |
| Altair | Analytics visualisation |
| SQLite | Local persistence and authentication/profile data |
| Supabase REST (optional) | Configurable investigation/evidence storage |

## Installation and Setup

### Prerequisites
- Python version compatible with the packages in requirements.txt.
- Git.
- Tesseract OCR installed separately if OCR functionality is required.
- Optional service credentials only for integrations you intend to enable.

### 1. Clone the repository
    git clone https://github.com/ritu511/TruthLens-AI.git
    cd TruthLens-AI

### 2. Create and activate a virtual environment

**macOS / Linux**
    python3 -m venv .venv
    source .venv/bin/activate

**Windows PowerShell**
    python -m venv .venv
    .venv\Scripts\Activate.ps1

### 3. Install Python dependencies
    python -m pip install --upgrade pip
    pip install -r requirements.txt

### 4. Install Tesseract OCR
Install the Tesseract executable using the installer or package manager appropriate for your operating system. Install required language data (for example, English and Hindi) and ensure the executable is available on your system PATH. Configure the application if it is installed in a custom location.

### 5. Run the application
    streamlit run app.py

Streamlit will print a local address in the terminal. Open that address in your browser.

Check the repository's current requirements.txt and deployment configuration for exact runtime dependencies.

## Configuration

Optional integrations use environment variables. Set them in your local environment or hosting provider's secret manager; do not place real values in source code or commit them.

| Variable | Purpose |
|---|---|
| HF_TOKEN | Optional Hugging Face access for the AI Assistant/model service |
| SUPABASE_URL | Enables the configured Supabase REST storage connection |
| SUPABASE_SERVICE_ROLE_KEY | Server-side Supabase service-role credential for the configured storage integration |

The AI Assistant can use a deterministic local fallback if the optional Hugging Face service is unavailable or not configured.

**Security note:** A Supabase service-role key is highly privileged. Keep it private, use hosting secrets, and never expose it in frontend code or a public repository.

## Data Storage

- Local SQLite is used for authentication and profile data in the documented implementation.
- Investigation/evidence storage can use Supabase REST when the relevant environment variables are configured.
- SQLite fallback is available for investigation/evidence storage.
- Supabase integration for investigation/evidence does **not** mean authentication and profile records are automatically migrated to Supabase; those remain SQLite-backed in the current implementation.

Persistence behaviour should be checked in the exact deployment environment before relying on it for long-term records.

## Security and Responsible Use

- Treat extracted content as untrusted until reviewed.
- Verify important statements against original, primary sources wherever possible.
- Do not treat lexical similarity as semantic proof.
- Do not treat HTTPS, domain suffixes, or publisher-list membership as a guarantee of reliability.
- Interpret OCR output carefully, especially names, dates, quantities, and tables.
- Treat image-forensics outputs as indicators, not verdicts.
- Keep API tokens, database credentials, and service-role keys out of Git.
- Use safe URL retrieval controls and review external content before relying on it.
- Preserve contradictory evidence and communicate uncertainty.

## Limitations

1. Candidate-claim extraction is rule-based and may miss valid claims or include irrelevant sentences.
2. OCR accuracy depends on image quality, layout, fonts, and installed language packs.
3. Jaccard similarity measures shared tokens, not semantic meaning or factual support.
4. Evidence relationship labels are entered by the reviewer.
5. Source/domain checks are limited technical indicators, not a complete reputation or fact-checking system.
6. Webpage content may change, be unavailable, or contain incomplete context.
7. EXIF, edge/texture, and ELA signals are not reliable standalone manipulation detectors.
8. The AI image classifier is experimental and may produce false positives or false negatives.
9. Optional AI services depend on credentials, network availability, service limits, and model availability.
10. Storage and persistence depend on the configured runtime and external services.
11. Authentication/profile data remain SQLite-backed in the documented implementation.
12. A generated report reflects the information and reviewer labels available to the application; it is not an independent certification of truth.

## Testing Status

The project report documents a test strategy and proposed functional test areas. It does not claim that every proposed test has passed on the current hosted build.

Recommended verification includes:
- registration, login, and password verification;
- supported file formats and invalid-file handling;
- embedded PDF text and scanned PDF OCR fallback;
- English/Hindi OCR language availability;
- claim extraction filters, deduplication, and candidate limit;
- evidence assessment for no evidence, support-only, contradiction-only, mixed, and unclear/context cases;
- URL validation, redirects, private-address blocking, timeout, and response-size handling;
- image metadata, ELA, and classifier error handling;
- storage isolation and persistence after restart;
- PDF report output;
- optional integrations with and without credentials.

Only mark a test as passed after it has actually been executed against the relevant version and environment.

## Future Enhancements

- Improve candidate-claim extraction using stronger NLP and multilingual processing.
- Add semantic claim-evidence reasoning while preserving human review.
- Improve source verification with traceable primary-source references and transparent criteria.
- Evaluate image-forensics models on representative datasets and communicate confidence limitations.
- Improve persistent storage, backup, and deployment configuration.
- Expand automated tests for security, file handling, and data isolation.
- Improve accessibility, responsive design, and user guidance.
- Add clearer evidence provenance and explainable investigation timelines.

## Project Team

| Team member | Project responsibility |
|---|---|
| Himanshu Saroj | Project Lead & Backend (Team Leader) |
| Krish Bansal | Document Processing & OCR |
| Ritu Raj | Claim Verification & Evidence Analysis |
| Shreyansh Jaiswal | AI & Image Forensics |

## Academic Information

- **Project title:** TruthLens AI – Content Investigation & Fake News Analysis
- **Programme:** B.Tech – Computer Science & Engineering (Artificial Intelligence)
- **Institution:** KCC Institute of Technology and Management, Greater Noida
- **Department:** Computer Science & Engineering
- **Project type:** Minor Project

## Disclaimer

TruthLens AI is an academic investigation-support prototype. Its automated outputs are preliminary indicators and should not be represented as definitive fact-checking decisions. Always inspect original sources, compare context, consider conflicting evidence, and apply informed human judgement.

## Repository

https://github.com/ritu511/TruthLens-AI
