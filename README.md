# aws-bedrock-pricing-data

A web scraper that extracts AWS Bedrock model pricing data from the [AWS Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) and saves it as structured JSON.

## How it works

Uses Playwright to drive a Chromium browser, then performs a depth-first traversal of every nested provider/model/tier tab on the pricing page. At each leaf node it extracts all visible pricing tables via BeautifulSoup, tagging each row with the full tab path it was reached from. Headings are detected by scoping to the table's enclosing `[role="tabpanel"]` so each row gets its real section name (e.g. `Geo and In-region Cross-region Inference`).

## Output format

Output is saved as `bedrock_n_level_pricing2.json` — roughly 700 rows across ~19 providers.

Every row includes these base fields, plus all columns from the source table:

| Field | Description |
|---|---|
| `Provider` | Top-level provider tab (Anthropic, Amazon, Meta, etc.) |
| `Hierarchy_Path` | Full ` > `-joined tab path traversed to reach this table |
| `Sub_Tab_1`, `Sub_Tab_2`, … | Each level of the path as its own field (dynamic depth) |
| `Pricing_Category` | The nearest heading above the table inside its tabpanel |

Pricing columns (names match the source table — examples):

- `Price per 1M input tokens` / `Price per 1M output tokens` — on-demand
- `Price per 1M input tokens (batch)` / `Price per 1M output tokens (batch)` — batch
- `Price per 1M input tokens (cache read)` / `(cache write)` / `(5m cache write)` / `(1h cache write)` — prompt caching tiers

## Usage

```bash
# Install dependencies
pip install playwright beautifulsoup4
playwright install chromium

# Run the scraper
python aws-bedrock-pricing.py
```

## Notes for contributors

A few things to know if you're modifying the scraper:

- **User-Agent spoofing is required.** AWS sniffs the User-Agent and serves a stripped-down pricing page to anything that looks headless (default Chromium UA contains `HeadlessChrome`). The script sets a real desktop Chrome UA — removing this drops roughly 25% of the data and silently mislabels section headings.
- **Pin a desktop viewport.** Headless Chromium defaults to 1280×720, which can trip responsive-layout breakpoints and hide columns like batch pricing. The script uses 1920×1200.
- **Lazy-load scroll.** Some tables only mount after scroll events, so `scroll_to_load_all` walks the page top-to-bottom before each extraction.
- **Source-side data quirks.** AWS occasionally has minor inconsistencies in its own page (e.g. some rows tagged `Global Cross-region Inference` and others `Global Cross region Inference` — note the missing hyphen). Normalize in a post-processing step if you need clean joins.
