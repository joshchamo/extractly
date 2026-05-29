import asyncio
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

async def describe_node_safe(cdp, node_dict, backend_id):
    """
    Safely resolves a backendDOMNodeId to its HTML tag name, class, and id attributes via CDP.
    """
    try:
        node_desc = await cdp.send("DOM.describeNode", {"backendNodeId": backend_id})
        node_info = node_desc.get("node", {})
        tag = node_info.get("localName")
        attributes = node_info.get("attributes", [])
        attr_dict = {}
        for i in range(0, len(attributes), 2):
            attr_dict[attributes[i]] = attributes[i+1]
        
        if tag:
            node_dict["tag"] = tag
        if attr_dict.get("class"):
            node_dict["class"] = attr_dict.get("class")
        if attr_dict.get("id"):
            node_dict["id"] = attr_dict.get("id")
    except Exception:
        pass

async def fetch_page_analysis(url: str) -> dict:
    """
    Navigates to URL, waits for JS content, and returns page metadata:
    - Page Title
    - Accessibility Tree Snapshot (enriched with HTML tags and CSS classes)
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
            response = await page.goto(url, wait_until="domcontentloaded")
            if response and not response.ok:
                raise ValueError(f"Server returned status {response.status}: {response.status_text or 'Error'}")
            
            # Wait 5 seconds for JS-rendered content
            await page.wait_for_timeout(5000)
            
            # Extract fields
            title = await page.title()
            
            # Extract accessibility tree via CDP session since page.accessibility is deprecated/removed in Playwright Python
            accessibility_tree = {}
            try:
                cdp = await page.context.new_cdp_session(page)
                # Enable DOM agent so we can describe nodes
                await cdp.send("DOM.enable")
                cdp_result = await cdp.send("Accessibility.getFullAXTree")
                nodes = cdp_result.get("nodes", [])
                
                # Build maps
                node_map = {node.get("nodeId"): node for node in nodes if node.get("nodeId")}
                parent_map = {}
                for node in nodes:
                    nid = node.get("nodeId")
                    cids = node.get("childIds", [])
                    for cid in cids:
                        parent_map[cid] = nid
                        
                # Propagate text from StaticText/InlineTextBox to parent
                for node in nodes:
                    role = node.get("role", {}).get("value") if isinstance(node.get("role"), dict) else node.get("role")
                    if role in ("StaticText", "InlineTextBox"):
                        name_val = node.get("name", {}).get("value") if isinstance(node.get("name"), dict) else node.get("name")
                        if name_val:
                            nid = node.get("nodeId")
                            pid = parent_map.get(nid)
                            if pid and pid in node_map:
                                parent = node_map[pid]
                                curr_name = parent.get("name", {}).get("value") if isinstance(parent.get("name"), dict) else parent.get("name")
                                if not curr_name:
                                    parent["name"] = {"value": name_val}
                                else:
                                    if isinstance(parent.get("name"), dict):
                                        parent["name"]["value"] = str(parent["name"]["value"]) + " " + str(name_val)
                                    else:
                                        parent["name"] = str(parent["name"]) + " " + str(name_val)
                                        
                # Perform DFS to order nodes in document hierarchy
                ordered_nodes = []
                visited = set()
                
                root_node = None
                for node in nodes:
                    role = node.get("role", {}).get("value") if isinstance(node.get("role"), dict) else node.get("role")
                    if role == "RootWebArea":
                        root_node = node
                        break
                if not root_node and nodes:
                    root_node = nodes[0]
                    
                def dfs(node_id):
                    if node_id in visited:
                        return
                    visited.add(node_id)
                    node = node_map.get(node_id)
                    if not node:
                        return
                    ordered_nodes.append(node)
                    for cid in node.get("childIds", []):
                        dfs(cid)
                        
                if root_node:
                    dfs(root_node.get("nodeId"))
                    
                # Append any leftover unvisited nodes just in case
                for node in nodes:
                    nid = node.get("nodeId")
                    if nid not in visited:
                        ordered_nodes.append(node)
                        
                # Simplify and describe in DFS order
                filtered_nodes = []
                tasks = []
                for node in ordered_nodes:
                    if node.get("ignored"):
                        continue
                    role = node.get("role", {}).get("value") if isinstance(node.get("role"), dict) else node.get("role")
                    if role in ("StaticText", "InlineTextBox"):
                        continue
                    simplified = {"role": role}
                    name = node.get("name", {}).get("value") if isinstance(node.get("name"), dict) else node.get("name")
                    if name:
                        simplified["name"] = name
                    backend_id = node.get("backendDOMNodeId")
                    if backend_id:
                        tasks.append(describe_node_safe(cdp, simplified, backend_id))
                    filtered_nodes.append(simplified)
                
                # Fetch tag, class, and id for all nodes in parallel to avoid slow sequential calls
                if tasks:
                    await asyncio.gather(*tasks)
                    
                cleaned_nodes = []
                for node in filtered_nodes:
                    role = node.get("role", "")
                    name = node.get("name", "")
                    cls = node.get("class", "")
                    id_ = node.get("id", "")
                    
                    if not name and not cls and not id_ and role in ("generic", "none", "", None):
                        continue
                        
                    cleaned = {"role": role}
                    if name: cleaned["name"] = name
                    if cls: cleaned["class"] = cls
                    if id_: cleaned["id"] = id_
                    if node.get("tag"): cleaned["tag"] = node["tag"]
                    cleaned_nodes.append(cleaned)
                    
                accessibility_tree = {"nodes": cleaned_nodes}
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
            
            response = await page.goto(url, wait_until="domcontentloaded")
            if response and not response.ok:
                raise ValueError(f"Server returned status {response.status}: {response.status_text or 'Error'}")
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
                        field_sel_clean = field_sel.strip() if field_sel else ""
                        
                        # Auto-strip parent selector prefix if LLM generates absolute selectors
                        if field_sel_clean.startswith(selector):
                            field_sel_clean = field_sel_clean[len(selector):].strip()
                            if field_sel_clean.startswith(">") or field_sel_clean.startswith(" "):
                                field_sel_clean = field_sel_clean.lstrip("> ").strip()
                                
                        if not field_sel_clean:
                            field_sel_clean = "self"

                        # Extract relative to parent row
                        if field_sel_clean in (".", "self"):
                            val = await row.text_content()
                        else:
                            is_self_match = False
                            try:
                                is_self_match = await row.evaluate("(el, sel) => el.matches(sel)", field_sel_clean)
                            except Exception:
                                pass
                            
                            sub_el = row if is_self_match else await row.query_selector(field_sel_clean)
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
