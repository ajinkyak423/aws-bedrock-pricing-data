from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import re

def scroll_to_load_all(page):
    """
    AWS lazy-loads pricing tables as the user scrolls. Walk the page top-to-bottom
    in viewport-sized steps so every table mounts before we read the DOM.
    """
    for _ in range(12):
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(400)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(800)

def extract_tables(page, current_path):
    """
    Extracts all visible tables on the screen right now.
    Appends the dynamic navigation path (e.g., Anthropic > Text Models) to the data.
    """
    scroll_to_load_all(page)
    tables_data = page.evaluate('''() => {
        const tables = Array.from(document.querySelectorAll('table'));
        // Only get tables physically painted on the screen right now
        const visibleTables = tables.filter(t => t.offsetWidth > 0 && t.offsetHeight > 0);

        return visibleTables.map(table => {
            let heading = "General Pricing";

            // Scope the heading search to the active tabpanel containing this table.
            // This avoids the responsive-layout DOM reordering that breaks a naive
            // previousElementSibling walk (e.g. Mistral / Anthropic sub-sections).
            const panel = table.closest('[role="tabpanel"]') || document.body;

            // Walk headings and tables in document order within the panel and pick
            // the most recent non-empty heading that appears before this table.
            const elements = Array.from(panel.querySelectorAll('h1, h2, h3, h4, h5, h6, table'));
            const tableIndex = elements.indexOf(table);
            for (let i = tableIndex - 1; i >= 0; i--) {
                const el = elements[i];
                if (/^H[1-6]$/.test(el.tagName)) {
                    const text = (el.innerText || '').trim();
                    if (text) {
                        heading = text;
                        break;
                    }
                }
            }

            return { heading: heading, html: table.outerHTML };
        });
    }''')

    extracted =[]
    for item in tables_data:
        soup = BeautifulSoup(item['html'], "html.parser")
        table = soup.find("table")
        if not table: continue
        
        thead = table.find("thead")
        header_row = thead.find("tr") if thead else table.find("tr")
        if not header_row: continue
        
        headers =[th.get_text(separator=" ", strip=True) for th in header_row.find_all(["th", "td"])]
        headers =[h if h else f"Column_{i}" for i, h in enumerate(headers)]
        
        for row in table.find_all("tr"):
            if row == header_row: continue
            
            cells = row.find_all(["td", "th"])
            cell_texts = [c.get_text(separator=" ", strip=True) for c in cells]
            
            if len(cell_texts) == len(headers) and len(headers) > 0:
                if any(t != "" for t in cell_texts):
                    # Construct our dynamic dictionary based on the recursion depth
                    entry = {
                        "Hierarchy_Path": " > ".join(current_path),
                        "Provider": current_path[0] if len(current_path) > 0 else "Unknown",
                        "Pricing_Category": item['heading']
                    }
                    
                    # Dynamically add Sub_Tab_1, Sub_Tab_2, etc., based on how deep we went!
                    for depth in range(1, len(current_path)):
                        entry[f"Sub_Tab_{depth}"] = current_path[depth]
                        
                    entry.update(dict(zip(headers, cell_texts)))
                    extracted.append(entry)
                    
    return extracted

def get_nested_tablists(page):
    """
    Returns a list of all currently VISIBLE tab groups, 
    EXCLUDING the root page navigation (Knowledge Bases, Model Pricing, etc.)
    """
    visible_tablists =[t for t in page.locator('[role="tablist"]').all() if t.is_visible()]
    nested =[]
    for t in visible_tablists:
        # If this tablist does NOT contain the main "Model pricing" tab, it's a provider/nested tablist
        if t.get_by_role("tab", name=re.compile(r"^model pricing$", re.IGNORECASE)).count() == 0:
            nested.append(t)
    return nested

def explore_tabs_recursively(page, level, current_path, all_pricing_data):
    """
    DFS Recursive function that clicks every possible permutation of nested tabs.
    """
    # Wait briefly for UI state to settle before evaluating screen depth
    page.wait_for_timeout(1000) 
    
    current_nested_tablists = get_nested_tablists(page)
    
    # BASE CASE: No more nested tabs below our current level! We hit a leaf node.
    if level >= len(current_nested_tablists):
        print(f"{'  ' * level}🟢 Reached data tier: [{' > '.join(current_path)}]. Extracting tables...")
        all_pricing_data.extend(extract_tables(page, current_path))
        return

    # RECURSIVE CASE: We have a row of tabs at this level. We must click every single one.
    tablist_at_this_level = current_nested_tablists[level]
    num_tabs = tablist_at_this_level.get_by_role("tab").count()
    
    for i in range(num_tabs):
        try:
            # Re-fetch the DOM state (clicking previous tabs might detach elements)
            refreshed_tablists = get_nested_tablists(page)
            if level >= len(refreshed_tablists): 
                break
                
            target_tab = refreshed_tablists[level].get_by_role("tab").nth(i)
            
            if target_tab.is_visible():
                tab_name = target_tab.inner_text().split('\n')[0].strip()
                print(f"{'  ' * level}➡️ Clicking level {level + 1}: {tab_name}...")
                
                target_tab.click()
                # Crucial wait time allowing React/Vue to fetch and render the inner tabs/tables
                page.wait_for_timeout(1500) 
                
                # RECURSION: Go one level deeper!
                explore_tabs_recursively(page, level + 1, current_path + [tab_name], all_pricing_data)
                
        except Exception as e:
            print(f"{'  ' * level}⚠️ Failed at level {level}, tab {i}: {e}")

def scrape_dynamic_bedrock_pricing():
    url = "https://aws.amazon.com/bedrock/pricing/"
    all_pricing_data =[]

    print("Launching recursive N-Level deep browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # Keep False to watch the algorithm work!
        # AWS sniffs the User-Agent and serves a stripped-down pricing page to
        # headless Chromium (the default UA contains "HeadlessChrome"). Force a
        # real desktop Chrome UA so headless gets the same DOM as a real browser.
        # Also pin a wide viewport to avoid responsive layout differences.
        context = browser.new_context(
            viewport={"width": 1920, "height": 1200},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # 1. ENTER THE MAIN GATEWAY: Click the "Model Pricing" root tab
        print("Locating main 'Model pricing' navigation...")
        main_tab = page.get_by_role("tab", name=re.compile(r"^model pricing$", re.IGNORECASE)).first
        if main_tab.is_visible():
            main_tab.click()
            page.wait_for_timeout(2000)

        # 2. TRIGGER THE RECURSION
        print("\nInitiating Depth-First Search on nested tabs...\n")
        explore_tabs_recursively(page, level=0, current_path=[], all_pricing_data=all_pricing_data)

        browser.close()

    print("\nRecursion complete! Cleaning and deduplicating massive dataset...")
    
    # Hash and sort to perfectly deduplicate tables
    unique_data =[dict(t) for t in {tuple(sorted(d.items())) for d in all_pricing_data}]
    
    # Sort beautifully by the generated Hierarchy path
    unique_data = sorted(unique_data, key=lambda x: (x.get('Hierarchy_Path', ''), x.get('Pricing_Category', '')))

    # 3. SAVE THE OUTPUT
    with open("bedrock_n_level_pricing.json", "w", encoding="utf-8") as f:
        json.dump(unique_data, f, indent=4, ensure_ascii=False)
        
    print(f"✅ Master Architecture Scraped! Saved {len(unique_data)} distinct pricing metrics across all dynamic depths.")

if __name__ == "__main__":
    scrape_dynamic_bedrock_pricing()