import os
import json
import re
from groq import Groq

# Read GROQ_API_KEY from environment variables
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def clean_json_string(text: str) -> str:
    """
    Cleans the raw response string to ensure it's a valid JSON object.
    Removes markdown code fences and isolates curly brace boundaries.
    """
    text = text.strip()
    
    # Strip markdown code blocks
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    # Isolate first '{' and last '}'
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1:
        text = text[first_brace:last_brace + 1]
        
    return text

def validate_schema(data: dict) -> None:
    """
    Validates that the parsed JSON complies with the expected extraction schema.
    """
    if not isinstance(data, dict):
        raise ValueError("Parsed result is not a dictionary.")
    if "selector" not in data or "fields" not in data:
        raise ValueError("Missing 'selector' or 'fields' in the JSON structure.")
    if not isinstance(data["fields"], list):
        raise ValueError("'fields' must be a list.")
    for f in data["fields"]:
        if not isinstance(f, dict) or "name" not in f or "selector" not in f:
            raise ValueError("Each field item must contain a 'name' and 'selector'.")

def prepare_contents(title: str, accessibility_tree: dict, body_text: str) -> tuple[str, str]:
    """
    Trims content defensively to stay safely under LLM token limits (approx 5000 tokens total).
    Prioritizes accessibility tree content over body text.
    Ensures that the accessibility tree JSON remains valid and well-formed.
    """
    nodes = accessibility_tree.get("nodes", [])
    
    # We aim to keep total characters of page context under 12,000 (roughly 3,000 tokens)
    max_combined = 12000
    
    tree_str = json.dumps({"nodes": nodes})
    
    if len(tree_str) + len(body_text) > max_combined:
        # If combined is too large, we truncate body text first (down to max 1000 characters)
        if len(tree_str) < 8000:
            allowed_body = max_combined - len(tree_str)
            body_text = body_text[:allowed_body]
        else:
            body_text = body_text[:1000]
            # Now truncate accessibility nodes list sequentially to guarantee valid JSON structure
            while len(nodes) > 10 and len(json.dumps({"nodes": nodes})) + len(body_text) > max_combined:
                nodes.pop()
            tree_str = json.dumps({"nodes": nodes})
            
    return tree_str, body_text

async def get_selectors_from_llm(title: str, accessibility_tree: dict, body_text: str, prompt: str) -> dict:
    """
    Constructs prompt, sends it to Groq API, parses response, and manages 
    the retry-once loop on failure.
    """
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY environment variable is not configured. Please add the secret key in HuggingFace Spaces.")

    client = Groq(api_key=GROQ_API_KEY)
    tree_str, body_trimmed = prepare_contents(title, accessibility_tree, body_text)
    
    system_prompt = (
        "You are a web scraping assistant. Analyze the provided page content and accessibility tree, "
        "then identify the best CSS selectors to extract what the user wants.\n"
        "Return ONLY a valid JSON object in exactly this format, with no markdown, no code fences, "
        "no explanation before or after the JSON:\n"
        "{\n"
        "  \"selector\": \"CSS selector targeting repeating data rows\",\n"
        "  \"fields\": [\n"
        "    {\"name\": \"field_name\", \"selector\": \"relative CSS selector\"}\n"
        "  ],\n"
        "  \"explanation\": \"one plain English sentence describing what was found and will be extracted\"\n"
        "}\n\n"
        "Example of a valid response for a product listing page:\n"
        "{\n"
        "  \"selector\": \".product-item\",\n"
        "  \"fields\": [\n"
        "    {\"name\": \"name\", \"selector\": \".product-title\"},\n"
        "    {\"name\": \"price\", \"selector\": \".product-price\"},\n"
        "    {\"name\": \"rating\", \"selector\": \".product-rating\"}\n"
        "  ],\n"
        "  \"explanation\": \"Found 24 product listings with name, price and rating fields.\"\n"
        "}"
    )
    
    user_message = (
        f"Page Title: {title}\n\n"
        f"Accessibility Tree:\n{tree_str}\n\n"
        f"Body Text:\n{body_trimmed}\n\n"
        f"User Data Extraction Request: {prompt}"
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.0
        )
        content = response.choices[0].message.content
        try:
            cleaned = clean_json_string(content)
            data = json.loads(cleaned)
            validate_schema(data)
            return data
        except Exception:
            # First attempt failed. Retry once with a explicit correction prompt.
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "Return only the raw JSON object, no other text."})
            
            retry_response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                temperature=0.0
            )
            retry_content = retry_response.choices[0].message.content
            cleaned_retry = clean_json_string(retry_content)
            data = json.loads(cleaned_retry)
            validate_schema(data)
            return data
            
    except Exception as e:
        raise ValueError(
            "Could not identify a data structure on this page. "
            "Try rephrasing your request or check that the page contains the data you described."
        )
