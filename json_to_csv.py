"""
Convert bedrock_n_level_pricing2.json into a SQL-friendly CSV.

- Model names normalized to Bedrock log style (e.g. `anthropic.claude-sonnet-4-6`,
  with `global.` prefix for Global Cross-region Inference rows). The pricing
  page doesn't carry the date stamp / `-v1:0` suffix that appears in real log
  IDs — join with `LIKE '<id>%'` or strip the suffix from log IDs before joining.
- Prices are plain decimals (no `$`, no commas).
"""
import csv
import json
import re
import unicodedata

INPUT_JSON = "bedrock_n_level_pricing.json"
OUTPUT_CSV = "bedrock_pricing.csv"

INPUT_PRICE_KEYS = ("Price per 1M input tokens", "Prce per 1M input tokens")  # second is a source-side typo
OUTPUT_PRICE_KEYS = ("Price per 1M output tokens",)

PROVIDER_SLUG = {
    "Amazon": "amazon",
    "AI21 Labs": "ai21",
    "Anthropic": "anthropic",
    "Cohere": "cohere",
    "Custom Model Import": "custom",
    "DeepSeek": "deepseek",
    "Google": "google",
    "Luma AI": "luma",
    "Meta": "meta",
    "MiniMax AI": "minimax",
    "Mistral AI": "mistral",
    "Moonshot AI": "moonshotai",
    "NVIDIA": "nvidia",
    "OpenAI OSS Models": "openai",
    "Qwen": "qwen",
    "Stability AI": "stability",
    "TwelveLabs": "twelvelabs",
    "Writer": "writer",
    "Z AI": "zai",
}

# Bedrock's cross-region inference uses prefixes like `global.`, `us.`, `eu.`, `apac.`
# We can only confidently set `global.` from the pricing page; Geo/In-region rows
# don't carry the specific region prefix in the source.
CATEGORY_PREFIX = {
    "Global Cross-region Inference": "global",
    "Global Cross region Inference": "global",  # source-side typo variant
}


def normalize_model(name, provider_slug):
    name = unicodedata.normalize("NFKC", name)
    # Drop only dated legacy notes — keep parens that carry real variant info like (70B) or (w/ latency optimized inference)
    name = re.sub(r"\s*\([^)]*(?:Effective|Public Extended Access)[^)]*\)", "", name, flags=re.IGNORECASE)
    # Drop trailing markers like asterisks or footnote refs
    name = re.sub(r"[*†‡]+", "", name)
    name = name.strip().lower()
    # Amazon's pricing page repeats the provider name ("Amazon Nova ...") whereas
    # real Bedrock IDs drop it (`amazon.nova-pro-v1:0`). Other providers don't
    # have this dup, and stripping would corrupt them (e.g. mistral.mistral-large).
    if provider_slug == "amazon" and name.startswith("amazon "):
        name = name[len("amazon "):]
    # Replace dots, spaces, slashes with single hyphens; preserve alphanumerics
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def slug_provider(provider):
    if provider in PROVIDER_SLUG:
        return PROVIDER_SLUG[provider]
    return re.sub(r"[^a-z0-9]+", "", provider.lower())


def build_model_id(provider, model, category):
    prov = slug_provider(provider)
    mdl = normalize_model(model, prov)
    prefix = CATEGORY_PREFIX.get(category)
    return f"{prefix}.{prov}.{mdl}" if prefix else f"{prov}.{mdl}"


def parse_price(s):
    if not isinstance(s, str):
        return None
    s = unicodedata.normalize("NFKC", s).strip()
    if not s or s.upper() in {"N/A", "NA", "-", "—"}:
        return None
    s = s.replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def detect_model(row):
    for k, v in row.items():
        if not isinstance(v, str) or not v.strip():
            continue
        kl = k.lower()
        if kl.endswith(" models") or kl.endswith(" model") or k == "Model Name":
            return v.strip()
    return ""


def main():
    with open(INPUT_JSON, encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for d in data:
        in_price = parse_price(next((d[k] for k in INPUT_PRICE_KEYS if d.get(k)), ""))
        out_price = parse_price(next((d[k] for k in OUTPUT_PRICE_KEYS if d.get(k)), ""))
        # Keep the row if either price is present (e.g. embedding models have no output price)
        if in_price is None and out_price is None:
            continue
        model = detect_model(d)
        if not model:
            continue
        provider = d.get("Provider", "").strip()
        category = d.get("Pricing_Category", "").strip()
        rows.append({
            "model": build_model_id(provider, model, category),
            "pricing_category": category,
            "price_per_1m_input_tokens": in_price if in_price is not None else "",
            "price_per_1m_output_tokens": out_price if out_price is not None else "",
        })

    rows.sort(key=lambda r: (r["model"], r["pricing_category"]))

    fieldnames = ["model", "pricing_category", "price_per_1m_input_tokens", "price_per_1m_output_tokens"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
