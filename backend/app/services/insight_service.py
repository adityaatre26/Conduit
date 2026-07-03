"""
insight_service.py
──────────────────
Purpose:
    Performs statistical analyses on dataframes to extract insights.

Use Cases:
    - Scans for outliers, anomalies, and duplicate records.
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import InsightRecord

logger = logging.getLogger("conduit.insights")


# ── Statistical analysis helpers ──────────────────────────────────────────


def _compute_stats(df: pd.DataFrame) -> dict:
    """Run basic statistical profiling on the DataFrame."""
    stats: dict = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": {},
    }

    for col in df.columns:
        col_stats: dict = {"dtype": str(df[col].dtype)}
        null_count = int(df[col].isna().sum())
        col_stats["null_count"] = null_count
        col_stats["null_ratio"] = round(null_count / len(df), 3) if len(df) > 0 else 0
        col_stats["distinct_count"] = int(df[col].nunique())

        # Value concentration (top-N)
        if col_stats["distinct_count"] > 0:
            top_vals = df[col].value_counts().head(5)
            col_stats["top_values"] = {
                str(k): int(v) for k, v in top_vals.items()
            }
            # Concentration ratio: top-1 value share
            col_stats["top1_share"] = round(
                int(top_vals.iloc[0]) / len(df), 3
            ) if len(top_vals) > 0 else 0

        # Numeric stats
        if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col]):
            col_stats["mean"] = round(float(df[col].mean()), 2) if not df[col].isna().all() else None
            col_stats["median"] = round(float(df[col].median()), 2) if not df[col].isna().all() else None
            col_stats["std"] = round(float(df[col].std()), 2) if not df[col].isna().all() else None
            col_stats["min"] = round(float(df[col].min()), 2) if not df[col].isna().all() else None
            col_stats["max"] = round(float(df[col].max()), 2) if not df[col].isna().all() else None

            # IQR-based outlier detection
            q1 = df[col].quantile(0.25)
            q3 = df[col].quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                outlier_mask = (df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)
                outlier_count = int(outlier_mask.sum())
                col_stats["outlier_count"] = outlier_count
                if outlier_count > 0:
                    col_stats["outlier_values"] = [
                        round(float(v), 2) for v in df[col][outlier_mask].head(5).tolist()
                    ]

        stats["columns"][col] = col_stats

    # Duplicate detection
    dup_count = int(df.duplicated().sum())
    stats["exact_duplicate_rows"] = dup_count

    # Temporal clustering (if datetime columns exist)
    for col in df.columns:
        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
            valid = parsed.dropna()
            if len(valid) > 5:
                # Check if many values cluster in a short window
                sorted_ts = valid.sort_values()
                diffs = sorted_ts.diff().dropna()
                median_gap = diffs.median().total_seconds()
                if median_gap < 600:  # less than 10 minutes
                    stats.setdefault("temporal_clusters", []).append({
                        "column": col,
                        "median_gap_seconds": round(median_gap, 1),
                        "window_start": str(sorted_ts.iloc[0]),
                        "window_end": str(sorted_ts.iloc[-1]),
                    })
        except Exception:
            pass

    return stats


# ── Mock insight generation ───────────────────────────────────────────────


def _generate_mock_insights(
    proposal_id: str,
    target_table: str,
    stats: dict,
    filename: str = "",
) -> list[dict]:
    """Return hardcoded insights crafted around the demo CSV patterns."""
    insights = []

    # Look for customer concentration
    cust_col = stats.get("columns", {}).get("customer_id", {})
    if cust_col.get("top1_share", 0) >= 0.4:
        top_customer = list(cust_col.get("top_values", {}).keys())[0] if cust_col.get("top_values") else "unknown"
        share_pct = round(cust_col["top1_share"] * 100)
        insights.append({
            "category": "CONCENTRATION",
            "severity": "CRITICAL",
            "title": f"Customer {top_customer} dominates this batch",
            "description": (
                f"{share_pct}% of all orders in this batch come from a single customer (ID: {top_customer}). "
                f"This level of concentration is unusual and may indicate a bulk buyer, a data duplication issue, "
                f"or a downstream system sending repeated records."
            ),
            "evidence": {
                "customer_id": top_customer,
                "share_percent": share_pct,
                "total_rows": stats["row_count"],
            },
        })

    # Look for amount outliers
    amt_col = stats.get("columns", {}).get("amount_usd", {})
    if amt_col.get("outlier_count", 0) > 0:
        outlier_vals = amt_col.get("outlier_values", [])
        insights.append({
            "category": "ANOMALY",
            "severity": "WARNING",
            "title": "Extreme order value detected",
            "description": (
                f"Found {amt_col['outlier_count']} order(s) with values far outside the normal range. "
                f"The median order is ${amt_col.get('median', 0)}, but outlier values include "
                f"{', '.join(f'${v}' for v in outlier_vals[:3])}. These may be legitimate large orders "
                f"or data entry errors that warrant review."
            ),
            "evidence": {
                "median": amt_col.get("median"),
                "outlier_values": outlier_vals,
                "outlier_count": amt_col["outlier_count"],
            },
        })

    # Look for high null ratios
    for col_name, col_data in stats.get("columns", {}).items():
        if col_data.get("null_ratio", 0) >= 0.3 and col_data["null_count"] > 0:
            pct = round(col_data["null_ratio"] * 100)
            insights.append({
                "category": "DATA_QUALITY",
                "severity": "WARNING",
                "title": f"High null rate in '{col_name}' column",
                "description": (
                    f"The '{col_name}' column has a {pct}% null rate ({col_data['null_count']} of "
                    f"{stats['row_count']} rows). This is likely caused by a broken upstream form field, "
                    f"a schema change in the source system, or an optional field that should be required."
                ),
                "evidence": {
                    "column": col_name,
                    "null_ratio": col_data["null_ratio"],
                    "null_count": col_data["null_count"],
                },
            })

    # Look for temporal clustering
    for cluster in stats.get("temporal_clusters", []):
        insights.append({
            "category": "PATTERN",
            "severity": "WARNING",
            "title": "Suspicious temporal clustering detected",
            "description": (
                f"Many orders were placed within a very short time window "
                f"(median gap: {cluster['median_gap_seconds']}s between {cluster['window_start']} and "
                f"{cluster['window_end']}). This pattern may indicate bot activity, a batch import, "
                f"or a system replay event."
            ),
            "evidence": cluster,
        })

    # Revenue concentration (if amount column exists)
    if amt_col and cust_col.get("top_values"):
        insights.append({
            "category": "TREND",
            "severity": "INFO",
            "title": "Revenue highly concentrated among few customers",
            "description": (
                f"The top customer by order count also likely drives a disproportionate share of revenue. "
                f"With {cust_col.get('distinct_count', 0)} unique customers in this batch, "
                f"the top contributor alone accounts for {round(cust_col.get('top1_share', 0) * 100)}% of orders. "
                f"Consider diversification strategies to reduce revenue risk."
            ),
            "evidence": {
                "unique_customers": cust_col.get("distinct_count", 0),
                "top_customer_share": cust_col.get("top1_share", 0),
            },
        })

    # Ensure we always return at least one insight
    if not insights:
        insights.append({
            "category": "DATA_QUALITY",
            "severity": "INFO",
            "title": "Data quality looks good",
            "description": (
                f"No major anomalies, concentration risks, or quality issues detected in this "
                f"{stats['row_count']}-row batch. All columns have acceptable null rates and "
                f"value distributions appear normal."
            ),
            "evidence": {"row_count": stats["row_count"], "column_count": stats["column_count"]},
        })

    return insights


# ── LLM-based insight generation ──────────────────────────────────────────


async def _generate_llm_insights(
    stats: dict,
    target_table: str,
    rows_written: int,
) -> list[dict]:
    """Call the LLM to generate insights from statistical analysis."""
    from groq import Groq

    client = Groq(api_key=settings.GROQ_API_KEY)

    system_prompt = """You are a data analyst AI. Given statistical summaries of a dataset that was just loaded into a database, generate 3-5 concise, actionable insights.

