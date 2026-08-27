"""Field registry + seeded taxonomies. This IS the quality-rules table, as code."""
from __future__ import annotations

# --- Seeded reference data (deterministic, never learned) ---

COUNTRY_MAP = {
    "de": "Germany", "deu": "Germany", "deutschland": "Germany", "germany": "Germany",
    "us": "United States", "usa": "United States", "united states": "United States",
    "uk": "United Kingdom", "gb": "United Kingdom", "united kingdom": "United Kingdom",
    "fr": "France", "france": "France", "nl": "Netherlands", "netherlands": "Netherlands",
    "se": "Sweden", "swe": "Sweden", "sweden": "Sweden",
}

DIAL_CODES = {  # country -> E.164 country calling code
    "Germany": "49", "United States": "1", "United Kingdom": "44",
    "France": "33", "Netherlands": "31", "Sweden": "46",
}

# Mock company-name -> domain resolution (Clearbit name-to-domain style). Lets us
# enrich a lead that arrived with a personal email but a known company name.
NAME_TO_DOMAIN = {
    "loyal nordic": "loyalnordic.se",
    "loyal nordic group": "loyalnordic.se",
    "acme commerce": "acme-commerce.com",
    "shopnord": "shopnord.de",
}

VERTICALS = {"Retail", "Ecommerce", "Travel", "Fintech", "SaaS", "Telco", "Gaming"}

# Seeded industry aliases (clear, known). The fuzzy tail is left to the LLM.
INDUSTRY_SEED_ALIASES = {
    "e-commerce": "Ecommerce", "e commerce": "Ecommerce", "online retail": "Ecommerce",
    "retailer": "Retail", "financial services": "Fintech",
}

PLATFORM_ALIASES = {
    "sfcc": "Salesforce Commerce Cloud", "salesforce commerce": "Salesforce Commerce Cloud",
    "shopify plus": "Shopify", "commerce tools": "commercetools", "sap hybris": "SAP Commerce",
    # lowercase tech slugs as real providers (e.g. Clearbit tech array) return them
    "shopify": "Shopify", "commercetools": "commercetools", "magento": "Magento",
    "bigcommerce": "BigCommerce", "sap commerce": "SAP Commerce", "custom": "custom",
}
PLATFORM_VOCAB = {
    "Shopify", "commercetools", "Salesforce Commerce Cloud", "SAP Commerce",
    "Magento", "BigCommerce", "custom",
}

FUNDING_STAGES = {"pre_seed", "seed", "series_a", "series_b", "series_c", "series_d", "public"}
FUNDING_ALIASES = {
    "series a": "series_a", "a": "series_a", "series b": "series_b", "b": "series_b",
    "series c": "series_c", "seed round": "seed",
}

# Seniority/function taxonomy for decision-maker detection (Talon ICP buyers).
SENIORITY_SEED = {
    "vp growth": "growth_leader", "head of growth": "growth_leader",
    "head of crm": "crm_leader", "head of loyalty": "loyalty_leader",
    "cto": "eng_leader", "vp engineering": "eng_leader",
}

# Domains we treat as personal/free -> not enrichable at company level.
FREE_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "gmx.de", "web.de"}
ROLE_LOCALPARTS = {"info", "sales", "support", "contact", "hello", "admin", "noreply"}

# Domains with a valid MX record (stubbed: real system does a DNS lookup).
KNOWN_MX = {
    "acme-commerce.com", "traveltech.io", "shopnord.de", "fastcart.io",
    "loyalnordic.se", "bahnpay.de", "nordicliving.se", "altbau-grocers.de",
}

# --- Field registry ---
# providers listed primary-first; that ordering drives selection + waterfall.
FIELD_REGISTRY: dict[str, dict] = {
    # company-level
    "industry":            {"level": "company", "needed": True,  "providers": ["clearbit", "crunchbase"]},
    "employee_count":      {"level": "company", "needed": True,  "providers": ["clearbit", "zoominfo"]},
    "annual_revenue_band": {"level": "company", "needed": False, "providers": ["clearbit", "crunchbase"]},
    "country":             {"level": "company", "needed": True,  "providers": ["clearbit", "zoominfo"]},
    "ecommerce_platform":  {"level": "company", "needed": True,  "providers": ["clearbit"]},
    "company_email":       {"level": "company", "needed": True,  "providers": ["clearbit", "zoominfo", "apollo"]},
    "funding_stage":       {"level": "company", "needed": False, "providers": ["crunchbase", "clearbit"]},
    "total_raised_usd":    {"level": "company", "needed": False, "providers": ["crunchbase"]},
    # contact-level
    "contact_email":       {"level": "contact", "needed": True,  "providers": ["zoominfo", "apollo"]},
    "contact_phone":       {"level": "contact", "needed": True,  "providers": ["zoominfo", "apollo"]},
    "seniority_function":  {"level": "contact", "needed": True,  "providers": ["zoominfo", "apollo"]},
    "linkedin_url":        {"level": "contact", "needed": False, "providers": ["apollo", "zoominfo"]},
}

PLACEHOLDERS = {"", "n/a", "na", "-", "unknown", "none", "null", "tbd"}
