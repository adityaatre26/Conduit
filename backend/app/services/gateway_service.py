"""
gateway_service.py
──────────────────
Purpose:
    Implements the gatekeeper-classifier logic.

Use Cases:
    - Inspects AI recommendations and overrides them to CONFLICT or SCHEMA_EVOLUTION 
      based on deterministic rules (confidence score, severity levels, null violations).
"""

def classify_gateway_state(
    ai_recommendation: str,
    drift_items: list[dict],
    confidence_score: float
) -> str:
    try:
        score = float(confidence_score) if confidence_score is not None else 0.0
    except (ValueError, TypeError):
        score = 0.0

    # Force CONFLICT for low confidence
    if score < 0.70:
        return "CONFLICT"

    # Force CONFLICT for critical mismatches
    for item in drift_items:
        if not isinstance(item, dict):
            continue
        if item.get("severity") == "HIGH" and item.get("issue_type") == "TYPE_MISMATCH":
            return "CONFLICT"
        if item.get("issue_type") == "MISSING_REQUIRED":
            return "CONFLICT"

    # Force SCHEMA_EVOLUTION
    if len(drift_items) >= 3:
        return "SCHEMA_EVOLUTION"
    if 0.70 <= score <= 0.88:
        return "SCHEMA_EVOLUTION"
    for item in drift_items:
        if not isinstance(item, dict):
            continue
        if item.get("severity") == "MEDIUM":
            return "SCHEMA_EVOLUTION"

    # Normalize/validate AI recommendation
    rec = (ai_recommendation or "").upper()
    if rec not in ["AUTO_LINK", "SCHEMA_EVOLUTION", "CONFLICT"]:
        return "CONFLICT" if score <= 0.75 else "SCHEMA_EVOLUTION"

    return rec
