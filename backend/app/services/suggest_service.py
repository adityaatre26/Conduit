"""
suggest_service.py
──────────────────
Purpose:
    Provides AI suggestions for new skills based on observed anomalies.
"""

import json
import re
import pandas as pd
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import mcp_service
from app.core.config import settings
from app.services.ai_service import client, MODEL

def compute_jaccard_similarity(incoming: List[str], target: List[str]) -> float:
    set_inc = set(c.lower() for c in incoming)
    set_tgt = set(c.lower() for c in target)
    if not set_inc or not set_tgt:
        return 0.0
    intersection = len(set_inc.intersection(set_tgt))
    union = len(set_inc.union(set_tgt))
    return intersection / union

def profile_incoming_data(df: pd.DataFrame) -> Dict[str, Any]:
    profile = {}
    for col in df.columns:
        series = df[col]
        # Inferred type
        dtype = str(series.dtype)
        
        # Sample values (up to 3 unique, non-null, converted to string)
        non_null_samples = series.dropna().unique()
        samples = [str(x) for x in non_null_samples[:3]]
        
        # Null ratio
        null_ratio = float(series.isnull().mean())
        
        # Type classification and patterns
        inferred_type = "string"
        if pd.api.types.is_numeric_dtype(series):
            if pd.api.types.is_integer_dtype(series):
                inferred_type = "integer"
            else:
                inferred_type = "float"
        elif pd.api.types.is_datetime64_any_dtype(series):
            inferred_type = "datetime"
        else:
            # Let's inspect values to see if they match patterns
            sample_str = " ".join(samples).lower()
            if "@" in sample_str and "." in sample_str:
                inferred_type = "email"
            elif any(re.match(r"^\d{4}-\d{2}-\d{2}", s) for s in samples):
                inferred_type = "datetime"
            elif any(s.strip().lower() in ["true", "false", "yes", "no", "1", "0"] for s in samples) and len(non_null_samples) <= 2:
                inferred_type = "boolean"
        
        profile[col] = {
            "dtype": dtype,
            "inferred_type": inferred_type,
            "null_ratio": null_ratio,
            "samples": samples
        }
    return profile

def compute_profile_match(incoming_profile: Dict[str, Any], target_columns: List[Dict[str, Any]]) -> float:
    # Compare inferred types and samples with target columns
    if not incoming_profile or not target_columns:
        return 0.0
    
    score = 0.0
    matched_count = 0
    
    target_by_name = {col["column_name"].lower(): col for col in target_columns}
    
    for inc_col, info in incoming_profile.items():
        inc_lower = inc_col.lower()
        if inc_lower in target_by_name:
            matched_count += 1
            tgt_col = target_by_name[inc_lower]
            
            # 1. Type compatibility
            tgt_type = tgt_col["data_type"].lower()
            inc_type = info["inferred_type"]
            
            type_match = 0.5
            if inc_type == tgt_type:
                type_match = 1.0
            elif inc_type in ["integer", "float"] and tgt_type in ["int", "integer", "decimal", "float", "numeric", "double"]:
                type_match = 0.9
            elif inc_type == "email" and tgt_type in ["varchar", "string", "text"]:
                type_match = 1.0
            elif inc_type == "datetime" and tgt_type in ["timestamp", "date", "datetime"]:
                type_match = 1.0
            
            # 2. Sample values heuristic (e.g. if target has sample values, check if any overlap or resemble)
            sample_match = 0.0
            tgt_samples = [str(s).lower() for s in tgt_col.get("sample_values", []) or []]
            inc_samples = [str(s).lower() for s in info["samples"]]
            if tgt_samples and inc_samples:
                overlap = len(set(tgt_samples).intersection(set(inc_samples)))
                if overlap > 0:
                    sample_match = 1.0
                else:
                    sample_match = 0.5
            else:
                sample_match = 0.8  # Neutral if no sample values to compare
                
            score += (type_match * 0.6 + sample_match * 0.4)
            
    if matched_count == 0:
        return 0.0
    
    # Normalize by the number of matched columns and target columns
    precision = score / matched_count if matched_count > 0 else 0
    recall = matched_count / len(target_columns) if target_columns else 0
    if precision + recall > 0:
        return 2 * (precision * recall) / (precision + recall)
    return 0.0

