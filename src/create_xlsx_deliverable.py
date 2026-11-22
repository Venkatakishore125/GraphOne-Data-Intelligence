import csv
from pathlib import Path

import xlsxwriter


ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ROOT / "deliverables"
OUTPUT = ROOT / "GraphOne_Assessment_Deliverables.xlsx"


def main():
    workbook = xlsxwriter.Workbook(str(OUTPUT))
    sheet_names = [
        ("startups.csv", "Startups"),
        ("products.csv", "Products"),
        ("research_papers.csv", "Research Papers"),
        ("jobs.csv", "Jobs"),
        ("news.csv", "News"),
        ("entity_mapping_log.csv", "Entity Mapping Log"),
    ]
    for filename, title in sheet_names:
        source = DELIVERABLES / filename
        worksheet = workbook.add_worksheet(title)
        if not source.exists():
            continue
        with source.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                worksheet.write(row_index, column_index, value)
        if rows:
            worksheet.autofilter(0, 0, len(rows) - 1, len(rows[0]) - 1)
            worksheet.freeze_panes(1, 0)
    workbook.close()
    return OUTPUT


if __name__ == "__main__":
    print(main())
