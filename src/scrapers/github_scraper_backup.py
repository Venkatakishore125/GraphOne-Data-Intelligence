
import os
import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_API = "https://api.github.com"
TOKEN = os.getenv("GITHUB_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json"
} if TOKEN else {
    "Accept": "application/vnd.github+json"
}


def search_repositories(paper_title):
    """Find candidate GitHub repositories for a research paper."""

    url = f"{GITHUB_API}/search/repositories"

    params = {
        "q": f'"{paper_title}"',
        "sort": "best match",
        "per_page": 5
    }

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=20
        )

        if response.status_code == 200:
            results = response.json().get("items", [])

            candidates = []

            for repo in results:
                candidates.append({
                    "repository_name": repo["full_name"],
                    "repository_url": repo["html_url"],
                    "stars": repo["stargazers_count"],
                    "description": repo["description"]
                })

            return candidates

        print("GitHub search error:", response.status_code)
        return []

    except requests.RequestException as error:
        print("Connection error:", error)
        return []


if __name__ == "__main__":
    title = "PlayCraft: Designing Engaging Games from Agent Play Experience"

    results = search_repositories(title)

    print("Paper title:", title)
    print("Candidate repositories:", len(results))

    for result in results:
        print(result)
