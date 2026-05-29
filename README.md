# Extractly 🕸️
### Turn Any Webpage Into a Spreadsheet Using Plain English

No code. No browser extensions. No local installs. Just paste a URL, 
describe what you want, and download your CSV.

---

## Try It In 10 Seconds

Paste any of these into the app to see it in action:

| URL | Prompt |
|-----|--------|
| `https://news.ycombinator.com` | Extract the title and link of each news item |
| `https://books.toscrape.com` | Extract the titles and prices of all books |
| `https://quotes.toscrape.com` | Extract the quote text, author, and tags |

---

## Who Is This For?

- **Researchers** who need data from a webpage without writing Python
- **Journalists** who want to turn a table or list into a spreadsheet
- **Product managers** who want competitor pricing or feature lists
- **Data enthusiasts** who know what they want but not how to get it
- **QA engineers** exploring NLP-driven browser automation

---

## How It Works
You describe it → AI identifies the structure →
Playwright extracts it → You download the CSV

1. **Paste a URL** — any publicly accessible webpage
2. **Describe what you want** in plain English
   — *"Extract the title and price of each product"*
   — *"Get the author, quote, and tags from each entry"*
3. **Extractly navigates the page** server-side using a 
   headless Chromium browser — no extension needed
4. **An LLM analyzes the page structure** and identifies 
   the right CSS selectors automatically
5. **Your data appears** as a clean preview table with 
   a one-click CSV download

---

## Under the Hood: Advanced Extraction Engineering

Extractly isn't just a simple raw HTML scraper. It employs several advanced runtime engineering mechanisms to ensure selector stability and high extraction accuracy:

*   **DFS Accessibility Tree Serialization**: Performs a Depth-First Search (DFS) traversal of the Chrome Accessibility Tree via direct Chrome DevTools Protocol (CDP) sessions. This preserves semantic reading order and document hierarchy, preventing token truncation and layout-ordering issues.
*   **Semantic Text Hoisting**: Automatically hoists text content from inner `StaticText` and `InlineTextBox` child nodes to their parent semantic elements, providing full contextual layout info to the LLM.
*   **Self-Correcting Selector Guards**:
    *   **Absolute Selector Stripping**: Sanitizes selectors to prevent the LLM from generating brittle absolute selector paths.
    *   **Parent Self-Match Auto-Correction**: Detects if a relative sub-field selector matches the card container itself. Automatically falls back to query narrower sub-elements (e.g. `.author`, `small`, `.tags`, `.price`) to prevent retrieving the entire card block.
    *   **List & Tag Formatting**: Detects fields representing multiple inline tags or categories. Automatically cleanses label text (removing prefixes like `"by "` or `"(about)"`), strips formatting whitespace, and joins items into a single-line comma-separated string.
    *   **Main Link & Utility Filtering**: Discriminates utility links (like category tags, upvotes, flags, or comments) from the primary destination URL to guarantee correct outbound links.

---

## What Makes This Different

Most scraping tools require either coding knowledge or 
expensive subscriptions. Extractly fills the gap:

| | Extractly | Code (Playwright/BS4) | Paid Platforms |
|---|---|---|---|
| Setup required | None | Node/Python install | Account + subscription |
| Technical knowledge | None | Required | Some |
| Cost | Free | Free | $$$  |
| Plain English input | ✅ | ❌ | Partial |
| Runs in browser | ✅ | ❌ | ✅ |

---

## Privacy & Compliance

- **robots.txt viewer** built in — check a site's scraping 
  guidelines before you extract
- **SSRF protection** — private IPs and localhost are blocked 
  server-side
- **No data retention** — extracted data lives only in your 
  session and is never stored
- Users are responsible for ensuring their use complies 
  with target site terms of service

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| Headless Browser | Playwright (Chromium, server-side via CDP) |
| AI / NLP | Groq Cloud — `llama-3.1-8b-instant` |
| Data | pandas |
| Frontend | Jinja2 + Vanilla CSS (Glassmorphic Dark Theme with One-Click Quick-Try Chips) |
| Deployment | HuggingFace Spaces, Docker |

---

## Local Development

### Prerequisites
- Python 3.11
- Groq API key — free at [console.groq.com](https://console.groq.com)

### Setup

```bash
git clone https://github.com/joshchamo/extractly.git
cd extractly
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Run

```bash
export GROQ_API_KEY="your-key-here"
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

Open `http://localhost:7860`

---

## Limitations

- Single page only — pagination is not yet supported
- JavaScript-heavy SPAs may require additional load time
- Results depend on page structure — 
  highly dynamic or obfuscated sites may not extract cleanly
- Respects a 20 second navigation timeout per page

---

*Built with FastAPI + Playwright + Groq. 
Part of an ongoing series of AI automation tools.*  
Developer: Josh Chamo [joshchamo@gmail.com] 
