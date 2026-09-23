# Project: Local Automated Job Application Assistant

## Objective

Create a local Python-based application that automates the job application preparation process and tracks subsequent communications. The user will input a job URL, and the system will extract job details using a free RapidAPI endpoint, analyze skill matching against a local LaTeX resume (`main.tex`), generate a tailored version of the LaTeX resume, compile it to a PDF using a lightweight compiler, log the application (and the direct apply link) in a Google Sheet, and continuously monitor Gmail for employer responses to update the tracker automatically.

## Constraints & Requirements

1. **Environment:** Must run locally (Python).
2. **User Input:** A single job URL (e.g., LinkedIn job posting).
3. **Application Process:** The system will NOT apply on behalf of the user. It will only prepare the assets and provide/log the direct "Apply" link for the user to submit manually.
4. **Resume Handling & Compilation:** 
    * Read and manipulate a local LaTeX (`main.tex`) file to extract current skills and generate an updated `.tex` file.
    * Compile the `.tex` file into a PDF locally using **Tectonic** (a lightweight, zero-configuration LaTeX engine that automatically downloads required packages on the fly, mimicking Overleaf's seamless environment).
5. **Data Extraction:** Use RapidAPI (e.g., LinkedIn Jobs API or JSearch freemium tiers) for extracting structured job data from a URL. No heavy web scraping (Selenium/Playwright).
6. **Tracking:** Use Google Sheets API to log job details and status.
7. **Email Tracking:** Use the Gmail API to scan for incoming emails related to applied jobs and classify their status using an LLM.

## Tech Stack Recommendations

* **Language:** Python 3.10+
* **LLM:** Google Gemini API (Free tier) or Groq API (Llama 3 - Free tier)
* **Job API:** RapidAPI (Free tier endpoints)
* **LaTeX Engine:** `tectonic` (Must be installed on the host machine. The Python script will call it via `subprocess`).
* **Google Workspace APIs:**
  * `gspread` and `oauth2client` libraries for Google Sheets.
  * `google-api-python-client`, `google-auth-httplib2`, and `google-auth-oauthlib` for Gmail API.

## Workflow & Implementation Steps

### Step 1: System Setup & User Input

* **Task:** Create a command-line interface (CLI) that prompts the user for a Job URL.
* **Config:** Load environment variables (`.env`) for API keys (LLM, RapidAPI, Google OAuth Desktop Credentials JSON).
* **Dependency Check:** Python script should verify that the `tectonic` CLI tool is installed and accessible in the system PATH.

### Step 2: Get Job Post (API Data Extraction)

* **Task:** Extract job title, company, description, and the direct apply link.
* **Implementation:**
  * Parse the job ID from the provided URL.
  * Make a GET request to the chosen RapidAPI endpoint using the Job ID.
  * Extract JSON response: `title`, `company`, `description`, `apply_link`.

### Step 3: Parse Resume & Match Qualifications

* **Task:** Read the base `main.tex` file and compare it against the job description.
* **Implementation:**
  * Open and read `main.tex` into a string.
  * Construct an LLM prompt containing: (A) The parsed job description, and (B) The raw text of the `main.tex` file.
  * **LLM Task 1:** Return a JSON object with:
    * `match_score` (0-100)
    * `missing_skills` (list)
    * `matching_skills` (list)
    * `core_requirements` (list)

### Step 4: Update Resume & Compile to PDF

* **Task:** Generate a tailored version of the resume and compile it.
* **Implementation:**
  * Construct a second LLM prompt instructing it to update the `main.tex` string.
  * **Prompt Rules:**
    * Inject missing keywords where contextually accurate.
    * Rewrite the professional summary/objective to align with the job title.
    * **CRITICAL:** Do NOT break LaTeX syntax. Escape special characters properly (`%`, `&`, `$`, `_`).
  * Save the LLM output as a new file: `[Company_Name]_Resume.tex`.
  * **Compilation:** Use Python's `subprocess.run` to execute: `tectonic [Company_Name]_Resume.tex`. This will output `[Company_Name]_Resume.pdf`.

### Step 5: Track in Google Sheets

* **Task:** Log the job details and the application link into a pre-configured Google Sheet so the user can apply manually.
* **Implementation:**
  * Authenticate using `gspread`.
  * Append a new row to the specified sheet with the following columns:
    `[Date Applied, Company, Job Title, Match Score %, Local PDF Path, Application URL, Status, Last Email Date]`
  * Set default Status to "Pending Manual Application" or "Ready to Apply".

### Step 6: Track Email Responses (Gmail Integration)

* **Task:** Monitor incoming emails to detect responses from companies and update the tracker.
* **Implementation:**
  * Create a separate routine (e.g., `python agent.py --check-mail`).
  * Fetch a list of all "Company" names currently in the Google Sheet where Status is not terminal (e.g., not "Rejected", "Hired", or "Ready to Apply").
  * Use the Gmail API to search for recent emails containing these company names.
  * **LLM Task 3:** Pass the body of matched emails to the LLM to classify the response: `["Rejection", "Interview Invite", "Assessment/Test", "Marketing/Spam", "Offer"]`.
  * **Action:** Update the specific company's row in the Google Sheet with the new `Status` and `Last Email Date`.

## Agent Instructions for Error Handling

* **LaTeX Compilation Failures:** If `tectonic` returns a non-zero exit code (meaning the LLM broke the LaTeX syntax), catch the error output. Send the error log and the broken `.tex` string back to the LLM in a new prompt asking it to fix the LaTeX compilation error, then retry compilation.
* **Authentication Flow:** Use Google OAuth Client ID for Desktop applications. The script should trigger a browser popup for initial user consent and save a `token.json` for subsequent runs so personal Gmail inboxes can be scanned securely.