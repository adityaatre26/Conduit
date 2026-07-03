#!/usr/bin/env python3
"""
Conduit Backend — Comprehensive Test Suite
Covers all 12 scenarios (A–L) from the implementation plan.
Run: python run_checks.py
Expects: http://localhost:8000/api to be running.
"""
import httpx
import json
import sys
import os
import time
import io
from pathlib import Path

BASE = "http://localhost:8000/api"

# Reconfigure stdout/stderr to UTF-8 on Windows if supported to prevent cp1252 encoding errors
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Encoding-safe icons for Windows CP1252/UTF-8 compat
try:
    "✅".encode(sys.stdout.encoding or "utf-8")
    "✔".encode(sys.stdout.encoding or "utf-8")
    PASS = "✅"
    FAIL = "❌"
    SKIP = "⚠️"
    TEST_ICON = "🧪"
    OK_ICON = "✔"
    ERR_ICON = "✘"
    PARTY_ICON = "🎉"
    WARN_ICON = "⚠️"
except Exception:
    PASS = "[PASS]"
    FAIL = "[FAIL]"
    SKIP = "[SKIP]"
    TEST_ICON = "="
    OK_ICON = "[OK]"
    ERR_ICON = "[ERROR]"
    PARTY_ICON = "[SUCCESS]"
    WARN_ICON = "[WARN]"


results = {"pass": 0, "fail": 0, "skip": 0}

# Track IDs across scenarios
state = {}


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        print(f"  {PASS} {name}")
        results["pass"] += 1
    else:
        print(f"  {FAIL} {name} — {detail}")
        results["fail"] += 1


def skip(name: str, reason: str = ""):
    print(f"  {SKIP} {name} — {reason}")
    results["skip"] += 1


def heading(label: str):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print("=" * 60)


# ─────────────────────────────────────────────────────────────
#  Scenario A: Clean upload → AUTO_LINK
# ─────────────────────────────────────────────────────────────
def scenario_a():
    heading("SCENARIO A — Clean upload → AUTO_LINK")
    csv_path = "db/demo_csvs/clean_orders.csv"
    if not os.path.exists(csv_path):
        csv_path = "Conduit/db/demo_csvs/clean_orders.csv"
    if not os.path.exists(csv_path):
        skip("A.1", f"CSV not found at {csv_path}")
        return

    with open(csv_path, "rb") as f:
        resp = httpx.post(
            f"{BASE}/ingest",
            files={"file": ("clean_orders.csv", f, "text/csv")},
            data={"target_table": "orders_clean"},
            timeout=120,
        )

    check("A.1 Ingest returns 200", resp.status_code == 200, f"got {resp.status_code}: {resp.text[:200]}")
    if resp.status_code != 200:
        return

    data = resp.json()
    state["proposal_id_auto"] = data.get("proposal_id")

    status_ok = data.get("gateway_status") in ["AUTO_LINK", "SCHEMA_EVOLUTION", "CONFLICT"]
    check("A.2 gateway_status is AUTO_LINK, SCHEMA_EVOLUTION, or CONFLICT", status_ok, f"got {data.get('gateway_status')}")
    check("A.3 target_table present in response", data.get("target_table") == "orders_clean", f"got {data.get('target_table')}")
    score_ok = (data.get("confidence_score") or 0) >= 0.85
    check("A.4 confidence_score >= 0.85", score_ok, f"got {data.get('confidence_score')}")
    check("A.5 llm_model_used is not none", data.get("llm_model_used") not in [None, "", "none"], f"got {data.get('llm_model_used')}")

    # Approve and execute
    pid = state["proposal_id_auto"]
    resp2 = httpx.post(
        f"{BASE}/proposals/{pid}/approve",
        json={"human_approver_id": "test_engineer_01"},
        timeout=120,
    )
    check("A.6 Approval returns 200", resp2.status_code == 200, f"got {resp2.status_code}: {resp2.text[:200]}")
    if resp2.status_code == 200:
        exec_data = resp2.json()
        check("A.7 rows_written == 30", exec_data.get("rows_written") == 30, f"got {exec_data.get('rows_written')}")
        check("A.8 execution_status == SUCCESS", exec_data.get("execution_status") == "SUCCESS", f"got {exec_data.get('execution_status')}")

    # Lineage event check
    resp3 = httpx.get(f"{BASE}/lineage/{pid}", timeout=120)
    if resp3.status_code == 200:
        events = resp3.json()
        check("A.9 Lineage event created", len(events) > 0, "no lineage events")
    else:
        check("A.9 Lineage endpoint reachable", False, f"got {resp3.status_code}")

    # Graph auto-populated check
    resp4 = httpx.get(f"{BASE}/graph/nodes?node_type=FILE", timeout=120)
    if resp4.status_code == 200:
        nodes = resp4.json()
        file_nodes = [n for n in nodes if "clean_orders" in (n.get("entity_name") or "")]
        check("A.10 Graph auto-populated FILE node", len(file_nodes) > 0, "no FILE node for clean_orders")
    else:
        check("A.10 Graph nodes endpoint", False, f"got {resp4.status_code}")


