"""
ai_service.py
─────────────
Purpose:
    Handles LLM query orchestration and prompt generation via Groq API.

Use Cases:
    - Generates transformation python scripts for incoming files based on target schema.
    - Orchestrates schema drift detection and provides reasoning.
"""

import json
import asyncio
import re
from groq import Groq
from app.core.config import settings
import traceback
from typing import Optional

client = Groq(api_key=settings.GROQ_API_KEY)
MODEL = "llama-3.3-70b-versatile"


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences (```json ... ``` or ``` ... ```) from LLM output."""
    stripped = text.strip()
    # Match ```json ... ``` or ```JSON ... ``` or ``` ... ```
    m = re.match(r"^```(?:json|JSON)?\s*\n?(.*?)```\s*$", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()
    return stripped

async def generate_pipeline_proposal(
    incoming_schema: dict,
    target_schema: dict,
    sample_rows: list[dict],
    table_metadata: dict,
    context_bundle: Optional[dict] = None,   # STAGE 3: Phase 2 context injection
    retry_msg: str = None,
    description_md: Optional[str] = None
) -> dict:

    system_prompt = """You are a data engineering AI. Your job is to analyze schema 
differences between an incoming dataset and a target database table, 
then generate a safe Python transformation plan.

You must respond with ONLY valid JSON. No explanation text before or 
after. No markdown code fences. Raw JSON only.

Response format:
{
  "drift_detected": [
    {
      "column": "string",
      "issue_type": "RENAME|EXTRA_COLUMN|TYPE_MISMATCH|NULL_VIOLATION|MISSING_REQUIRED",
      "source_value": "string - what the incoming data has",
      "target_expectation": "string - what the target expects",
      "suggested_action": "string - plain english action",
      "severity": "LOW|MEDIUM|HIGH"
    }
  ],
  "proposed_steps": ["string - plain english step 1", "step 2"],
  "generated_code": "string - complete valid Python function",
  "confidence_score": 0.0-1.0,
  "pii_columns_found": ["col1", "col2"],
  "reasoning": "string - 2-3 sentences explaining in non-technical, business-friendly terms what was transformed and why (WITHOUT any references to internal JSON structure, regex, code syntax, programming languages, database columns, or technical jargon).",
  "gateway_recommendation": "AUTO_LINK|SCHEMA_EVOLUTION|CONFLICT",
  "suggested_skills_to_add": [
    {
      "skill_name": "string (lowercase_with_underscores, e.g., format_zipcode)",
      "description": "string (clear description of what this skill does and why it is recommended)",
      "category": "string (DATA_CLEANING|SECURITY|SCHEMA_EVOLUTION|DATETIME_STANDARDIZATION|VALIDATION)"
    }
  ],
  "enrichment_applied": ["string - list of enrichment rules applied"]
}

Rules for reasoning:
- Explain decisions in non-technical, business-friendly terms (e.g., "The order_amount column was renamed to amount_usd to match the target schema standard for dollar amounts" or "Customer email values were hashed to protect sensitive data").
- Do NOT mention code, syntax, regex, data types, database columns, JSON keys/structures, or programming concepts. Focus on what was transformed and why it makes business sense.

Rules for gateway_recommendation:
- AUTO_LINK: all columns match cleanly, zero or trivial drift 
  (only extra nullable columns), confidence > 0.92
- SCHEMA_EVOLUTION: detectable drift with clear fix available, 
  confidence > 0.75
- CONFLICT: type mismatch on required columns, missing required 
  columns, or confidence <= 0.75

Rules for generated_code:
- Must be a complete Python function: def transform(df: pd.DataFrame) -> pd.DataFrame:
- Import nothing inside the function, assume pandas as pd and hashlib are available
- Must handle every drift item detected
- Must mask PII columns: replace value with SHA256 hash
- Must add processed_at column: pd.Timestamp.now()
- Return the transformed DataFrame

TRANSFORMATION CODE RULES — MUST FOLLOW:

