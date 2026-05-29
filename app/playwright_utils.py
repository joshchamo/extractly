import asyncio
import re
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
                        
                    # Filter out layout/navigation boilerplate and their descendants
                    role = node.get("role", {}).get("value") if isinstance(node.get("role"), dict) else node.get("role")
                    if role in ("banner", "navigation", "complementary", "contentinfo"):
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
                            
                            # Loosen selector: if a tag-class selector (like span.title) fails to match, try matching only by class (.title)
                            if not sub_el and not is_self_match and field_sel_clean and "." in field_sel_clean:
                                parts = field_sel_clean.split(" ")
                                modified = False
                                for i, part in enumerate(parts):
                                    if "." in part and not part.startswith("."):
                                        sub_parts = part.split(".")
                                        if sub_parts[0].isalnum():
                                            parts[i] = "." + ".".join(sub_parts[1:])
                                            modified = True
                                if modified:
                                    loosened_sel = " ".join(parts)
                                    try:
                                        found_el = await row.query_selector(loosened_sel)
                                        if found_el:
                                            sub_el = found_el
                                            field_sel_clean = loosened_sel
                                    except Exception:
                                        pass
                            
                            field_name_lower = name.lower()
                            
                            # Self-match correction: if a specific field like author, tags, price matches the parent row itself,
                            # try to find a narrower child element instead.
                            if is_self_match and field_name_lower in ("author", "tags", "tag", "price", "title", "name"):
                                candidates = []
                                if field_name_lower == "author":
                                    candidates = [".author", "small", "[itemprop='author']", ".author-name"]
                                elif field_name_lower in ("tags", "tag"):
                                    candidates = [".tags", ".tag", "a.tag", ".categories"]
                                elif field_name_lower == "price":
                                    candidates = [".price", ".price_color", "span.price", ".price-value"]
                                    
                                for cand in candidates:
                                    found = await row.query_selector(cand)
                                    if found:
                                        sub_el = found
                                        is_self_match = False
                                        break
                            
                            # Guard 1: If title field matches multiple elements and the first is just a rank/number
                            if sub_el and field_name_lower in ("title", "name") and not is_self_match:
                                all_matches = await row.query_selector_all(field_sel_clean)
                                if len(all_matches) > 1:
                                    first_text = (await all_matches[0].text_content() or "").strip().rstrip(".")
                                    if first_text.isdigit() or len(first_text) <= 3:
                                        for candidate in all_matches[1:]:
                                            cand_text = (await candidate.text_content() or "").strip()
                                            if cand_text and not cand_text.isdigit() and len(cand_text) > len(first_text):
                                                sub_el = candidate
                                                break
                                                
                            # Guard 2: If link field matches a utility link, look for a better link in the container
                            if sub_el and field_name_lower in ("link", "url", "href") and not is_self_match:
                                tag_name = await sub_el.evaluate("el => el.tagName.toLowerCase()")
                                if tag_name == "a":
                                    href_val = await sub_el.get_attribute("href") or ""
                                    if "vote?" in href_val or "flag?" in href_val or "goto=" in href_val or not href_val:
                                        # Try to find a better anchor in the same row
                                        all_anchors = await row.query_selector_all("a")
                                        for anchor in all_anchors:
                                            a_href = await anchor.get_attribute("href") or ""
                                            if a_href and not any(k in a_href for k in ("vote?", "flag?", "goto=")):
                                                sub_el = anchor
                                                break
                                                
                            if sub_el:
                                # Check if it's a link/image tag and might have useful attributes
                                tag_name = await sub_el.evaluate("el => el.tagName.toLowerCase()")
                                if tag_name == "a":
                                    # If the field name suggests it is a link/URL, prioritize the href attribute
                                    if field_name_lower in ("link", "url", "href"):
                                        href_attr = await sub_el.get_attribute("href") or ""
                                        if href_attr and not href_attr.startswith(("http://", "https://", "mailto:", "tel:")):
                                            parsed_base = urlparse(url)
                                            val = f"{parsed_base.scheme}://{parsed_base.netloc}/{href_attr.lstrip('/')}"
                                        else:
                                            val = href_attr
                                    else:
                                        # Prioritize the 'title' attribute if it contains the full text of the link
                                        val = await sub_el.get_attribute("title") or ""
                                        val = val.strip()
                                        if not val:
                                            val = await sub_el.text_content()
                                            val = val.strip() if val else ""
                                        if not val:
                                            # Check if there is an image child with alt text
                                            img_child = await sub_el.query_selector("img")
                                            if img_child:
                                                val = await img_child.get_attribute("alt") or ""
                                                val = val.strip()
                                        if not val:
                                            val = await sub_el.get_attribute("href") or ""
                                elif tag_name == "img":
                                    val = await sub_el.get_attribute("alt") or await sub_el.get_attribute("src") or ""
                                else:
                                    val = await sub_el.text_content()
                                    val = val.strip() if val else ""
                                    
                                # Truncation check fallback
                                if val.endswith("...") or val.endswith("…"):
                                    anchor = sub_el if tag_name == "a" else await sub_el.query_selector("a")
                                    if anchor:
                                        full_title = await anchor.get_attribute("title")
                                        if full_title and len(full_title) > len(val) - 3:
                                            val = full_title
                            else:
                                val = ""
                        
                        # Clean up value as requested
                        val_cleaned = val.strip() if val else ""
                        if val_cleaned:
                            # Strip '(about)' if present anywhere in the value
                            val_cleaned = re.sub(r'\(about\)', '', val_cleaned, flags=re.IGNORECASE).strip()
                            
                            # Strip common label prefixes
                            if val_cleaned.lower().startswith("by "):
                                val_cleaned = val_cleaned[3:].strip()
                            if val_cleaned.lower().startswith("tags:"):
                                val_cleaned = val_cleaned[5:].strip()
                            elif val_cleaned.lower().startswith("tags"):
                                rest = val_cleaned[4:].lstrip()
                                if len(rest) < len(val_cleaned) - 4:
                                    val_cleaned = rest
                                    
                            # Add special handling for fields where the LLM selector targets a container 
                            # with multiple child elements (like tags). 
                            # If the result contains multiple newline-separated short words, split them, 
                            # strip each one, filter empty strings, and rejoin as a comma-separated string.
                            if "\n" in val_cleaned:
                                parts = [p.strip() for p in val_cleaned.split("\n")]
                                parts = [p for p in parts if p]
                                
                                # Remove any remaining tag-like labels from the list (like "tags")
                                cleaned_parts = []
                                for p in parts:
                                    p_low = p.lower()
                                    if p_low in ("tags:", "tags", "tag:", "tag"):
                                        continue
                                    cleaned_parts.append(p)
                                    
                                if len(cleaned_parts) > 1 and all(len(p) < 30 for p in cleaned_parts):
                                    val_cleaned = ", ".join(cleaned_parts)
                                else:
                                    # Strip newlines and collapse multiple spaces to single spaces
                                    val_cleaned = re.sub(r'\s+', ' ', val_cleaned).strip()
                            else:
                                # Collapse multiple spaces to single spaces
                                val_cleaned = re.sub(r'\s+', ' ', val_cleaned).strip()
                        
                        row_data[name] = val_cleaned
                    except Exception:
                        row_data[name] = ""
                        
                extracted_data.append(row_data)
                
            return extracted_data
        finally:
            await browser.close()
