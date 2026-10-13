#!/usr/bin/env python3
"""Clean messy transaction CSV data and produce cleaned.csv and report.json."""
import csv
import json
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from collections import Counter, defaultdict
from pathlib import Path

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y")
STATUSES = {"paid", "pending", "cancelled", "refund"}

def clean_name(value):
    original = (value or "").strip()
    normalized = re.sub(r"\s+", " ", original).title()
    return original, normalized

def parse_date(value):
    value = (value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return ""

def parse_amount(value):
    raw = (value or "").strip()
    if not raw or raw.upper() in {"N/A", "NA", "NULL", "NONE"}:
        return None
    # Accept plain numbers and conventional comma-grouped thousands, optionally decimals.
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", raw):
        return None
    try:
        amount = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    # Transactions must have a strictly positive amount; zero/negative values are invalid.
    if not amount.is_finite() or amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"))

def main():
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "input.csv")
    output_csv = Path(sys.argv[2] if len(sys.argv) > 2 else "cleaned.csv")
    output_json = Path(sys.argv[3] if len(sys.argv) > 3 else "report.json")

    with source.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames or []
    required = {"transaction_id", "customer_name", "amount", "transaction_date", "status", "order_id"}
    missing = required - set(fields)
    if missing:
        raise SystemExit("Missing required CSV columns: " + ", ".join(sorted(missing)))

    processed = []
    id_rows = defaultdict(list)
    fingerprint_rows = defaultdict(list)
    for i, row in enumerate(rows):
        txid = (row.get("transaction_id") or "").strip()
        original_name, normalized_name = clean_name(row.get("customer_name"))
        date = parse_date(row.get("transaction_date"))
        amount = parse_amount(row.get("amount"))
        raw_status = (row.get("status") or "").strip().lower()
        status = raw_status if raw_status in STATUSES else "unknown"
        order_id = (row.get("order_id") or "").strip()
        issues = []
        if not txid:
            issues.append("missing_transaction_id")
        if not normalized_name:
            issues.append("missing_customer_name")
        if not date:
            issues.append("unparseable_or_ambiguous_date")
        if amount is None:
            issues.append("invalid_amount")
        if status == "unknown":
            issues.append("unknown_status")
        item = {
            "transaction_id": txid, "customer_name_original": row.get("customer_name", ""),
            "customer_name_normalized": normalized_name, "amount_original": row.get("amount", ""),
            "amount": f"{amount:.2f}" if amount is not None else "",
            "transaction_date_original": row.get("transaction_date", ""),
            "transaction_date": date, "status_original": row.get("status", ""),
            "status": status, "order_id": order_id, "_issues": issues,
            "_amount_decimal": amount, "_index": i
        }
        processed.append(item)
        if txid:
            id_rows[txid].append(i)
        if order_id and normalized_name and date and amount is not None and status != "unknown":
            # Transaction-like duplicate fingerprint deliberately excludes transaction ID.
            fingerprint = (order_id, normalized_name.casefold(), date, str(amount), status)
            fingerprint_rows[fingerprint].append(i)

    duplicate_id_groups = {k:v for k,v in id_rows.items() if len(v) > 1}
    duplicate_fingerprint_groups = {k:v for k,v in fingerprint_rows.items() if len(v) > 1}
    duplicate_id_rows = set()
    for indices in duplicate_id_groups.values():
        duplicate_id_rows.update(indices)
    duplicate_lookalike_rows = set()
    # The same fingerprint may also be in a repeated-ID group; count lookalikes independently
    # only when they use different transaction IDs.
    for indices in duplicate_fingerprint_groups.values():
        ids = {processed[i]["transaction_id"] for i in indices}
        if len(ids) > 1:
            duplicate_lookalike_rows.update(indices)

    for i, item in enumerate(processed):
        if i in duplicate_id_rows:
            item["_issues"].append("duplicate_transaction_id")
        if i in duplicate_lookalike_rows:
            item["_issues"].append("possible_duplicate_transaction")
        item["validity"] = "valid" if not item["_issues"] else "invalid"
        item["issues"] = ";".join(item["_issues"]) if item["_issues"] else ""
        item.pop("_issues")
        item.pop("_index")

    out_fields = [
        "transaction_id", "customer_name_original", "customer_name_normalized",
        "amount_original", "amount", "transaction_date_original", "transaction_date",
        "status_original", "status", "order_id", "validity", "issues"
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        for item in processed:
            writer.writerow({k: item.get(k, "") for k in out_fields})

    valid_rows = sum(item["validity"] == "valid" for item in processed)
    invalid_rows = len(processed) - valid_rows
    # Revenue counts only valid, non-duplicate paid rows; invalid rows are excluded to avoid overstating revenue.
    revenue = Decimal("0")
    for i, item in enumerate(processed):
        # Reparse normalized amount from the CSV-safe value, and only count trusted paid rows.
        if item["validity"] == "valid" and item["status"] == "paid" and item["amount"]:
            revenue += Decimal(item["amount"])
    report = {
        "input_rows": len(processed),
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "duplicate_transaction_id_groups": len(duplicate_id_groups),
        "rows_with_duplicate_transaction_id": len(duplicate_id_rows),
        "possible_duplicate_transaction_groups": sum(
            1 for indices in duplicate_fingerprint_groups.values()
            if len({processed[i]["transaction_id"] for i in indices}) > 1
        ),
        "rows_in_possible_duplicate_transactions": len(duplicate_lookalike_rows),
        "total_revenue": f"{revenue:.2f}",
        "revenue_definition": "Sum of amounts for valid paid rows only; invalid and duplicate-flagged rows are excluded.",
        "reconciliation": {
            "input_rows_equals_valid_plus_invalid": len(processed) == valid_rows + invalid_rows,
            "cleaned_csv_rows": len(processed),
            "report_counts_reconcile": len(processed) == valid_rows + invalid_rows
        }
    }
    with output_json.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("")

if __name__ == "__main__":
    main()
