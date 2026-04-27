# aws-bedrock-pricing-data

A web scraper that extracts AWS Bedrock model pricing data from the [AWS Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) and saves it as structured JSON.

## How it works

Uses Playwright to drive a headless Chromium browser, navigates the pricing page's nested tabs (by provider and model category), sets the target AWS region in the UI dropdowns, then extracts all visible pricing tables via BeautifulSoup. Example/scenario tables are filtered out automatically.

## Output format

Each record in the JSON includes:

| Field | Description |
|---|---|
| `Provider` | Model provider (e.g., Anthropic, Amazon, Meta) |
| `Model Name` | Model name and variant |
| `Pricing_Category` | Section heading from the pricing page |
| `Hierarchy_Path` | Full tab path traversed to reach the table |
| `Region` | AWS region code (or `global` if region-agnostic) |
| `Price per 1M input/output tokens` | On-demand pricing |
| `Price per 1M input/output tokens (batch)` | Batch pricing |
| `Price per 1M input tokens (cache read/write)` | Prompt caching pricing |

## Usage

```bash
# Install dependencies
pip install playwright beautifulsoup4
playwright install chromium

# Scrape pricing for a specific region (default: us-west-2)
python aws-bedrock-pricing.py --region us-east-1
```

Output is saved as `bedrock_pricing_<region>.json`.

