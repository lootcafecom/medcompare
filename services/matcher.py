"""
Medicine Matching Engine — Phase 1
Simple string normalization + fuzzy matching
No AI needed at this stage — handles 90% of cases
"""
import re
from rapidfuzz import fuzz

# Words to remove when normalizing medicine names
REMOVE_WORDS = [
    "tablet", "tablets", "tab", "tabs",
    "capsule", "capsules", "cap", "caps",
    "strip", "strips", "pack", "packs",
    "injection", "syrup", "cream", "gel",
    "ointment", "drops", "solution", "suspension",
    "of", "with", "for", "and", "the",
    "mg", "ml", "mcg", "gm", "gms",
]

def normalize(name: str) -> str:
    """
    Normalize a medicine name for comparison.

    Examples:
    "Dolo 650Mg Strip Of 15 Tablets" → "dolo 650 15"
    "Dolo-650 Tablet 15'S"           → "dolo 650 15"
    "Dolo 650mg Tab"                 → "dolo 650"
    """
    if not name:
        return ""

    name = name.lower()

    # Remove special characters except numbers and letters
    name = re.sub(r"['\-/\\]", " ", name)
    name = re.sub(r"[^a-z0-9\s]", " ", name)

    # Remove stop words
    words = name.split()
    words = [w for w in words if w not in REMOVE_WORDS]

    # Remove standalone numbers that are likely quantity (e.g. "15" in "strip of 15")
    # Keep numbers that are likely strength (e.g. "650" in "Dolo 650")
    # Heuristic: keep numbers > 10 that appear right after medicine name
    cleaned = []
    for i, w in enumerate(words):
        if w.isdigit() and int(w) <= 10 and i > 1:
            continue  # Skip small quantity numbers
        cleaned.append(w)

    name = " ".join(cleaned)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def match_score(name1: str, name2: str) -> float:
    """
    Return similarity score between two medicine names (0-100).
    Uses multiple fuzzy matching strategies and returns the best score.
    """
    n1 = normalize(name1)
    n2 = normalize(name2)

    if not n1 or not n2:
        return 0.0

    # Exact match after normalization
    if n1 == n2:
        return 100.0

    scores = [
        fuzz.ratio(n1, n2),                # Simple character ratio
        fuzz.partial_ratio(n1, n2),        # Best substring match
        fuzz.token_sort_ratio(n1, n2),     # Sort words then compare
        fuzz.token_set_ratio(n1, n2),      # Set-based comparison (best for medicine names)
    ]

    return max(scores)


def is_same_medicine(name1: str, name2: str, threshold: float = 80.0) -> bool:
    """Returns True if two medicine names refer to the same product"""
    return match_score(name1, name2) >= threshold


def group_by_medicine(results: list[dict], query: str, threshold: float = 75.0) -> list[dict]:
    """
    Given results from multiple pharmacies, filter to only keep products
    that actually match the searched medicine.

    Removes irrelevant products that scrapers sometimes return.
    """
    matched = []
    for pharmacy_result in results:
        pharmacy = pharmacy_result.get("pharmacy", "")
        products = pharmacy_result.get("products", [])
        filtered = []
        for product in products:
            name  = product.get("name", "")
            score = match_score(query, name)
            if score >= threshold:
                product["match_score"] = round(score, 1)
                filtered.append(product)
            else:
                # Still include if it's the only result and score > 50
                if len(products) == 1 and score > 50:
                    product["match_score"] = round(score, 1)
                    filtered.append(product)

        # Sort filtered products by match score
        filtered.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        matched.append({**pharmacy_result, "products": filtered})

    return matched


def extract_strength(name: str) -> str:
    """Extract medicine strength from name e.g. '650mg' from 'Dolo 650mg'"""
    m = re.search(r"(\d+\.?\d*)\s*(mg|ml|mcg|gm|iu|%)", name.lower())
    return m.group(0) if m else ""


def extract_salt(name: str) -> str:
    """
    Try to extract active ingredient/salt from name.
    Very basic — just returns normalized first word(s)
    """
    normalized = normalize(name)
    parts = normalized.split()
    # Return first word that is not a number
    for part in parts:
        if not part.isdigit():
            return part
    return ""
