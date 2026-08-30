# Custom GPT Usage Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Help self-hosters configure a Custom GPT to select Schwabber operations correctly and interpret market and SEC responses without publishing any private investment strategy.

**Architecture:** Add a neutral usage guide for human operators and concise descriptions to the generated OpenAPI schema used by Custom GPT Actions. Keep setup, usage, and private analyst instructions separate; link the public guide from the README and Action setup guide.

**Tech Stack:** Markdown, FastAPI OpenAPI generation, Pydantic schemas, pytest, Ruff, mypy

---

### Task 1: Define the public Action contract

**Files:**
- Modify: `tests/test_app.py`

- [x] **Step 1: Add failing OpenAPI tests**

Require every public operation to have a meaningful description, every request parameter to have a description, and critical response fields such as cache age, real-time status, and SEC reporting provenance to be described.

- [x] **Step 2: Run focused tests and confirm failure**

Run: `pytest -q tests/test_app.py`

Expected: FAIL because the OpenAPI descriptions do not exist yet.

### Task 2: Publish neutral Custom GPT usage guidance

**Files:**
- Create: `docs/custom-gpt-usage.md`
- Modify: `README.md`
- Modify: `docs/gpt-action-setup.md`

- [x] **Step 1: Write the guide**

Document operation selection, common research workflows, source and freshness semantics, missing-data rules, error handling, security boundaries, and a generic Custom GPT instruction block. Do not include private analyst personas, credentials, hostnames, or investment methodology.

- [x] **Step 2: Link the guide from public entry points**

Add concise links from the README and Action setup guide without duplicating the full guidance.

- [x] **Step 3: Review the public documentation**

Confirm the guide contains every public operation, the reusable instruction
template, source boundaries, security guidance, and working relative links.

### Task 3: Improve the Action-facing OpenAPI contract

**Files:**
- Modify: `src/schwabber/api/market.py`
- Modify: `src/schwabber/api/sec.py`
- Modify: `src/schwabber/api/status.py`
- Modify: `src/schwabber/schemas/common.py`
- Modify: `src/schwabber/schemas/market.py`
- Modify: `src/schwabber/schemas/sec.py`

- [x] **Step 1: Describe operations and request parameters**

Add concise, model-oriented descriptions that state what each operation returns, its appropriate use, and relevant limits. Describe symbols, dates, frequencies, forms, counts, and filters.

- [x] **Step 2: Describe critical response semantics**

Describe response source and retrieval time, cache hit and age, truncation, real-time flags, SEC reported/derived provenance, and filing URLs.

- [x] **Step 3: Run the OpenAPI test**

Run: `pytest -q tests/test_app.py`

Expected: PASS.

### Task 4: Verify and review

**Files:**
- Verify only

- [x] **Step 1: Run the full test suite**

Run: `pytest -q`

Expected: all tests PASS.

- [x] **Step 2: Run static checks**

Run: `ruff check src tests`

Expected: no lint errors.

Run: `mypy src`

Expected: no type errors.

- [x] **Step 3: Verify staged scope**

Run: `git diff --cached --name-only`

Expected: only the planned public project files are staged.

### Task 5: Document Schwab developer setup

**Files:**
- Create: `docs/schwab-developer-setup.md`
- Modify: `README.md`
- Modify: `docs/gpt-action-setup.md`

- [x] **Step 1: Define the documentation checklist**

Require the official portal URL, App Key and Secret mappings, exact callback
guidance, middleware-key distinction, OAuth redirect handling, token storage
modes, credential warnings, and links from both onboarding entry points.

- [x] **Step 2: Write and link the stable setup guide**

Document the portal prerequisites and field mappings without depending on
authenticated portal navigation labels. Cover Docker and direct-host token paths,
manual OAuth login, status verification, reauthorization, and Schwab agreement
guidance.

- [x] **Step 3: Review documentation and run full verification**

Review the guide and relative links directly; Markdown prose is not enforced with
brittle content assertions.

Run: `pytest -q && ruff check src tests && mypy src`

Expected: all checks PASS.
