import os
import uuid
import pandas as pd
from urllib.parse import urlparse
import requests

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.session_store import session_store
from app.playwright_utils import is_safe_url, fetch_page_analysis, extract_data
from app.llm import get_selectors_from_llm

app = FastAPI(title="Extractly")

# Templates
templates = Jinja2Templates(directory="templates")

class ExtractRequest(BaseModel):
    url: str
    prompt: str

class RobotsRequest(BaseModel):
    url: str

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/extract")
async def extract(req: ExtractRequest):
    url = req.url.strip()
    prompt = req.prompt.strip()
    
    if not url:
        return JSONResponse(status_code=400, content={"detail": "URL is required."})
    if not prompt:
        return JSONResponse(status_code=400, content={"detail": "Prompt is required."})
        
    if not is_safe_url(url):
        return JSONResponse(
            status_code=400,
            content={"detail": "Access to local, private IP addresses or invalid protocols is blocked."}
        )
        
    try:
        # Step 1: Page Analysis (navigates and retrieves text + accessibility tree)
        analysis = await fetch_page_analysis(url)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Failed to retrieve webpage. Please check the URL and try again. Error: {str(e)}"}
        )
        
    try:
        # Step 2: Call LLM to identify selectors
        llm_response = await get_selectors_from_llm(
            title=analysis["title"],
            accessibility_tree=analysis["accessibility_tree"],
            body_text=analysis["body_text"],
            prompt=prompt
        )
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"detail": str(e)}
        )
        
    selector = llm_response.get("selector")
    fields = llm_response.get("fields")
    explanation = llm_response.get("explanation", "")
    
    if not selector or not fields:
        return JSONResponse(
            status_code=400,
            content={"detail": "Could not identify a data structure on this page. Try rephrasing your request."}
        )
        
    try:
        # Step 3: Extract data using selectors
        extracted_rows = await extract_data(url, selector, fields)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Failed to extract elements using selectors. Error: {str(e)}"}
        )
        
    if not extracted_rows:
        return JSONResponse(
            status_code=400,
            content={"detail": "No data items could be extracted with the generated selectors. Make sure the page has repeating items matching your description."}
        )
        
    try:
        # Convert to pandas DataFrame and store in session
        df = pd.DataFrame(extracted_rows)
        
        # Ensure column order aligns with fields definition
        field_names = [f["name"] for f in fields if f.get("name")]
        # Keep only fields present in dataframe
        cols = [col for col in field_names if col in df.columns]
        if cols:
            df = df[cols]
            
        session_id = str(uuid.uuid4())
        session_store[session_id] = df
        
        return {
            "columns": list(df.columns),
            "rows": df.values.tolist(),
            "explanation": explanation,
            "row_count": len(df),
            "session_id": session_id
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Error structuring data. Error: {str(e)}"}
        )

@app.get("/download")
async def download(session_id: str):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id parameter is required.")
        
    df = session_store.get(session_id)
    if df is None:
        raise HTTPException(status_code=404, detail="Session expired or results not found.")
        
    csv_content = df.to_csv(index=False)
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=extractly_results.csv"
        }
    )

@app.post("/robots")
async def fetch_robots(req: RobotsRequest):
    url = req.url.strip()
    if not url:
        return {"content": "No URL provided."}
        
    if not is_safe_url(url):
        return {"content": "Blocked private IP range or invalid protocol."}
        
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        if not is_safe_url(robots_url):
            return {"content": "Robots URL points to a blocked address."}
            
        response = requests.get(robots_url, timeout=10)
        if response.status_code == 200:
            return {"content": response.text}
        else:
            return {"content": "No robots.txt found"}
    except Exception:
        return {"content": "No robots.txt found"}