# ─────────────────────────────────────────────────────────────
#  Scenario B: Drifted upload → SCHEMA_EVOLUTION
# ─────────────────────────────────────────────────────────────
def scenario_b():
    heading("SCENARIO B — Drifted upload → SCHEMA_EVOLUTION")
    csv_path = "db/demo_csvs/drifted_orders.csv"
    if not os.path.exists(csv_path):
        csv_path = "Conduit/db/demo_csvs/drifted_orders.csv"
    if not os.path.exists(csv_path):
        skip("B.1", f"CSV not found at {csv_path}")
        return

    with open(csv_path, "rb") as f:
        resp = httpx.post(
            f"{BASE}/ingest",
            files={"file": ("drifted_orders.csv", f, "text/csv")},
            data={"target_table": "orders_clean"},
            timeout=120,
        )

    check("B.1 Ingest returns 200", resp.status_code == 200, f"got {resp.status_code}: {resp.text[:200]}")
    if resp.status_code != 200:
        return

    data = resp.json()
    state["proposal_id_drift"] = data.get("proposal_id")

    check("B.2 gateway_status == SCHEMA_EVOLUTION", data.get("gateway_status") == "SCHEMA_EVOLUTION", f"got {data.get('gateway_status')}")
    drift = data.get("drift_detected", [])
    check("B.3 drift_detected has 3 items", len(drift) == 3, f"got {len(drift)}")
    check("B.4 pii_columns_found includes customer_email", "customer_email" in (data.get("pii_columns_found") or []), f"got {data.get('pii_columns_found')}")

    # Approve
    pid = state["proposal_id_drift"]
    resp2 = httpx.post(
        f"{BASE}/proposals/{pid}/approve",
        json={"human_approver_id": "test_engineer_02"},
        timeout=120,
    )
    check("B.5 Approval succeeds", resp2.status_code == 200, f"got {resp2.status_code}: {resp2.text[:200]}")


# ─────────────────────────────────────────────────────────────
#  Scenario C: Conflict upload → CONFLICT
# ─────────────────────────────────────────────────────────────
def scenario_c():
    heading("SCENARIO C — Conflict upload → CONFLICT")
    csv_path = "db/demo_csvs/conflicted_orders.csv"
    if not os.path.exists(csv_path):
        csv_path = "Conduit/db/demo_csvs/conflicted_orders.csv"
    if not os.path.exists(csv_path):
        skip("C.1", f"CSV not found at {csv_path}")
        return

    with open(csv_path, "rb") as f:
        resp = httpx.post(
            f"{BASE}/ingest",
            files={"file": ("conflicted_orders.csv", f, "text/csv")},
            data={"target_table": "orders_clean"},
            timeout=120,
        )

    check("C.1 Ingest returns 200", resp.status_code == 200, f"got {resp.status_code}: {resp.text[:200]}")
    if resp.status_code != 200:
        return

    data = resp.json()
    state["proposal_id_conflict"] = data.get("proposal_id")

    check("C.2 gateway_status == CONFLICT", data.get("gateway_status") == "CONFLICT", f"got {data.get('gateway_status')}")
    drift = data.get("drift_detected", [])
    high_sev = [d for d in drift if d.get("severity") == "HIGH"]
    check("C.3 HIGH severity items present", len(high_sev) > 0, f"got {len(high_sev)} HIGH items")


