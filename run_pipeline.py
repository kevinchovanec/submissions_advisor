"""
Phase 1+2 CLI entry point.

Usage:
  python run_pipeline.py --duotrope data/duotrope_export.csv
  python run_pipeline.py --duotrope data/duotrope_export.csv --fetch-about
  python run_pipeline.py --duotrope data/duotrope_export.csv --output outputs/my_results.xlsx
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ingest import load as load_duotrope
from scrape_rankings import load_rankings
from match import match, ranked_only, unranked_only
from fetch_about import fetch_about_pages
from output import build


def main():
    parser = argparse.ArgumentParser(description="Submissions Advisor pipeline")
    parser.add_argument("--duotrope", required=True, help="Path to Duotrope CSV export")
    parser.add_argument("--fetch-about", action="store_true", help="Fetch about pages (slow first run)")
    parser.add_argument("--threshold", type=int, default=85, help="Fuzzy match threshold (default: 85)")
    parser.add_argument("--output", help="Output Excel path (default: outputs/open_ranked_journals.xlsx)")
    args = parser.parse_args()

    print("=== Phase 1: Data Ingestion ===")
    journals = load_duotrope(args.duotrope)
    print(f"Loaded {len(journals)} journals from Duotrope export")

    rankings = load_rankings()
    print(f"Loaded {len(rankings)} ranked journals")

    print("\n=== Phase 2: Matching ===")
    matched = match(journals, rankings, threshold=args.threshold)
    ranked = ranked_only(matched)
    unranked = unranked_only(matched)
    print(f"Matched {len(ranked)} journals, {len(unranked)} unranked")

    if args.fetch_about:
        print("\n=== Phase 2b: Fetching About Pages ===")
        matched = fetch_about_pages(matched)

    print("\n=== Output ===")
    output_path = Path(args.output) if args.output else None
    build(matched, output_path=output_path)


if __name__ == "__main__":
    main()
