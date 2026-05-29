---
title: Extractly
emoji: 🕸️
colorFrom: indigo
colorTo: cyan
sdk: docker
pinned: false
short_description: Extract data from any webpage using plain English — no code required
---

# Extractly 🕸️

Extractly is an NLP-powered web scraping and data extraction agent designed to work entirely server-side inside HuggingFace Spaces. 

With Extractly, you don't need any local web scraping extensions, browser installations, or coding knowledge. Simply provide a webpage URL and a plain English description of what data you want to retrieve, and the application handles the rest—rendering a preview table and generating a downloadable CSV.

## Key Features
- **Server-Side Playwright Headless Browser**: Navigates to modern Javascript-rendered websites dynamically on the server.
- **NLP Structural Parsing**: Utilizes Groq Cloud with `llama-3.1-8b-instant` to analyze the page's accessibility tree and body content to generate precise CSS selectors.
- **Zero Extension Scraping**: Runs headlessly inside a Docker container.
- **Privacy and Compliance Check**: Includes a built-in robots.txt viewer to query site-specific scraping guidelines beforehand.
- **Advanced Security Boundaries**: Implements server-side request verification blocking loopbacks, private subnets (SSRF protection), and local hosts.

## Tech Stack
- **Backend**: Python 3.11, FastAPI, Uvicorn
- **Headless Browser**: Playwright (Python)
- **AI Integration**: Groq Cloud SDK (Model: `llama-3.1-8b-instant`)
- **Data Engineering**: pandas
- **Frontend**: Single-page Jinja2 HTML template with custom responsive Vanilla CSS (Glassmorphic Dark Theme)

## How It Works

1. **Page Analysis**: Playwright accesses the URL, waiting up to 5 seconds for client-side JavaScript execution. It retrieves the page title, accessibility tree, and visible body text (trimmed defensively to stay within LLM token constraints).
2. **Selector Identification**: The model parses page structure and maps the user's natural language request to repeating container selectors and relative field selectors.
3. **Data Extraction**: The server retrieves all elements matching the container, parses child attributes, structures the results in a pandas DataFrame, and saves them to an in-memory session.
4. **Interactive UI**: The data is loaded into a responsive table, allowing immediate preview and CSV download.

---

## Local Development Setup

To run Extractly on your local machine, follow these steps:

### 1. Prerequisites
- Python 3.11 installed
- A Groq API Key (Sign up at [Groq Console](https://console.groq.com/))

### 2. Installation
Clone the repository:
```bash
git clone https://github.com/joshchamo/extractly.git
cd extractly
```

Create a virtual environment and install requirements:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Install Playwright browsers and dependencies:
```bash
playwright install chromium
```

### 3. Running the Server
Set your Groq API key:
```bash
export GROQ_API_KEY="your-groq-api-key-here"
```

Start the FastAPI application:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

Open your browser and navigate to `http://localhost:7860`.

---

## Deployment to HuggingFace Spaces

When deploying this project to HuggingFace, configure it as a **Docker Space**:

1. Create a new Space on HuggingFace: `Jchamo/Extractly`.
2. Choose **Docker** as the SDK.
3. Add your `GROQ_API_KEY` under the Space **Settings** -> **Variables and Secrets** (as a secret value).
4. Push this codebase to the Space repository. HuggingFace will automatically build the Docker image using the provided `Dockerfile` and boot the server on port `7860`.
