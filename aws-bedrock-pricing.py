import argparse
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import re

# Map standard AWS region codes to the exact text used in the UI
REGION_MAPPING = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-2": "US West (Oregon)",
    "ca-central-1": "Canada (Central)",
    "eu-west-1": "Europe (Ireland)",
    "eu-west-2": "Europe (London)",
    "eu-west-3": "Europe (Paris)",
    "eu-central-1": "Europe (Frankfurt)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "sa-east-1": "South America (São Paulo)"
}

def set_target_region_and_filter(page, ui_target_region, level):
    page.wait_for_timeout(1000)
    
    region_regex = re.compile(r"US East|US West|Europe|Asia Pacific|Canada|South America", re.IGNORECASE)
    dropdowns =[]
    dropdowns.extend(page.locator('select').all())
    
    for el in page.locator('button, [role="combobox"], [role="button"]').all():
        try:
            if el.is_visible() and region_regex.search(el.inner_text()):
                if el not in dropdowns:
                    dropdowns.append(el)
        except: pass

    if not dropdowns:
        return False

    for d in dropdowns:
        try:
            if not d.is_visible(): continue
            
            is_select = d.evaluate('el => el.tagName.toLowerCase() === "select"')
            supported = False
            
            if is_select:
                options_text = d.evaluate('el => Array.from(el.options).map(o => o.innerText).join(" ")')
                if ui_target_region.lower() in options_text.lower():
                    d.select_option(label=ui_target_region)
                    supported = True
            else:
                current_text = d.inner_text().split('\n')[0].strip()
                if ui_target_region.lower() == current_text.lower():
                    supported = True
                else:
                    d.click()
                    page.wait_for_timeout(500)
                    option = page.locator('[role="option"]').filter(has_text=re.compile(f"^{re.escape(ui_target_region)}", re.IGNORECASE)).first
                    if option.is_visible():
                        option.click()
                        supported = True
                    else:
                        page.keyboard.press("Escape")
                        supported = False
                    page.wait_for_timeout(500)
            
            if not supported:
                print(f"{'  ' * level}⚠️ Model not supported in '{ui_target_region}'. Hiding table.")
                d.evaluate('''el => {
                    let parent = el;
                    for(let i=0; i<5; i++) {
                        if(parent.parentElement) parent = parent.parentElement;
                    }
                    parent.style.display = "none";
                }''')
        except Exception as e:
            pass
            
    page.wait_for_timeout(1500)
    return True

def extract_tables(page, current_path, region_code):
    tables_data = page.evaluate('''() => {
        const tables = Array.from(document.querySelectorAll('table'));
        const visibleTables = tables.filter(t => t.offsetWidth > 0 && t.offsetHeight > 0);
        
        return visibleTables.map(table => {
            let heading = "General Pricing";
            let currentElement = table;
            for (let level = 0; level < 4; level++) {
                if (!currentElement) break;
                let prev = currentElement.previousElementSibling;
                while (prev) {
                    if (['H1', 'H2', 'H3', 'H4', 'H5', 'H6'].includes(prev.tagName)) {
                        heading = prev.innerText.trim(); break;
                    }
                    const innerHeading = prev.querySelector && prev.querySelector('h1, h2, h3, h4, h5, h6');
                    if (innerHeading) { heading = innerHeading.innerText.trim(); break; }
                    prev = prev.previousElementSibling;
                }
                if (heading !== "General Pricing") break;
                currentElement = currentElement.parentElement;
            }
            return { heading: heading, html: table.outerHTML };
        });
    }''')

    extracted =[]
    for item in tables_data:
        # 🚨 FILTER 1: Exclude if the heading explicitly mentions 'example'
        if "example" in item['heading'].lower():
            continue

        soup = BeautifulSoup(item['html'], "html.parser")
        table = soup.find("table")
        if not table: continue
        
        thead = table.find("thead")
        header_row = thead.find("tr") if thead else table.find("tr")
        if not header_row: continue
        
        headers =[th.get_text(separator=" ", strip=True) for th in header_row.find_all(["th", "td"])]
        headers =[h if h else f"Column_{i}" for i, h in enumerate(headers)]
        
        # 🚨 FILTER 2: Exclude if table columns are for examples (e.g., Total Cost)
        headers_lower = [h.lower() for h in headers]
        if any("example" in h or "total cost" in h or "monthly cost" in h for h in headers_lower):
            continue
            
        # 🚨 FILTER 3: Exclude if the table body contains "Scenario" text
        is_example_body = False
        for row in table.find_all("tr"):
            text = row.get_text(separator=" ", strip=True).lower()
            if "scenario" in text or "pricing example" in text:
                is_example_body = True
                break
                
        if is_example_body:
            continue

        # Standard Data Extraction
        for row in table.find_all("tr"):
            if row == header_row: continue
            cells = row.find_all(["td", "th"])
            cell_texts =[c.get_text(separator=" ", strip=True) for c in cells]
            
            if len(cell_texts) == len(headers) and len(headers) > 0:
                if any(t != "" for t in cell_texts):
                    entry = {
                        "Hierarchy_Path": " > ".join(current_path),
                        "Provider": current_path[0] if len(current_path) > 0 else "Unknown",
                        "Pricing_Category": item['heading'],
                        "Region": region_code 
                    }
                    for depth in range(1, len(current_path)):
                        entry[f"Sub_Tab_{depth}"] = current_path[depth]
                        
                    entry.update(dict(zip(headers, cell_texts)))
                    extracted.append(entry)
    return extracted