The generated `transform` function MUST only use the following pandas operations:
  - Column renaming:       df.rename(columns={...})
  - Column dropping:       df.drop(columns=[...])
  - Null filling:          df[col].fillna(value)
  - Type casting:          df[col].astype(dtype)
  - String normalization:  df[col].str.strip(), df[col].str.lower()
  - Date parsing:          pd.to_datetime(df[col])
  - Value replacement:     df[col].replace({...})
  - Constant assignment:   df[col] = value
  - Conditional mapping:   df[col].map({...}) or np.where(...)

The generated `transform` function MUST NEVER use:
  - Any aggregation or statistical method: quantile(), mean(), median(), 
    std(), var(), describe(), corr(), cov(), skew(), kurt(), rank()
  - Any grouping operation: groupby(), resample(), pivot_table(), crosstab()
  - Any join/merge operation: merge(), join(), concat()
  - Any operation that changes the number of rows
  - Any operation that requires numeric dtype on a column that has not been 
    explicitly cast to numeric first

The output DataFrame MUST have exactly the same number of rows as the input.
The function signature MUST be: def transform(df: pd.DataFrame) -> pd.DataFrame

Rules for generated_code (ENRICHMENT):
- If numeric columns exist, add an `amount_tier` derived column classifying values as 'low' (< 25th pct), 'medium', and 'high' (> 75th pct).
- Flag potential duplicate rows by adding a `is_potential_duplicate` boolean column (True if all non-ID columns match another row).
- Flag numeric outliers by adding `amount_outlier` boolean column for values beyond 1.5× IQR (matching the target database schema).
- Record any applied enrichment rules in the `enrichment_applied` field (e.g., ["amount_tier", "outlier_detection", "duplicate_flagging"]).

Rules for suggested_skills_to_add:
- If the registered skills (provided in ORGANIZATIONAL KNOWLEDGE CONTEXT) are not sufficient or available to handle the detected schema drift, and you had to write custom Python logic for it, suggest 1 or more reusable skills that should be added to the registry for this task.
- If the registered skills already cover everything, return an empty list `[]`."""

    # ── STAGE 3: Build organizational context section for Phase 2 ──────────
    context_section = ""
    if context_bundle:
        related_skills = context_bundle.get("related_skills", [])
        related_entities = context_bundle.get("related_entities", [])
        dependencies = context_bundle.get("dependencies", [])
        business_context = context_bundle.get("business_context", [])
        pii_columns_from_graph = context_bundle.get("pii_columns", [])

        skills_block = ""
        for sk in related_skills:
            skills_block += f"\n  - {sk['name']} ({sk['category']}): {sk['description']}"

        context_section = f"""

ORGANIZATIONAL KNOWLEDGE CONTEXT:
Known PII columns in this table (from graph): {', '.join(pii_columns_from_graph) if pii_columns_from_graph else 'none detected'}
Related entities: {', '.join(e['name'] for e in related_entities) if related_entities else 'none'}
Dependencies (tables this table reads from): {', '.join(d['name'] for d in dependencies) if dependencies else 'none'}
Business KPI impact: {'; '.join(business_context) if business_context else 'not specified'}
Registered skills that may apply:{skills_block if skills_block else ' none'}

When generating the transformation:
- Prefer strategies consistent with the registered skills above
- Always mask the PII columns listed above, even if they appear safe
- Be aware this table feeds the business KPIs listed above — schema changes have downstream impact
"""
    # ── End context section ───────────────────────────────────────────────

    # ── User-provided dataset description ────────────────────────────────
    description_section = ""
    if description_md:
        description_section = f"\nINCOMING DATASET DESCRIPTION (provided by user):\n{description_md}\n"

    user_message = f"""TARGET TABLE SCHEMA:
{json.dumps(target_schema, indent=2)}

INCOMING DATA SCHEMA (columns detected):
{json.dumps(incoming_schema, indent=2)}
{description_section}
SAMPLE ROWS (first 5):
{json.dumps(sample_rows, indent=2)}

