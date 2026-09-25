"""
GitHub Job Scraper
==================
Mines job postings from:
1. GitHub repository READMEs with hiring indicators ("We're hiring", "Jobs", "Careers")
2. Company career pages linked from repos
3. Open source project "Help Wanted" issues tagged with "job" or "hiring"
"""

import asyncio
import re
from typing import List, Dict, Optional
import httpx
from bs4 import BeautifulSoup
from loguru import logger


class GitHubJobScraper:
    """Scrapes job postings from GitHub repos and organizations"""

    BASE_URL = "https://api.github.com"
    SEARCH_URL = f"{BASE_URL}/search"

    HIRING_KEYWORDS = [
        "we're hiring", "we are hiring", "join our team", "careers",
        "job openings", "open positions", "work with us", "jobs at",
        "🚀 hiring", "💼 careers", "join us"
    ]

    def __init__(self, github_token: Optional[str] = None):
        """
        Args:
            github_token: GitHub Personal Access Token for higher rate limits
                         (5000 req/hr vs 60 req/hr unauthenticated)
        """
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "JobPredator/1.0"
        }
        if github_token:
            self.headers["Authorization"] = f"token {github_token}"

    async def search_repos_with_jobs(
        self,
        topics: List[str] = None,
        location: str = "Germany",
        min_stars: int = 100,
        max_results: int = 50
    ) -> List[Dict]:
        """
        Search GitHub repositories that might have job postings.

        Args:
            topics: GitHub topics to search (e.g., ["energy", "machine-learning"])
            location: Company location filter
            min_stars: Minimum repository stars
            max_results: Maximum results to return

        Returns:
            List of potential job postings found in READMEs
        """
        topics = topics or ["machine-learning", "data-science", "energy", "ai"]
        jobs = []

        async with httpx.AsyncClient(timeout=30.0, headers=self.headers) as client:
            for topic in topics:
                # Search for repos with hiring keywords in README
                for keyword in self.HIRING_KEYWORDS[:3]:  # Limit to avoid rate limits
                    query = f"{keyword} topic:{topic} stars:>{min_stars} in:readme"
                    if location:
                        query += f" location:{location}"

                    url = f"{self.SEARCH_URL}/repositories"
                    params = {"q": query, "per_page": min(max_results, 30), "sort": "stars"}

                    try:
                        response = await client.get(url, params=params)
                        response.raise_for_status()
                        data = response.json()

                        for repo in data.get("items", []):
                            job = await self._extract_job_from_repo(client, repo)
                            if job:
                                jobs.append(job)

                        # Respect rate limits
                        await asyncio.sleep(1)

                    except httpx.HTTPStatusError as e:
                        logger.warning(f"GitHub API error: {e.response.status_code}")
                        if e.response.status_code == 403:  # Rate limit
                            logger.error("GitHub rate limit exceeded. Use a token for higher limits.")
                            break
                    except Exception as e:
                        logger.error(f"Error searching GitHub: {e}")

        logger.info(f"Found {len(jobs)} potential job postings from GitHub")
        return jobs[:max_results]

    async def _extract_job_from_repo(self, client: httpx.AsyncClient, repo: Dict) -> Optional[Dict]:
        """Extract job information from repository README"""
        try:
            # Fetch README
            readme_url = repo.get("html_url") + "/blob/main/README.md"
            raw_readme_url = readme_url.replace("/blob/", "/raw/")

            response = await client.get(raw_readme_url)
            if response.status_code == 404:
                # Try master branch
                raw_readme_url = raw_readme_url.replace("/main/", "/master/")
                response = await client.get(raw_readme_url)

            if response.status_code != 200:
                return None

            readme_text = response.text

            # Extract career page links
            career_links = self._extract_career_links(readme_text, repo.get("html_url", ""))

            # Extract job-related sections
            job_section = self._extract_job_section(readme_text)

            if not job_section and not career_links:
                return None

            # Get company info from repo
            owner = repo.get("owner", {})
            company_name = owner.get("login", "Unknown")

            return {
                "title": f"Engineering Position at {company_name}",
                "company": company_name,
                "location": owner.get("location") or repo.get("language") or "Germany",
                "description": job_section or f"Check careers page: {career_links[0] if career_links else repo.get('html_url')}",
                "url": career_links[0] if career_links else repo.get("html_url"),
                "source": "github",
                "company_url": owner.get("html_url"),
                "repo_stars": repo.get("stargazers_count", 0),
                "repo_name": repo.get("full_name"),
                "topics": repo.get("topics", []),
                "career_links": career_links
            }

        except Exception as e:
            logger.debug(f"Error extracting job from {repo.get('full_name')}: {e}")
            return None

    def _extract_career_links(self, readme: str, repo_url: str) -> List[str]:
        """Extract career page URLs from README"""
        patterns = [
            r'https?://[^\s\)]+(?:careers|jobs|hiring|join)[^\s\)]*',
            r'\[.*?(?:career|job|hiring|join).*?\]\((https?://[^\)]+)\)',
        ]

        links = []
        for pattern in patterns:
            matches = re.findall(pattern, readme, re.IGNORECASE)
            links.extend(matches)

        # Deduplicate
        return list(dict.fromkeys(links))[:5]

    def _extract_job_section(self, readme: str) -> str:
        """Extract job/hiring section from README"""
        # Find section with hiring keywords
        lines = readme.split('\n')
        in_job_section = False
        job_lines = []

        for i, line in enumerate(lines):
            # Check if line is a heading with hiring keywords
            if re.match(r'^#{1,3}\s+', line):
                if any(kw in line.lower() for kw in ["career", "job", "hiring", "join", "work with us"]):
                    in_job_section = True
                    job_lines.append(line)
                    continue
                elif in_job_section:
                    # End of job section
                    break

            if in_job_section:
                job_lines.append(line)
                # Limit to 500 chars
                if len('\n'.join(job_lines)) > 500:
                    break

        return '\n'.join(job_lines).strip()


async def scrape_github_jobs(
    topics: List[str] = None,
    location: str = "Germany",
    min_stars: int = 100,
    github_token: Optional[str] = None
) -> List[Dict]:
    """
    Convenience function to scrape GitHub jobs.

    Usage:
        jobs = await scrape_github_jobs(
            topics=["energy", "machine-learning"],
            location="Germany",
            github_token=os.getenv("GITHUB_TOKEN")
        )
    """
    scraper = GitHubJobScraper(github_token=github_token)
    return await scraper.search_repos_with_jobs(
        topics=topics,
        location=location,
        min_stars=min_stars
    )


# For testing
if __name__ == "__main__":
    async def test():
        jobs = await scrape_github_jobs(
            topics=["python", "machine-learning"],
            location="Germany",
            min_stars=50
        )
        for job in jobs[:5]:
            print(f"\n{job['title']} @ {job['company']}")
            print(f"⭐ {job['repo_stars']} stars | {job['url']}")
            print(f"Topics: {', '.join(job['topics'])}")

    asyncio.run(test())