async def get_llm_suggestions(
    incoming_profile: Dict[str, Any],
    all_table_schemas: List[Dict[str, Any]]
) -> Dict[str, Any]:
    if settings.MOCK_AI:
        # Mock suggestion based on incoming columns
        incoming_cols = list(incoming_profile.keys())
        if "order_amount" in incoming_cols or "amount_usd" in incoming_cols:
            return {
                "data_understanding": "This dataset represents transaction or sales order records containing identifiers, payment amounts, and timestamps.",
                "suggestions": [
                    {
                        "table_name": "orders_clean",
                        "confidence": 0.95,
                        "reasoning": "The columns clearly represent orders, with identifiers, customer details, and transaction amounts matching the orders_clean table metadata."
                    }
                ]
            }
        return {
            "data_understanding": "Unknown dataset uploaded.",
            "suggestions": []
        }
        
    system_prompt = """You are a database and data engineering expert. 
Your task is to analyze an incoming dataset's profile (column names, inferred data types, sample values) 
and recommend which of the registered target tables in the metadata catalog is the best fit.

You must respond with ONLY valid JSON. No explanations, no markdown fences. Raw JSON only.

Response format:
{
  "data_understanding": "A 1-2 sentence description of what this incoming data represents.",
  "suggestions": [
    {
      "table_name": "string",
      "confidence": 0.0-1.0,
      "reasoning": "1-2 sentences explaining why this data fits this target table, mentioning semantic matches."
    }
  ]
}
"""

    user_message = f"""INCOMING DATA PROFILE:
{json.dumps(incoming_profile, indent=2)}

REGISTERED TARGET TABLES:
{json.dumps(all_table_schemas, indent=2)}

Recommend the best target table(s) from the registered tables list. Only suggest tables that have a logical relationship/fit with the data.
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1,
            max_tokens=1500
        )
        content = response.choices[0].message.content
        # Strip markdown code fences the LLM may wrap around JSON
        import re
        stripped = content.strip()
        m = re.match(r"^```(?:json|JSON)?\s*\n?(.*?)```\s*$", stripped, re.DOTALL)
        if m:
            stripped = m.group(1).strip()
        return json.loads(stripped)
    except Exception as e:
        return {
            "data_understanding": "Error invoking AI service for semantic understanding.",
            "suggestions": []
        }

async def suggest_target_table(df: pd.DataFrame, db: AsyncSession) -> Dict[str, Any]:
    all_table_schemas = await mcp_service.get_all_table_schemas(db)
    incoming_profile = profile_incoming_data(df)
    incoming_cols = list(df.columns)
    
    structural_suggestions = {}
    for tgt in all_table_schemas:
        tgt_name = tgt["table_name"]
        tgt_cols = [c["column_name"] for c in tgt["columns"]]
        
        col_match_score = compute_jaccard_similarity(incoming_cols, tgt_cols)
        data_profile_score = compute_profile_match(incoming_profile, tgt["columns"])
        
        structural_suggestions[tgt_name] = {
            "col_match_score": col_match_score,
            "data_profile_score": data_profile_score
        }
        
    llm_res = await get_llm_suggestions(incoming_profile, all_table_schemas)
    data_understanding = llm_res.get("data_understanding", "Analyzed incoming columns and data types.")
    llm_suggestions = {s["table_name"]: s for s in llm_res.get("suggestions", [])}
    
    combined = []
    for tgt in all_table_schemas:
        tgt_name = tgt["table_name"]
        struct = structural_suggestions.get(tgt_name, {"col_match_score": 0.0, "data_profile_score": 0.0})
        llm_sug = llm_suggestions.get(tgt_name, {"confidence": 0.0, "reasoning": ""})
        
        col_score = struct["col_match_score"]
        prof_score = struct["data_profile_score"]
        llm_conf = llm_sug["confidence"]
        
        final_score = (col_score * 0.25) + (prof_score * 0.25) + (llm_conf * 0.50)
        
        if final_score > 0.05:
            tgt_cols = {c["column_name"].lower() for c in tgt["columns"]}
            inc_cols_lower = {c.lower() for c in incoming_cols}
            
            matched = list(tgt_cols.intersection(inc_cols_lower))
            matched_orig = [c for c in incoming_cols if c.lower() in matched]
            extra_orig = [c for c in incoming_cols if c.lower() not in tgt_cols]
            missing_orig = [c["column_name"] for c in tgt["columns"] if c["column_name"].lower() not in inc_cols_lower]
            
            combined.append({
                "table_name": tgt_name,
                "final_score": round(final_score, 3),
                "column_match_score": round(col_score, 3),
                "data_profile_score": round(prof_score, 3),
                "llm_confidence": round(llm_conf, 3),
                "llm_reasoning": llm_sug.get("reasoning", "Matched based on structural and type analysis."),
                "matched_columns": matched_orig,
                "missing_columns": missing_orig,
                "extra_columns": extra_orig
            })
            
    combined.sort(key=lambda x: x["final_score"], reverse=True)
    
    return {
        "data_understanding": data_understanding,
        "incoming_columns": incoming_cols,
        "suggestions": combined
    }
