"""Batch-export invoices to ERP import Excel files.

Replaces the repetitive GUI sequence:
open PDF → drop zero rows → format for import → save Excel.

Never overwrites existing files unless --force is passed.
Never deletes or moves source PDFs.
Skips Leone / Sola Swiss invoices that need a transport amount
unless it was found on the PDF or --transport is provided.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from pipeline import (
    format_for_import,
    needs_manual_transport,
    parse_invoices,
)


def iter_pdfs(input_dir: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(p for p in input_dir.glob(pattern) if p.is_file())


def export_one(
    pdf_path: Path,
    output_dir: Path,
    *,
    transport: float,
    force: bool,
    dry_run: bool,
    allow_missing_transport: bool,
) -> list[dict]:
    parsed_docs = parse_invoices(pdf_path, transport_cost=transport)
    results: list[dict] = []
    for parsed in parsed_docs:
        results.append(
            _export_parsed(
                pdf_path,
                parsed,
                output_dir,
                force=force,
                dry_run=dry_run,
                allow_missing_transport=allow_missing_transport,
            )
        )
    return results


def _export_parsed(
    pdf_path: Path,
    parsed,
    output_dir: Path,
    *,
    force: bool,
    dry_run: bool,
    allow_missing_transport: bool,
) -> dict:
    label = parsed.invoice_number or pdf_path.name
    if needs_manual_transport(parsed.vendor, parsed.transport_cost) and not allow_missing_transport:
        return {
            "file": f"{pdf_path} [{label}]",
            "status": "skipped",
            "vendor": parsed.vendor,
            "reason": "transport amount required (pass --transport N or use GUI)",
            "output": "",
        }

    formatted = format_for_import(
        parsed.rows,
        parsed.pdf_total_amount,
        parsed.transport_cost,
    )
    suffix = f"_{parsed.invoice_number}" if parsed.invoice_number else ""
    out_path = output_dir / f"{pdf_path.stem}{suffix}_import.xlsx"
    if out_path.exists() and not force:
        return {
            "file": f"{pdf_path} [{label}]",
            "status": "skipped",
            "vendor": parsed.vendor,
            "reason": f"output exists (use --force): {out_path.name}",
            "output": str(out_path),
        }

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        formatted.df.to_excel(out_path, index=False)

    return {
        "file": f"{pdf_path} [{label}]",
        "status": "ok" if formatted.matched else "ok_unmatched_total",
        "vendor": parsed.vendor,
        "reason": (
            f"invoice={label} rows={len(formatted.df)} "
            f"target={formatted.target_grand_total:.2f} "
            f"sim={formatted.simulated_sum:.2f}"
        ),
        "output": str(out_path),
    }


def write_report(rows: list[dict], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["file", "status", "vendor", "reason", "output"]
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-convert invoice PDFs to 3-column ERP import Excel files."
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Folder containing PDF invoices",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write *_import.xlsx files (default: <input_dir>/excel_import)",
    )
    parser.add_argument(
        "--transport",
        type=float,
        default=0.0,
        help="External transport amount in EUR when the PDF does not include it",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Include PDFs in subfolders",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing Excel files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing Excel files",
    )
    parser.add_argument(
        "--allow-missing-transport",
        action="store_true",
        help="Process Leone/Sola Swiss even if transport is 0 (usually wrong for ERP)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="CSV report path (default: <output_dir>/batch_export_report.csv)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        print(f"Input folder not found: {input_dir}", file=sys.stderr)
        return 2

    output_dir = (args.output_dir or (input_dir / "excel_import")).resolve()
    pdfs = iter_pdfs(input_dir, args.recursive)
    if not pdfs:
        print(f"No PDF files found in {input_dir}")
        return 1

    results: list[dict] = []
    for pdf_path in pdfs:
        try:
            batch_results = export_one(
                pdf_path,
                output_dir,
                transport=args.transport,
                force=args.force,
                dry_run=args.dry_run,
                allow_missing_transport=args.allow_missing_transport,
            )
        except Exception as exc:
            batch_results = [
                {
                    "file": str(pdf_path),
                    "status": "error",
                    "vendor": "",
                    "reason": str(exc),
                    "output": "",
                }
            ]
        for result in batch_results:
            results.append(result)
            print(f"[{result['status']}] {pdf_path.name} {result['vendor']} — {result['reason']}")

    report_path = args.report or (output_dir / "batch_export_report.csv")
    if not args.dry_run:
        try:
            write_report(results, report_path)
        except PermissionError:
            report_path = output_dir / "batch_export_report_new.csv"
            write_report(results, report_path)
        print(f"Report: {report_path}")

    errors = sum(1 for row in results if row["status"] == "error")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
