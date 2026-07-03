"""
validation_service.py
─────────────────────
Purpose:
    Implements AST checks and file metadata verification.

Use Cases:
    - Validates file magic bytes and size limits.
    - Runs syntax checks and blocks unsafe statements (imports, sys, eval, subprocess) 
      in generated Python scripts.
"""

import ast

# python-magic requires libmagic.dll on Windows.
# Install fix:  pip install python-magic-bin
# Fallback: pure-Python header inspection so the server still boots without the DLL.
try:
    import magic as _magic

    def _detect_mime(data: bytes) -> str:
        return _magic.from_buffer(data, mime=True)

except (ImportError, OSError):
    def _detect_mime(data: bytes) -> str:  # type: ignore[misc]
        """Minimal MIME detection without libmagic — covers CSV and JSON only."""
        head = data.lstrip()
        # JSON starts with { or [
        if head and head[0:1] in (b"{", b"["):
            return "application/json"
        # Try to decode as text — if it succeeds it's a CSV/text file
        try:
            data.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            return "application/octet-stream"

FORBIDDEN_METHODS = {
    "quantile",
    "describe",
    "corr",
    "cov",
    "kurt",
    "kurtosis",
    "skew",
    "sem",
    "var",
    "std",
    "mean",
    "median",
    "mode",
    "pct_change",
    "diff",
    "rank",
    "rolling",
    "ewm",
    "expanding",
    "groupby",
    "resample",
    "pivot_table",
    "crosstab",
    "melt",
    "wide_to_long",
    "merge",
    "join",
    "concat",
    "eval",
    "query",
}

def validate_magic_bytes(file_bytes: bytes, declared_extension: str) -> tuple[bool, str]:
    if len(file_bytes) == 0:
        return False, "File is empty"
    if len(file_bytes) > 50 * 1024 * 1024:
        return False, "File is too large (max 50MB)"
        
    detected = _detect_mime(file_bytes)
    ext = declared_extension.lower()
    if ext == '.csv':
        if detected not in ['text/plain', 'text/csv', 'application/csv']:
            return False, f"Expected CSV, detected {detected}"
    elif ext == '.json':
        if detected != 'application/json':
            return False, f"Expected JSON, detected {detected}"
    else:
        return False, f"Unsupported file extension: {declared_extension}"
            
    return True, ""

def validate_generated_code(code_string: str) -> tuple[bool, str]:
    try:
        ast.parse(code_string)
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"

    if "def transform(df" not in code_string:
        return False, "Function def transform(df: pd.DataFrame) not found"
    if "return " not in code_string:
        return False, "Function must return a value"
        
    unsafe_terms = ["import os", "import sys", "subprocess", "eval(", "exec("]
    for term in unsafe_terms:
        if term in code_string:
            return False, "unsafe code detected"

    tree = ast.parse(code_string)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_METHODS:
                return False, (
                    f"Generated code uses forbidden method '.{node.attr}()'. "
                    "Statistical and aggregation operations are not permitted "
                    "in schema transformation scripts. Only column mapping, "
                    "renaming, type casting, null filling, and string "
                    "normalization are allowed."
                )

    return True, ""
