import socket
import ipaddress
from urllib.parse import urlparse
from playwright.async_api import async_playwright

def is_safe_url(url: str) -> bool:
    """
    Validates that a URL is a properly formed http:// or https:// URL
    and does not resolve to loopback, private, or link-local IP addresses.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        
        hostname = parsed.hostname
        if not hostname:
            return False
        
        # Check if the hostname is directly an IP address
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
                return False
            return True
        except ValueError:
            # Not a raw IP address, proceed to DNS resolution
            pass
        
        # Resolve all IP addresses for the hostname
        addr_info = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
                return False
        return True
    except Exception:
        return False

async def fetch_page_analysis(url: str) -> dict:
    """
    Navigates to URL, waits for JS content, and returns page metadata:
    - Page Title
    - Accessibility Tree Snapshot
    - Body inner text (trimmed to 3000 chars)
    """
    if not is_safe_url(url):
        raise ValueError("URL is invalid or points to a blocked private network address.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # Set navigation timeout (20000ms)
            page.set_default_navigation_timeout(20000)
            page.set_default_timeout(20000)
            
            # Navigate to target
            await page.goto(url)
            
            # Wait 5 seconds for JS-rendered content
            await page.wait_for_timeout(5000)
            
            # Extract fields
            title = await page.title()
            
            # Extract accessibility tree via CDP session since page.accessibility is deprecated/removed in Playwright Python
            accessibility_tree = {}
            try:
                cdp = await page.context.new_cdp_session(page)
                cdp_result = await cdp.send("Accessibility.getFullAXTree")
                nodes = cdp_result.get("nodes", [])
                filtered_nodes = []
                for node in nodes:
                    if node.get("ignored"):
                        continue
                    simplified = {
                        "nodeId": node.get("nodeId"),
                        "role": node.get("role", {}).get("value") if isinstance(node.get("role"), dict) else node.get("role"),
                        "name": node.get("name", {}).get("value") if isinstance(node.get("name"), dict) else node.get("name"),
                        "childIds": node.get("childIds", [])
                    }
                    filtered_nodes.append(simplified)
                accessibility_tree = {"nodes": filtered_nodes}
            except Exception:
                accessibility_tree = {}
            
            try:
                body_text = await page.inner_text('body')
            except Exception:
                body_text = ""
                
            body_text_trimmed = body_text[:3000] if body_text else ""
            
            return {
                "title": title or "No Title",
                "accessibility_tree": accessibility_tree or {},
                "body_text": body_text_trimmed
            }
        finally:
            await browser.close()

async def extract_data(url: str, selector: str, fields: list[dict]) -> list[dict]:
    """
    Navigates to the URL and extracts repeating elements using the
    provided CSS selectors.
    """
    if not is_safe_url(url):
        raise ValueError("URL is invalid or points to a blocked private network address.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            page.set_default_navigation_timeout(20000)
            page.set_default_timeout(20000)
            
            await page.goto(url)
            await page.wait_for_timeout(5000)
            
            # Find all parent rows matching selector
            rows = await page.query_selector_all(selector)
            if not rows:
                return []
                
            extracted_data = []
            for row in rows:
                row_data = {}
                for field in fields:
                    name = field.get("name")
                    field_sel = field.get("selector")
                    if not name:
                        continue
                    
                    try:
                        # Extract relative to parent row
                        if not field_sel or field_sel.strip() in ("", ".", "self"):
                            val = await row.text_content()
                        else:
                            sub_el = await row.query_selector(field_sel)
                            if sub_el:
                                # Check if it's a link/image tag and might have useful attributes if text is empty
                                tag_name = await sub_el.evaluate("el => el.tagName.toLowerCase()")
                                val = await sub_el.text_content()
                                val = val.strip() if val else ""
                                if not val:
                                    if tag_name == "a":
                                        val = await sub_el.get_attribute("href") or ""
                                    elif tag_name == "img":
                                        val = await sub_el.get_attribute("src") or ""
                            else:
                                val = ""
                        
                        row_data[name] = val.strip() if val else ""
                    except Exception:
                        row_data[name] = ""
                        
                extracted_data.append(row_data)
                
            return extracted_data
        finally:
            await browser.close()