You must respond with ONLY valid JSON. No markdown, no code fences. Raw JSON only.

Response format:
[
  {
    "category": "CONCENTRATION|ANOMALY|DATA_QUALITY|TREND|PATTERN",
    "severity": "INFO|WARNING|CRITICAL",
    "title": "Short, attention-grabbing title (max 10 words)",
    "description": "2-3 sentences in plain, business-friendly English. No technical jargon. Explain what was found, why it matters, and what action to consider.",
    "evidence": {"key": "value pairs of the raw stats backing this insight"}
  }
]

Rules:
- CRITICAL severity: Use only for findings that could cause business harm if ignored (e.g., >50% concentration in one entity, data integrity issues)
- WARNING severity: For notable patterns that deserve attention (e.g., high null rates, outliers, clustering)
- INFO severity: For informational patterns (e.g., distribution summaries, trends)
- Write as if explaining to a business stakeholder, not an engineer
- Each insight must be backed by specific numbers from the statistics
- Focus on surprising, non-obvious patterns — avoid stating the obvious"""

    user_msg = f"""Dataset loaded into table '{target_table}' — {rows_written} rows written.

STATISTICAL SUMMARY:
{json.dumps(stats, indent=2, default=str)}

Generate insights about this data."""

    import asyncio

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        logger.warning(f"LLM insight generation failed: {e}")
        return []


# ── Public API ────────────────────────────────────────────────────────────


async def generate_insights(
    proposal_id: str,
    target_table: str,
    rows_written: int,
    transformed_df: pd.DataFrame,
    db: AsyncSession,
    filename: str = "",
) -> list[dict]:
    """
    Generate and persist insights for a completed pipeline execution.

    1. Compute statistical summary of the transformed data
    2. Generate insights (mock or LLM)
    3. Persist to insight_records table
    4. Return the insight list

    Never raises — all exceptions are caught and logged.
    """
    try:
        stats = _compute_stats(transformed_df)

        if settings.MOCK_AI:
            raw_insights = _generate_mock_insights(
                proposal_id, target_table, stats, filename
            )
        else:
            raw_insights = await _generate_llm_insights(
                stats, target_table, rows_written
            )

        # Persist each insight
        persisted = []
        for item in raw_insights:
            record = InsightRecord(
                proposal_id=proposal_id,
                category=item.get("category", "DATA_QUALITY"),
                severity=item.get("severity", "INFO"),
                title=item.get("title", "Untitled insight"),
                description=item.get("description", ""),
                evidence=item.get("evidence"),
            )
            db.add(record)
            await db.flush()  # get the auto-generated id
            persisted.append({
                "id": record.id,
                "proposal_id": proposal_id,
                "category": record.category,
                "severity": record.severity,
                "title": record.title,
                "description": record.description,
                "evidence": record.evidence,
                "created_at": record.created_at.isoformat() if record.created_at else None,
            })

        await db.commit()
        logger.info(
            f"Generated {len(persisted)} insights for proposal {proposal_id}"
        )
        return persisted

    except Exception as e:
        logger.warning(f"Insight generation failed for {proposal_id}: {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        return []


async def get_insights(
    proposal_id: str,
    db: AsyncSession,
) -> list[dict]:
    """Retrieve stored insights for a proposal."""
    stmt = (
        select(InsightRecord)
        .where(InsightRecord.proposal_id == proposal_id)
        .order_by(InsightRecord.created_at.asc())
    )
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [
        {
            "id": r.id,
            "proposal_id": r.proposal_id,
            "category": r.category,
            "severity": r.severity,
            "title": r.title,
            "description": r.description,
            "evidence": r.evidence,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


async def list_all_insights(
    db: AsyncSession,
    category: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List all insights, with optional category/severity filters."""
    stmt = select(InsightRecord)
    if category:
        stmt = stmt.where(InsightRecord.category == category)
    if severity:
        stmt = stmt.where(InsightRecord.severity == severity)
    stmt = stmt.order_by(InsightRecord.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [
        {
            "id": r.id,
            "proposal_id": r.proposal_id,
            "category": r.category,
            "severity": r.severity,
            "title": r.title,
            "description": r.description,
            "evidence": r.evidence,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


async def get_insights_summary(db: AsyncSession) -> dict:
    """Aggregate stats: total by category, by severity, recent critical."""
    all_insights = await list_all_insights(db, limit=500)
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    recent_critical: list[dict] = []

    for item in all_insights:
        cat = item.get("category", "OTHER")
        sev = item.get("severity", "INFO")
        by_category[cat] = by_category.get(cat, 0) + 1
        by_severity[sev] = by_severity.get(sev, 0) + 1
        if sev in ("CRITICAL", "WARNING") and len(recent_critical) < 5:
            recent_critical.append(item)

    return {
        "total": len(all_insights),
        "by_category": by_category,
        "by_severity": by_severity,
        "recent_critical": recent_critical,
    }
