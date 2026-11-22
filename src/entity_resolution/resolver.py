import csv
import json
import re
import unicodedata
from pathlib import Path

from rapidfuzz.fuzz import ratio


CANONICAL_SEEDS = [
    ("OpenAI", "https://openai.com"),
    ("Anthropic", "https://www.anthropic.com"),
    ("Google DeepMind", "https://deepmind.google"),
    ("Microsoft", "https://www.microsoft.com"),
    ("Meta AI", "https://ai.meta.com"),
    ("NVIDIA", "https://www.nvidia.com"),
    ("Amazon Web Services", "https://aws.amazon.com"),
    ("Apple", "https://www.apple.com"),
    ("xAI", "https://x.ai"),
    ("Mistral AI", "https://mistral.ai"),
    ("Cohere", "https://cohere.com"),
    ("Stability AI", "https://stability.ai"),
    ("Hugging Face", "https://huggingface.co"),
    ("Databricks", "https://www.databricks.com"),
    ("Scale AI", "https://scale.com"),
    ("Perplexity", "https://www.perplexity.ai"),
    ("Character.AI", "https://character.ai"),
    ("Midjourney", "https://www.midjourney.com"),
    ("Runway", "https://runwayml.com"),
    ("ElevenLabs", "https://elevenlabs.io"),
    ("Jasper", "https://www.jasper.ai"),
    ("Copy.ai", "https://www.copy.ai"),
    ("Writer", "https://writer.com"),
    ("Grammarly", "https://www.grammarly.com"),
    ("Notion", "https://www.notion.com"),
    ("Canva", "https://www.canva.com"),
    ("Adobe", "https://www.adobe.com"),
    ("Salesforce", "https://www.salesforce.com"),
    ("Palantir", "https://www.palantir.com"),
    ("Snowflake", "https://www.snowflake.com"),
    ("Datadog", "https://www.datadog.com"),
    ("ServiceNow", "https://www.servicenow.com"),
    ("UiPath", "https://www.uipath.com"),
    ("Automation Anywhere", "https://www.automationanywhere.com"),
    ("Sakana AI", "https://sakana.ai"),
    ("Aleph Alpha", "https://aleph-alpha.com"),
    ("Synthesia", "https://www.synthesia.io"),
    ("DeepL", "https://www.deepl.com"),
    ("Ada", "https://www.ada.cx"),
    ("HubSpot", "https://www.hubspot.com"),
    ("IBM", "https://www.ibm.com"),
    ("Oracle", "https://www.oracle.com"),
    ("SAP", "https://www.sap.com"),
    ("Tesla", "https://www.tesla.com"),
    ("Nuro", "https://nuro.ai"),
    ("Cruise", "https://www.getcruise.com"),
    ("Waymo", "https://waymo.com"),
    ("Figure", "https://www.figure.ai"),
    ("Recursion", "https://www.recursion.com"),
    ("Insilico Medicine", "https://insilico.com"),
]


def normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def resolve_entities(records: list[dict], name_key: str, source_key: str, source_label: str) -> list[dict]:
    output = []
    for record in records:
        name = str(record.get(name_key) or "")
        normalized = normalize_name(name)
        best = None
        best_score = -1.0
        for canonical, domain in CANONICAL_SEEDS:
            score = ratio(normalized, normalize_name(canonical)) / 100.0
            if score > best_score:
                best_score = score
                best = (canonical, domain)
        if best and best_score >= 0.95:
            decision, confidence = "EXACT_OR_CANONICAL_MATCH", best_score
        elif best and best_score >= 0.80:
            decision, confidence = "NEAR_MATCH_REVIEW", best_score
        else:
            decision, confidence = "UNMATCHED", best_score
        output.append({
            "sourceDataset": source_label,
            "sourceRecordName": name,
            "sourceUrl": record.get(source_key),
            "normalizedName": normalized,
            "canonicalEntity": best[0] if decision == "EXACT_OR_CANONICAL_MATCH" else "",
            "canonicalWebsite": best[1] if decision == "EXACT_OR_CANONICAL_MATCH" else "",
            "matchDecision": decision,
            "confidence": round(confidence, 4),
        })
    return output