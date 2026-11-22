
import asyncio
import aiohttp
import certifi
import ssl
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timezone
from pathlib import Path

# arXiv API endpoint
ARXIV_API = "https://export.arxiv.org/api/query"


async def fetch_papers(max_results=100):

    print("Connecting to arXiv API...")

    params = {
        "search_query": "all:artificial intelligence",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }

    headers = {
        "User-Agent": "GraphOneDataPipeline/1.0"
    }

    timeout = aiohttp.ClientTimeout(total=90)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    async with aiohttp.ClientSession(
        headers=headers,
        timeout=timeout,
        connector=connector
    ) as session:

        async with session.get(
            ARXIV_API,
            params=params
        ) as response:

            response.raise_for_status()
            xml_data = await response.text()

    root = ET.fromstring(xml_data)

    namespace = {
        "atom": "http://www.w3.org/2005/Atom"
    }

    papers = []

    for entry in root.findall("atom:entry", namespace):

        title = entry.findtext(
            "atom:title",
            default="",
            namespaces=namespace
        )

        paper_url = entry.findtext(
            "atom:id",
            default="",
            namespaces=namespace
        )

        published_date = entry.findtext(
            "atom:published",
            default="",
            namespaces=namespace
        )

        authors = [
            author.findtext(
                "atom:name",
                default="",
                namespaces=namespace
            )
            for author in entry.findall(
                "atom:author", namespace
            )
        ]

        paper = {
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "content": {
                "title": " ".join(title.split()),
                "authors": authors,
                "paper_url": paper_url,
                "github_url": None,
                "github_stars": None,
                "published_date": published_date
            },
            "collectedAt": datetime.now(
                timezone.utc
            ).isoformat()
        }

        papers.append(paper)

    return papers


def save_results(papers):

    output_folder = Path("data")
    output_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = output_folder / "research_papers.json"

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            papers,
            file,
            indent=4,
            ensure_ascii=False
        )

    print(f"Total papers collected: {len(papers)}")
    print(f"Saved successfully: {output_file}")


async def main():

    print("=" * 45)
    print("GRAPHONE DATA INTELLIGENCE PIPELINE")
    print("Research Paper Collection")
    print("=" * 45)

    papers = await fetch_papers(max_results=100)

    save_results(papers)

    print("Research paper collection completed!")


if __name__ == "__main__":
    asyncio.run(main())