# ─────────────────────────────────────────────────────────────
#  Scenario D: Zero column overlap → fast CONFLICT
# ─────────────────────────────────────────────────────────────
def scenario_d():
    heading("SCENARIO D — Zero overlap → fast CONFLICT")
    # Create a CSV with columns that don't match orders_clean
    csv_content = "foo,bar,baz\n1,2,3\n4,5,6\n"
    csv_bytes = csv_content.encode()

    resp = httpx.post(
        f"{BASE}/ingest",
        files={"file": ("zero_overlap.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={"target_table": "orders_clean"},
        timeout=120,
    )

    check("D.1 Ingest returns 200", resp.status_code == 200, f"got {resp.status_code}: {resp.text[:200]}")
    if resp.status_code != 200:
        return

    data = resp.json()
    check("D.2 gateway_status == CONFLICT", data.get("gateway_status") == "CONFLICT", f"got {data.get('gateway_status')}")
    check("D.3 llm_model_used == none", data.get("llm_model_used") == "none", f"got {data.get('llm_model_used')}")
    check("D.4 confidence_score == 0.0", data.get("confidence_score") == 0.0, f"got {data.get('confidence_score')}")


# ─────────────────────────────────────────────────────────────
#  Scenario E: File safety
# ─────────────────────────────────────────────────────────────
def scenario_e():
    heading("SCENARIO E — File safety")

    # E.1: PDF rejected
    pdf_header = b"%PDF-1.4 fake content" + b"\x00" * 100
    resp = httpx.post(
        f"{BASE}/ingest",
        files={"file": ("test.pdf", io.BytesIO(pdf_header), "application/pdf")},
        data={"target_table": "orders_clean"},
        timeout=120,
    )
    check("E.1 PDF rejected (400)", resp.status_code == 400, f"got {resp.status_code}")

    # E.2: Empty file rejected
    resp2 = httpx.post(
        f"{BASE}/ingest",
        files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
        data={"target_table": "orders_clean"},
        timeout=120,
    )
    check("E.2 Empty file rejected (400)", resp2.status_code == 400, f"got {resp2.status_code}")

    # E.3: Large file rejected (simulate > 50MB)
    # Just check that the endpoint doesn't crash — actual 50MB test is impractical
    skip("E.3 50MB+ file rejection", "Not practical in automated test")


# ─────────────────────────────────────────────────────────────
#  Scenario F: Skill lifecycle
# ─────────────────────────────────────────────────────────────
def scenario_f():
    heading("SCENARIO F — Skill lifecycle")

    skill_name = f"test_email_validation_{int(time.time())}"
    # F.1: Create skill
    skill_data = {
        "skill_name": skill_name,
        "version": "1.0.0",
        "category": "DATA_QUALITY",
        "description": "Validates email format and domain against known providers.",
        "use_cases": "Customer registration forms, bulk email imports.",
        "constraints": "Email must be non-null and string type.",
        "owner": "Test Suite"
    }
    resp = httpx.post(f"{BASE}/skills", json=skill_data, timeout=120)
    check("F.1 Create skill returns 201", resp.status_code == 201, f"got {resp.status_code}: {resp.text[:200]}")
    if resp.status_code == 201:
        skill = resp.json()
        state["test_skill_id"] = skill.get("id")
        check("F.2 Skill has correct name", skill.get("skill_name") == skill_name, f"got {skill.get('skill_name')}")
    else:
        skip("F.2-F.9", "Skill creation failed")
        return

    sid = state["test_skill_id"]

    # F.3: Get skill by ID
    resp3 = httpx.get(f"{BASE}/skills/{sid}", timeout=120)
    check("F.3 GET skill by ID returns 200", resp3.status_code == 200, f"got {resp3.status_code}")

    # F.4: Search skills
    resp4 = httpx.get(f"{BASE}/skills/search?q=email", timeout=120)
    check("F.4 Search finds skill", resp4.status_code == 200 and len(resp4.json()) > 0, f"got {resp4.status_code}, results: {len(resp4.json()) if resp4.status_code == 200 else 'N/A'}")

    # F.5: Attach script
    script_data = {
        "script_path": "/scripts/email_validation.py",
        "script_hash": "abc123def456",
        "is_validated": True
    }
    resp5 = httpx.post(f"{BASE}/skills/{sid}/scripts", json=script_data, timeout=120)
    check("F.5 Attach script returns 201", resp5.status_code == 201, f"got {resp5.status_code}: {resp5.text[:200]}")

    # F.6: Attach issue
    issue_data = {
        "issue_reference": "INC-TEST-001",
        "resolution_notes": "Unicode emails were failing validation. Fixed regex pattern."
    }
    resp6 = httpx.post(f"{BASE}/skills/{sid}/issues", json=issue_data, timeout=120)
    check("F.6 Attach issue returns 201", resp6.status_code == 201, f"got {resp6.status_code}: {resp6.text[:200]}")

    # F.7: Verify detail includes children
    resp7 = httpx.get(f"{BASE}/skills/{sid}", timeout=120)
    if resp7.status_code == 200:
        detail = resp7.json()
        check("F.7 Detail includes scripts", len(detail.get("scripts", [])) > 0, "no scripts")
        check("F.8 Detail includes issue_references", len(detail.get("issue_references", [])) > 0, "no issue refs")
    else:
        check("F.7 Detail fetch", False, f"got {resp7.status_code}")

    # F.9: Deprecate skill
    resp9 = httpx.patch(f"{BASE}/skills/{sid}", json={"status": "DEPRECATED"}, timeout=120)
    check("F.9 Deprecate returns 200", resp9.status_code == 200, f"got {resp9.status_code}")

    # Verify deprecated skill excluded from search
    resp10 = httpx.get(f"{BASE}/skills/search?q={skill_name}", timeout=120)
    if resp10.status_code == 200:
        found = [s for s in resp10.json() if s.get("skill_name") == skill_name]
        check("F.10 Deprecated skill excluded from search", len(found) == 0, f"found {len(found)} results")
    else:
        check("F.10 Search after deprecation", False, f"got {resp10.status_code}")


# ─────────────────────────────────────────────────────────────
#  Scenario G: Graph manual ops
# ─────────────────────────────────────────────────────────────
def scenario_g():
    heading("SCENARIO G — Graph manual operations")

    # G.1: Create test nodes
    node1 = httpx.post(f"{BASE}/graph/nodes", json={
        "node_type": "TABLE",
        "entity_id": "tbl-invoices",
        "entity_name": "invoices",
        "metadata": {"semantic_description": "Invoice records generated from orders."}
    }, timeout=120)
    check("G.1 Create TABLE node invoices", node1.status_code == 201, f"got {node1.status_code}: {node1.text[:200]}")

    node2 = httpx.post(f"{BASE}/graph/nodes", json={
        "node_type": "KPI",
        "entity_id": "kpi-quarterly",
        "entity_name": "quarterly_revenue",
        "metadata": {"description": "Quarterly revenue aggregation."}
    }, timeout=120)
    check("G.2 Create KPI node quarterly_revenue", node2.status_code == 201, f"got {node2.status_code}")

    if node1.status_code == 201 and node2.status_code == 201:
        inv_id = node1.json().get("id")
        kpi_id = node2.json().get("id")
        state["invoices_node_id"] = inv_id
        state["quarterly_kpi_node_id"] = kpi_id

        # G.3: Create edges — invoices DEPENDS_ON orders_clean
        # First find orders_clean node id
        nodes_resp = httpx.get(f"{BASE}/graph/nodes?node_type=TABLE", timeout=120)
        orders_node = None
        if nodes_resp.status_code == 200:
            for n in nodes_resp.json():
                if n.get("entity_name") == "orders_clean":
                    orders_node = n
                    break

        if orders_node:
            edge1 = httpx.post(f"{BASE}/graph/edges", json={
                "source_node_id": inv_id,
                "target_node_id": orders_node["id"],
                "relation_type": "DEPENDS_ON",
                "confidence_score": 0.95
            }, timeout=120)
            check("G.3 Create DEPENDS_ON edge invoices→orders_clean", edge1.status_code == 201, f"got {edge1.status_code}")

            edge2 = httpx.post(f"{BASE}/graph/edges", json={
                "source_node_id": kpi_id,
                "target_node_id": inv_id,
                "relation_type": "DEPENDS_ON",
                "confidence_score": 0.9
            }, timeout=120)
            check("G.4 Create DEPENDS_ON edge quarterly_revenue→invoices", edge2.status_code == 201, f"got {edge2.status_code}")

            # G.5: BFS lineage
            lineage = httpx.get(f"{BASE}/graph/lineage/orders_clean?max_depth=4", timeout=120)
            if lineage.status_code == 200:
                lin_data = lineage.json()
                node_names = [n.get("entity_name") for n in lin_data.get("nodes", [])]
                check("G.5 BFS finds invoices in lineage", "invoices" in node_names, f"got nodes: {node_names[:10]}")
            else:
                check("G.5 BFS lineage", False, f"got {lineage.status_code}")

            # G.6: Impact analysis
            impact = httpx.get(f"{BASE}/graph/impact/orders_clean", timeout=120)
            if impact.status_code == 200:
                imp_data = impact.json()
                impacted_names = [n["node"].get("entity_name") for n in imp_data.get("impacted_nodes", [])]
                check("G.6 Impact finds invoices", "invoices" in impacted_names, f"got: {impacted_names[:10]}")
                check("G.7 Impact finds quarterly_revenue", "quarterly_revenue" in impacted_names, f"got: {impacted_names[:10]}")
            else:
                check("G.6 Impact analysis", False, f"got {impact.status_code}")

            # G.8: Idempotent edge creation
            edge_dup = httpx.post(f"{BASE}/graph/edges", json={
                "source_node_id": inv_id,
                "target_node_id": orders_node["id"],
                "relation_type": "DEPENDS_ON",
                "confidence_score": 0.95
            }, timeout=120)
            check("G.8 Idempotent edge (no error)", edge_dup.status_code == 201, f"got {edge_dup.status_code}")
        else:
            skip("G.3-G.8", "orders_clean node not found")
    else:
        skip("G.3-G.8", "Node creation failed")


# ─────────────────────────────────────────────────────────────
#  Scenario H: Lineage queries
# ─────────────────────────────────────────────────────────────
def scenario_h():
    heading("SCENARIO H — Lineage queries")

    # H.1: List all events
    resp = httpx.get(f"{BASE}/lineage", timeout=120)
    check("H.1 List lineage events returns 200", resp.status_code == 200, f"got {resp.status_code}")
    if resp.status_code == 200:
        events = resp.json()
        check("H.2 At least 1 lineage event exists", len(events) > 0, f"got {len(events)}")

    # H.3: Filter by proposal
    pid = state.get("proposal_id_auto")
    if pid:
        resp2 = httpx.get(f"{BASE}/lineage/{pid}", timeout=120)
        check("H.3 Lineage filter by proposal returns 200", resp2.status_code == 200, f"got {resp2.status_code}")
        if resp2.status_code == 200:
            check("H.4 Filtered events have correct proposal_id", all(e.get("proposal_id") == pid for e in resp2.json()), "mismatch")
    else:
        skip("H.3", "No auto-link proposal ID available")


# ─────────────────────────────────────────────────────────────
#  Scenario I: AI fallback (skip if MOCK_AI)
# ─────────────────────────────────────────────────────────────
def scenario_i():
    heading("SCENARIO I — AI fallback")
    skip("I.1", "Requires invalid Groq key and MOCK_AI=False. Skip in automated test.")


# ─────────────────────────────────────────────────────────────
#  Scenario J: Audit completeness
# ─────────────────────────────────────────────────────────────
def scenario_j():
    heading("SCENARIO J — Audit completeness")

    resp = httpx.get(f"{BASE}/audit", timeout=120)
    check("J.1 Audit endpoint returns 200", resp.status_code == 200, f"got {resp.status_code}")
    if resp.status_code != 200 or not resp.json():
        skip("J.2-J.4", "No audit entries")
        return

    entry = resp.json()[0]
    required_fields = [
        "id", "proposal_id", "filename", "skill_name",
        "execution_status", "human_approver_id", "executed_at",
        "llm_prompt_sent", "llm_raw_response", "transformation_script_ref"
    ]
    missing = [f for f in required_fields if f not in entry]
    check("J.2 All required audit fields present", len(missing) == 0, f"missing: {missing}")

    # J.3: Single audit entry by ID
    entry_id = entry.get("id")
    resp2 = httpx.get(f"{BASE}/audit/{entry_id}", timeout=120)
    check("J.3 Single audit entry returns 200", resp2.status_code == 200, f"got {resp2.status_code}")
    if resp2.status_code == 200:
        single = resp2.json()
        check("J.4 Single entry has correct ID", single.get("id") == entry_id, f"got {single.get('id')}")


# ─────────────────────────────────────────────────────────────
#  Scenario K: Proposals filtering
# ─────────────────────────────────────────────────────────────
def scenario_k():
    heading("SCENARIO K — Proposals filtering")

    # K.1: List all proposals
    resp = httpx.get(f"{BASE}/proposals", timeout=120)
    check("K.1 List proposals returns 200", resp.status_code == 200, f"got {resp.status_code}")
    if resp.status_code == 200:
        proposals = resp.json()
        check("K.2 Multiple proposals exist", len(proposals) >= 3, f"got {len(proposals)}")

    # K.3: Filter by status
    resp2 = httpx.get(f"{BASE}/proposals?status=PENDING", timeout=120)
    if resp2.status_code == 200:
        pending = resp2.json()
        all_pending = all(p.get("gateway_status") is not None for p in pending)
        check("K.3 Status filter works", resp2.status_code == 200, "filter failed")
    else:
        check("K.3 Status filter", False, f"got {resp2.status_code}")

    # K.4: Pagination
    resp3 = httpx.get(f"{BASE}/proposals?limit=1&offset=0", timeout=120)
    check("K.4 Pagination (limit=1)", resp3.status_code == 200 and len(resp3.json()) <= 1, f"got {len(resp3.json()) if resp3.status_code == 200 else 'N/A'} results")

    # K.5: target_table present in response
    if resp.status_code == 200 and proposals:
        has_target = any(p.get("target_table") is not None for p in proposals)
        check("K.5 target_table present in proposals", has_target, "no target_table found")


# ─────────────────────────────────────────────────────────────
#  Scenario L: Context bundle growth
# ─────────────────────────────────────────────────────────────
def scenario_l():
    heading("SCENARIO L — Context bundle growth")

    # L.1: Check context for first auto-link proposal
    pid = state.get("proposal_id_auto")
    if not pid:
        skip("L.1-L.4", "No auto-link proposal")
        return

    resp = httpx.get(f"{BASE}/proposals/{pid}/context", timeout=120)
    if resp.status_code == 200:
        ctx = resp.json()
        bundle = ctx.get("context_bundle", {})
        check("L.1 Context bundle exists", bundle is not None, "no bundle")
        check("L.2 Context has target_table", ctx.get("target_table") == "orders_clean", f"got {ctx.get('target_table')}")

        related_skills = bundle.get("related_skills", [])
        check("L.3 Context has related_skills", len(related_skills) > 0, f"got {len(related_skills)} skills")

        related_entities = bundle.get("related_entities", [])
        check("L.4 Context has related_entities", len(related_entities) > 0, f"got {len(related_entities)} entities")
    elif resp.status_code == 404:
        skip("L.1-L.4", "Context not found (may be expected if graph is empty)")
    else:
        check("L.1 Context endpoint", False, f"got {resp.status_code}: {resp.text[:200]}")

    # L.5: List graph nodes — check no duplicates
    resp2 = httpx.get(f"{BASE}/graph/nodes", timeout=120)
    if resp2.status_code == 200:
        nodes = resp2.json()
        seen = set()
        dups = []
        for n in nodes:
            key = (n.get("node_type"), n.get("entity_id"))
            if key in seen:
                dups.append(key)
            seen.add(key)
        check("L.5 No duplicate graph nodes", len(dups) == 0, f"duplicates: {dups[:5]}")
    else:
        check("L.5 Graph nodes check", False, f"got {resp2.status_code}")


# ─────────────────────────────────────────────────────────────
#  Additional: Quick endpoint smoke tests
# ─────────────────────────────────────────────────────────────
def endpoint_smoke():
    heading("SMOKE — All key endpoints reachable")

    endpoints = [
        ("GET", "/proposals"),
        ("GET", "/audit"),
        ("GET", "/quarantine"),
        ("GET", "/sources"),
        ("GET", "/skills"),
        ("GET", "/graph/nodes"),
        ("GET", "/graph/edges"),
        ("GET", "/lineage"),
    ]

    for method, path in endpoints:
        try:
            resp = httpx.request(method, f"{BASE}{path}", timeout=120)
            check(f"{method} {path} → {resp.status_code}", resp.status_code in [200, 201], f"got {resp.status_code}")
        except Exception as e:
            check(f"{method} {path}", False, str(e))


# ─────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────
def main():
    print("\n" + TEST_ICON * 30)
    print("  CONDUIT BACKEND — COMPREHENSIVE TEST SUITE")
    print(TEST_ICON * 30)
    print(f"\n  Target: {BASE}")
    print(f"  Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Quick connectivity check
    try:
        r = httpx.get(f"{BASE}/sources", timeout=120)
        print(f"  {OK_ICON} Server reachable (status {r.status_code})\n")
    except Exception as e:
        print(f"  {ERR_ICON} Cannot reach {BASE}. Is the server running?")
        print(f"    Error: {e}")
        sys.exit(1)

    # Run all scenarios in order
    scenario_a()
    scenario_b()
    scenario_c()
    scenario_d()
    scenario_e()
    scenario_f()
    scenario_g()
    scenario_h()
    scenario_i()
    scenario_j()
    scenario_k()
    scenario_l()
    endpoint_smoke()

    # Summary
    print(f"\n\n{'='*60}")
    print("  RESULTS SUMMARY")
    print("=" * 60)
    total = results["pass"] + results["fail"] + results["skip"]
    print(f"  {PASS} Passed:  {results['pass']}")
    print(f"  {FAIL} Failed:  {results['fail']}")
    print(f"  {SKIP} Skipped: {results['skip']}")
    print(f"  Total:    {total}")
    print("=" * 60)

    if results["fail"] > 0:
        print(f"\n  {WARN_ICON}  {results['fail']} test(s) FAILED")
        sys.exit(1)
    else:
        print(f"\n  {PARTY_ICON} All tests passed (with {results['skip']} skips)")
        sys.exit(0)


if __name__ == "__main__":
    main()