TABLE BUSINESS CONTEXT:
{json.dumps(table_metadata, indent=2)}
{context_section}
Remember: only column mapping, renaming, type casting, null filling, and 
string normalization. No statistical operations. No aggregations. No joins.
Analyze the drift and generate the transformation plan."""

    if retry_msg:
        user_message += f"\n\n{retry_msg}"

    if settings.MOCK_AI:
        # Check incoming schema to determine test case
        cols = list(incoming_schema.keys())
        if "amount_usd" not in cols:
            # SCHEMA_EVOLUTION mock
            generated_code = (
                "def transform(df: pd.DataFrame) -> pd.DataFrame:\n"
                "    import hashlib\n"
                "    df = df.rename(columns={\"order_amount\": \"amount_usd\"})\n"
                "    if \"discount_code\" in df.columns:\n"
                "        df = df.drop(columns=[\"discount_code\"])\n"
                "    df[\"order_status\"] = df[\"order_status\"].fillna(\"completed\")\n"
                "    df[\"customer_email\"] = df[\"customer_email\"].apply(lambda x: hashlib.sha256(str(x).encode()).hexdigest())\n"
                "    df[\"amount_usd\"] = df[\"amount_usd\"].astype(str).str.replace(r'[^\\d\\.]', '', regex=True)\n"
                "    df[\"amount_usd\"] = pd.to_numeric(df[\"amount_usd\"], errors='coerce')\n"
                "    _sv = df[\"amount_usd\"].dropna().sort_values().reset_index(drop=True)\n"
                "    _n = len(_sv)\n"
                "    q25 = float(_sv.iloc[int(_n * 0.25)]) if _n > 0 else 0.0\n"
                "    q75 = float(_sv.iloc[int(_n * 0.75)]) if _n > 0 else 0.0\n"
                "    df[\"amount_tier\"] = pd.cut(df[\"amount_usd\"], bins=[-float('inf'), q25, q75, float('inf')], labels=[\"low\", \"medium\", \"high\"]).astype(str)\n"
                "    iqr = float(q75 - q25)\n"
                "    df[\"amount_outlier\"] = (df[\"amount_usd\"] < (q25 - 1.5 * iqr)) | (df[\"amount_usd\"] > (q75 + 1.5 * iqr))\n"
                "    dup_cols = [c for c in df.columns if c != \"order_id\" and c not in [\"processed_at\", \"amount_tier\", \"amount_outlier\"]]\n"
                "    df[\"is_potential_duplicate\"] = df.duplicated(subset=dup_cols, keep=False)\n"
                "    df[\"processed_at\"] = pd.Timestamp.now()\n"
                "    df[\"created_at\"] = pd.to_datetime(df[\"created_at\"])\n"
                "    return df"
            )
            content = json.dumps({
                "drift_detected": [
                    {"column": "order_amount", "issue_type": "RENAME", "source_value": "order_amount", "target_expectation": "amount_usd", "suggested_action": "rename to amount_usd", "severity": "LOW"},
                    {"column": "discount_code", "issue_type": "EXTRA_COLUMN", "source_value": "discount_code", "target_expectation": "none", "suggested_action": "drop column", "severity": "LOW"},
                    {"column": "order_status", "issue_type": "NULL_VIOLATION", "source_value": "null", "target_expectation": "not null", "suggested_action": "fill nulls", "severity": "LOW"}
                ],
                "proposed_steps": ["Rename order_amount to amount_usd", "Drop discount_code column", "Fill null statuses", "Enrich with amount_tier", "Enrich with amount_outlier", "Enrich with duplicate_detection"],
                "generated_code": generated_code,
                "confidence_score": 0.85,
                "pii_columns_found": ["customer_email"],
                "reasoning": "Standardized currency amount by renaming and cleaning values, masked customer email PII using SHA-256, and auto-enriched with amount tier classification, amount outlier flags, and near-duplicate markers.",
                "gateway_recommendation": "SCHEMA_EVOLUTION",
                "suggested_skills_to_add": [
                    {
                        "skill_name": "normalize_currency",
                        "description": "Standardize currencies to standard currency values and format decimal representation.",
                        "category": "DATA_CLEANING"
                    }
                ],
                "enrichment_applied": ["amount_tier", "outlier_detection", "duplicate_flagging"],
                "context_aware": context_bundle is not None,
            })
        elif "customer_email" not in cols:
            # CONFLICT mock
            generated_code = (
                "def transform(df: pd.DataFrame) -> pd.DataFrame:\n"
                "    # Attempt basic enrichment\n"
                "    df[\"amount_usd\"] = pd.to_numeric(df[\"amount_usd\"], errors='coerce')\n"
                "    _sv = df[\"amount_usd\"].dropna().sort_values().reset_index(drop=True)\n"
                "    _n = len(_sv)\n"
                "    q25 = float(_sv.iloc[int(_n * 0.25)]) if _n > 0 else 0.0\n"
                "    q75 = float(_sv.iloc[int(_n * 0.75)]) if _n > 0 else 0.0\n"
                "    df[\"amount_tier\"] = pd.cut(df[\"amount_usd\"], bins=[-float('inf'), q25, q75, float('inf')], labels=[\"low\", \"medium\", \"high\"]).astype(str)\n"
                "    iqr = float(q75 - q25)\n"
                "    df[\"amount_outlier\"] = (df[\"amount_usd\"] < (q25 - 1.5 * iqr)) | (df[\"amount_usd\"] > (q75 + 1.5 * iqr))\n"
                "    dup_cols = [c for c in df.columns if c != \"order_id\" and c not in [\"processed_at\", \"amount_tier\", \"amount_outlier\"]]\n"
                "    df[\"is_potential_duplicate\"] = df.duplicated(subset=dup_cols, keep=False)\n"
                "    df[\"processed_at\"] = pd.Timestamp.now()\n"
                "    df[\"created_at\"] = pd.to_datetime(df[\"created_at\"])\n"
                "    return df"
            )
            content = json.dumps({
                "drift_detected": [
                    {"column": "order_id", "issue_type": "TYPE_MISMATCH", "source_value": "string", "target_expectation": "integer", "suggested_action": "cannot convert safely", "severity": "HIGH"},
                    {"column": "customer_email", "issue_type": "MISSING_REQUIRED", "source_value": "missing", "target_expectation": "string", "suggested_action": "missing required column", "severity": "HIGH"}
                ],
                "proposed_steps": ["Fail due to validation errors"],
                "generated_code": generated_code,
                "confidence_score": 0.60,
                "pii_columns_found": [],
                "reasoning": "Failed to map order ID format and detected missing required customer email column. Potential enrichment applied to available order amounts.",
                "gateway_recommendation": "CONFLICT",
                "suggested_skills_to_add": [],
                "enrichment_applied": ["amount_tier", "outlier_detection", "duplicate_flagging"],
                "context_aware": context_bundle is not None,
            })
        else:
            # AUTO_LINK mock
            generated_code = (
                "def transform(df: pd.DataFrame) -> pd.DataFrame:\n"
                "    import hashlib\n"
                "    df[\"customer_email\"] = df[\"customer_email\"].apply(lambda x: hashlib.sha256(str(x).encode()).hexdigest())\n"
                "    df[\"amount_usd\"] = df[\"amount_usd\"].astype(float)\n"
                "    _sv = df[\"amount_usd\"].dropna().sort_values().reset_index(drop=True)\n"
                "    _n = len(_sv)\n"
                "    q25 = float(_sv.iloc[int(_n * 0.25)]) if _n > 0 else 0.0\n"
                "    q75 = float(_sv.iloc[int(_n * 0.75)]) if _n > 0 else 0.0\n"
                "    df[\"amount_tier\"] = pd.cut(df[\"amount_usd\"], bins=[-float('inf'), q25, q75, float('inf')], labels=[\"low\", \"medium\", \"high\"]).astype(str)\n"
                "    iqr = float(q75 - q25)\n"
                "    df[\"amount_outlier\"] = (df[\"amount_usd\"] < (q25 - 1.5 * iqr)) | (df[\"amount_usd\"] > (q75 + 1.5 * iqr))\n"
                "    dup_cols = [c for c in df.columns if c != \"order_id\" and c not in [\"processed_at\", \"amount_tier\", \"amount_outlier\"]]\n"
                "    df[\"is_potential_duplicate\"] = df.duplicated(subset=dup_cols, keep=False)\n"
                "    df[\"processed_at\"] = pd.Timestamp.now()\n"
                "    df[\"created_at\"] = pd.to_datetime(df[\"created_at\"])\n"
                "    return df"
            )
            content = json.dumps({
                "drift_detected": [],
                "proposed_steps": ["Identity transform with enrichment"],
                "generated_code": generated_code,
                "confidence_score": 0.95,
                "pii_columns_found": ["customer_email"],
                "reasoning": "Masked customer email PII using SHA-256 and enriched with amount tier classification, amount outlier flags, and potential duplicate markers.",
                "gateway_recommendation": "AUTO_LINK",
                "suggested_skills_to_add": [],
                "enrichment_applied": ["amount_tier", "outlier_detection", "duplicate_flagging"],
                "context_aware": context_bundle is not None,
            })
    else:
        max_retries = 3
        delay = 1.0
        for attempt in range(max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.1,
                    max_tokens=2000
                )
                content = response.choices[0].message.content
                break
            except Exception as e:
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    raise e

    try:
        content = _strip_code_fences(content)
        parsed = json.loads(content)
        return {
            "raw_response": content,
            "prompt_sent": user_message,
            "model_used": MODEL,
            "parsed": parsed
        }
    except json.JSONDecodeError:
        if retry_msg is None:
            return await generate_pipeline_proposal(
                incoming_schema, target_schema, sample_rows, table_metadata,
                context_bundle=context_bundle,
                retry_msg="Your previous response was not valid JSON. Respond with ONLY the JSON object, no other text.",
                description_md=description_md
            )
        else:
            raise Exception(f"Failed to parse JSON from AI response: {content}")


async def generate_skill_script(skill_name: str, description: str, category: str) -> str:
    """
    Generate Python transformation code for a registered skill.
    Uses the Groq completion API or returns mock templates if settings.MOCK_AI is active.
    """
    if settings.MOCK_AI:
        if skill_name == "normalize_currency":
            return '''def transform(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    # Standardize currencies to standard currency values and format decimal representation.
    columns = config.get("columns", [])
    if not columns:
        columns = [c for c in df.columns if "amount" in c.lower() or "price" in c.lower() or "currency" in c.lower()]
    for col in columns:
        if col in df.columns:
            # Strip currency symbols and commas, then convert to numeric
            df[col] = df[col].astype(str).str.replace(r'[^\d\.]', '', regex=True)
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df
'''
        else:
            return f'''def transform(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    # Implement: {description}
    columns = config.get("columns", [])
    for col in columns:
        if col in df.columns:
            pass
    return df
'''

    system_prompt = (
        "You are an expert data engineer. Write a python function that implements a pandas data transformation skill.\\n"
        "The function MUST follow this exact signature:\\n"
        "def transform(df: pd.DataFrame, config: dict) -> pd.DataFrame:\\n"
        "    ...\\n\\n"
        "Rules:\\n"
        "1. Write clean, robust pandas code that implements the requested skill.\\n"
        "2. The 'config' dictionary can contain parameters like 'columns' (list of columns to apply to) and other parameters.\\n"
        "3. Assume pandas is imported as pd in the environment. Do not write 'import pandas as pd' inside the function, though you can use 'pd.' directly. Do not import any other libraries unless absolutely necessary (like re, math).\\n"
        "4. Do NOT use unsafe features (e.g. os, sys, eval, exec, subprocess, open).\\n"
        "5. The output must be ONLY the raw Python code. Do not wrap the code in markdown code fences or backticks (e.g., do not use ```python). No explanation text before or after."
    )
    user_msg = f"Skill Name: {skill_name}\\nCategory: {category}\\nDescription: {description}\\nGenerate the transform function."

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.1,
            max_tokens=1500
        )
        code = response.choices[0].message.content.strip()
        # Strip code blocks if LLM still returned them
        if code.startswith("```python"):
            code = code[9:]
        elif code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        return code.strip()
    except Exception as e:
        # Fallback to simple template on failure
        return f'''def transform(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    # Fallback template for {skill_name}
    # Description: {description}
    columns = config.get("columns", [])
    for col in columns:
        if col in df.columns:
            pass
    return df
'''