def get_nested_tablists(page):
    visible =[t for t in page.locator('[role="tablist"]').all() if t.is_visible()]
    return[t for t in visible if t.get_by_role("tab", name=re.compile(r"^model pricing$", re.IGNORECASE)).count() == 0]

def explore_tabs_recursively(page, level, current_path, all_pricing_data, ui_target_region, region_code):
    page.wait_for_timeout(1000) 
    current_nested_tablists = get_nested_tablists(page)
    
    if level >= len(current_nested_tablists):
        print(f"{'  ' * level}📍 Base Level:[{' > '.join(current_path)}]. Configuring Region...")
        
        has_regions = set_target_region_and_filter(page, ui_target_region, level)
        assigned_region = region_code if has_regions else "global"
        
        all_pricing_data.extend(extract_tables(page, current_path, assigned_region))
        return

    tablist_at_this_level = current_nested_tablists[level]
    num_tabs = tablist_at_this_level.get_by_role("tab").count()
    
    for i in range(num_tabs):
        try:
            refreshed_tablists = get_nested_tablists(page)
            if level >= len(refreshed_tablists): break
                
            target_tab = refreshed_tablists[level].get_by_role("tab").nth(i)
            if target_tab.is_visible():
                tab_name = target_tab.inner_text().split('\n')[0].strip()
                print(f"{'  ' * level}➡️ Traversing: {tab_name}...")
                
                target_tab.click()
                page.wait_for_timeout(1500) 
                
                explore_tabs_recursively(page, level + 1, current_path + [tab_name], all_pricing_data, ui_target_region, region_code)
        except Exception as e:
            pass

def scrape_targeted_bedrock_pricing(region_code):
    ui_target_region = REGION_MAPPING.get(region_code.lower())
    
    if not ui_target_region:
        print(f"❌ Error: AWS Region code '{region_code}' is not recognized.")
        return

    url = "https://aws.amazon.com/bedrock/pricing/"
    all_pricing_data =[]

    print(f"🚀 Launching Scraper for {region_code} (UI: {ui_target_region})")
    with sync_playwright() as p:
        # headless=True for production speed!
        browser = p.chromium.launch(headless=True) 
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(3000)

        main_tab = page.get_by_role("tab", name=re.compile(r"^model pricing$", re.IGNORECASE)).first
        if main_tab.is_visible():
            main_tab.click()
            page.wait_for_timeout(2000)

        explore_tabs_recursively(page, level=0, current_path=[], all_pricing_data=all_pricing_data, ui_target_region=ui_target_region, region_code=region_code.lower())

        browser.close()

    print("\n✅ Extraction complete! Deduplicating data...")
    unique_data =[dict(t) for t in {tuple(sorted(d.items())) for d in all_pricing_data}]
    unique_data = sorted(unique_data, key=lambda x: (x.get('Provider', ''), x.get('Pricing_Category', '')))

    filename = f"bedrock_pricing_{region_code.lower()}.json"
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(unique_data, f, indent=4, ensure_ascii=False)
        
    print(f"🎉 Success! Scraped {len(unique_data)} records. Saved to {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AWS Bedrock Pricing Scraper API")
    parser.add_argument("--region", type=str, default="us-west-2", help="AWS Region Code (e.g., us-east-1, eu-central-1)")
    
    args = parser.parse_args()
    scrape_targeted_bedrock_pricing(args.region)