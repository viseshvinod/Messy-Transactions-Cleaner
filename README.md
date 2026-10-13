# Messy Transactions Cleaner

## Run
Requires Python 3.9+; no third-party packages are needed.

```bash
python clean_transactions.py input.csv cleaned.csv report.json
```

If arguments are omitted, the program uses `input.csv`, `cleaned.csv`, and `report.json` in the current directory.

## Assumptions
- Customer names are normalized by trimming leading/trailing whitespace, collapsing repeated internal whitespace, and title-casing. The original source value is retained.
- Dates are output as ISO `YYYY-MM-DD`. Accepted formats are `YYYY-MM-DD`, `YYYY/MM/DD`, `DD/MM/YYYY`, and `DD-MM-YYYY`; slash and hyphen day-first formats are interpreted as day/month/year. Invalid dates are not trusted.
- Amounts accept plain numbers and comma-grouped thousands with up to two decimal places. Missing markers, malformed values, zero, and negative amounts are invalid.
- Known statuses are `paid`, `pending`, `cancelled`, and `refund`, case-insensitively. Other statuses become `unknown` and invalidate the row.
- Any issue invalidates a row; all applicable reasons are included in `issues`.
- Repeated transaction IDs flag every row in that ID group. Possible real-world duplicates are detected using the combination of order ID, normalized customer, normalized date, amount, and status, excluding transaction ID.
- Revenue is the sum of valid `paid` rows only. Rows flagged for data issues or duplicates are excluded to avoid double-counting or trusting questionable records.
- Counts in `report.json` reconcile to all rows in `cleaned.csv`.

## Edge case tested
The input includes a transaction with an impossible date (`2026-15-08`), which is marked invalid with `unparseable_or_ambiguous_date`. It also includes malformed/missing/negative/zero amounts and repeated transaction IDs.
