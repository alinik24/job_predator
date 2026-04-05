"""
JobPredator CLI — main entry point.

=== FIRST-TIME SETUP ===
  python main.py upload-cv my_cv.pdf           # Parse and store your CV
  python main.py profile --init                # Create personal context template
  #  → Edit output/user_profile.yaml
  python main.py learn-style --dir "C:/path/to/Cover Letters"  # Learn your writing style
  python main.py suggest-positions --cv cv.pdf # AI suggests job titles from your CV
  #  → Review/edit output/suggested_positions.yaml

=== SCRAPING & SCORING ===
  python main.py scrape-from-suggestions       # Scrape using approved positions
  python main.py scrape -p "Data Engineer" -l Deutschland  # Manual scrape
  python main.py score                         # Score all unscored jobs
  python main.py score --memory               # Score with adaptive memory

=== PER-JOB ANALYSIS ===
  python main.py analyze-job --job-id <uuid>   # Skills matrix + niche keywords
  python main.py analyze-job --all --min-score 7.5  # Batch analysis
  python main.py job-skills --job-id <uuid>    # View skills analysis
  python main.py cover-letter --job-id <uuid>  # Generate tailored cover letter
  python main.py cover-letter --job-id <uuid> --lang de --output cover.txt

=== LEARNING & MEMORY ===
  python main.py feedback --job-id <uuid> --decision apply --reason "Great fit"
  python main.py remember --skill "Apache Spark" --status have_it
  python main.py memory                        # Show memory state

=== SKILL GAPS ===
  python main.py gaps --min-score 7.5          # Analyse missing skills
  python main.py cv-suggestions                # Get LaTeX CV improvement snippets

=== BROWSE RESULTS ===
  python main.py list-jobs --min-score 7.5
  python main.py list-jobs --min-score 7.5 --gaps

See --help for all options.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="JobPredator — AI-powered adaptive job hunter for Germany")
console = Console()


# ── Helper: load CV profile from DB ──────────────────────────────────────────

def _load_cv_profile_sync():
    """
    Load the most recently stored CV profile using a synchronous psycopg2 connection.
    Used in CLI commands to avoid asyncpg WinError 64 on Windows/Docker.
    """
    import psycopg2
    import psycopg2.extras
    from core.config import settings
    from core.models import CVProfileSchema

    conn = psycopg2.connect(
        settings.database_url_sync.replace("postgresql+psycopg2://", "postgresql://")
    )
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM cv_profile ORDER BY created_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return None

    return CVProfileSchema(
        full_name=row.get("full_name"),
        email=row.get("email"),
        phone=row.get("phone"),
        location=row.get("location"),
        linkedin_url=row.get("linkedin_url"),
        github_url=row.get("github_url"),
        summary=row.get("summary"),
        skills=row.get("skills") or [],
        languages=row.get("languages") or [],
        work_experience=row.get("work_experience") or [],
        education=row.get("education") or [],
        certifications=row.get("certifications") or [],
        raw_text=row.get("raw_text"),
    )


async def _load_cv_profile():
    """Async wrapper — uses sync psycopg2 under the hood for Windows compatibility."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _load_cv_profile_sync)


# ── Run full pipeline ─────────────────────────────────────────────────────────

@app.command()
def run(
    cv: str = typer.Option(..., "--cv", help="Path to CV (PDF, .tex, or Overleaf directory)"),
    positions: List[str] = typer.Option(..., "--position", "-p", help="Job titles to search for"),
    locations: Optional[List[str]] = typer.Option(None, "--location", "-l"),
    sources: Optional[List[str]] = typer.Option(None, "--source", "-s"),
    language: str = typer.Option("de", "--lang"),
    dry_run: bool = typer.Option(True, "--dry-run/--live"),
    stop_before: Optional[str] = typer.Option(None, "--stop-before"),
    use_memory: bool = typer.Option(True, "--memory/--no-memory",
                                    help="Apply adaptive memory adjustments"),
):
    """Run the full JobPredator pipeline (scrape → score → apply → outreach)."""
    from agents.graph import JobPredatorGraph

    console.print("[bold green]JobPredator starting...[/bold green]")
    console.print(f"  CV: {cv}")
    console.print(f"  Positions: {', '.join(positions)}")
    console.print(f"  Locations: {', '.join(locations or ['Deutschland'])}")
    console.print(f"  Dry run: {dry_run} | Memory: {use_memory}")

    async def _run():
        graph = JobPredatorGraph(
            cv_source=cv,
            positions=positions,
            locations=locations,
            sources=sources,
            language=language,
            dry_run=dry_run,
        )
        if stop_before:
            state = await graph.run_until(stop_before)
        else:
            state = await graph.run_full_pipeline()
        graph.print_summary(state)

    asyncio.run(_run())


# ── Scrape ────────────────────────────────────────────────────────────────────

@app.command()
def scrape(
    positions: List[str] = typer.Option(..., "--position", "-p"),
    locations: Optional[List[str]] = typer.Option(None, "--location", "-l"),
    sources: Optional[List[str]] = typer.Option(None, "--source", "-s"),
    max_results: int = typer.Option(50, "--max"),
):
    """Scrape jobs without scoring or applying."""
    from scrapers.aggregator import JobAggregator, ALL_SOURCES
    from core.models import JobSearchParams

    async def _scrape():
        params = JobSearchParams(
            positions=positions,
            locations=locations or ["Deutschland"],
            sources=sources or ALL_SOURCES,
            max_results=max_results,
        )
        agg = JobAggregator(params)
        jobs = await agg.run()
        console.print(f"[green]Scraped {len(jobs)} new jobs[/green]")

    asyncio.run(_scrape())


# ── Suggest positions ─────────────────────────────────────────────────────────

@app.command()
def suggest_positions(
    cv: Optional[str] = typer.Option(None, "--cv",
        help="Path to CV file. If omitted, uses stored profile."),
    output: str = typer.Option("output/suggested_positions.yaml", "--output", "-o"),
):
    """
    Analyse your CV and generate a prioritised list of job titles to search for.

    Creates output/suggested_positions.yaml — review and edit it, then run
    'scrape-from-suggestions' to search using the approved positions.
    """
    from cv.position_generator import PositionGenerator

    async def _suggest():
        if cv:
            from cv.cv_parser import CVParser
            parser = CVParser()
            text = parser.extract_text(cv)
            profile = parser.parse(text)
        else:
            profile = await _load_cv_profile()
            if not profile:
                console.print("[red]No CV profile found. Use --cv or run 'upload-cv' first.[/red]")
                raise typer.Exit(1)

        gen = PositionGenerator()
        suggestions = gen.generate(profile)
        out_path = gen.save_for_review(suggestions, Path(output))

        console.print(f"\n[bold green]Position suggestions saved to: {out_path}[/bold green]")
        console.print("\n[yellow]Next steps:[/yellow]")
        console.print(f"  1. Edit {out_path} — set 'approved: true/false' for each role")
        console.print("  2. Run: python main.py scrape-from-suggestions")

        # Show summary
        table = Table(title="Suggested Job Positions")
        table.add_column("Category")
        table.add_column("Title")
        table.add_column("Confidence")
        table.add_column("Approved by default")

        for role in suggestions.get("primary", []):
            table.add_row("Primary", role["title"],
                          f"{role.get('confidence', 0):.0%}", "YES")
        for role in suggestions.get("research", []):
            table.add_row("Research", role["title"],
                          f"{role.get('confidence', 0):.0%}", "YES")
        for role in suggestions.get("adjacent", []):
            table.add_row("Adjacent", role["title"],
                          f"{role.get('confidence', 0):.0%}", "review")
        for role in suggestions.get("german_specific", []):
            table.add_row("DE-specific", role["title"],
                          f"{role.get('confidence', 0):.0%}", "YES")

        console.print(table)
        if suggestions.get("market_insight"):
            console.print(f"\n[italic]{suggestions['market_insight']}[/italic]")

    asyncio.run(_suggest())


# ── Scrape from suggestions ───────────────────────────────────────────────────

@app.command()
def scrape_from_suggestions(
    suggestions_file: str = typer.Option(
        "output/suggested_positions.yaml", "--file", "-f"),
    locations: Optional[List[str]] = typer.Option(None, "--location", "-l"),
    sources: Optional[List[str]] = typer.Option(None, "--source", "-s"),
    max_results: int = typer.Option(50, "--max"),
):
    """
    Read approved positions from suggestions file and run a scrape.
    Edit output/suggested_positions.yaml first (see suggest-positions).
    """
    from cv.position_generator import PositionGenerator
    from scrapers.aggregator import JobAggregator, ALL_SOURCES
    from core.models import JobSearchParams, SearchSession
    from core.database import get_session

    async def _scrape():
        positions = PositionGenerator.load_approved(Path(suggestions_file))
        if not positions:
            console.print("[red]No approved positions found. Edit the YAML file first.[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Searching for {len(positions)} position types:[/green]")
        for p in positions:
            console.print(f"  • {p}")

        srcs = sources or ALL_SOURCES
        params = JobSearchParams(
            positions=positions,
            locations=locations or ["Deutschland"],
            sources=srcs,
            max_results=max_results,
        )
        agg = JobAggregator(params)
        jobs = await agg.run()

        # Record search session
        async with get_session() as session:
            ss = SearchSession(
                positions_used=positions,
                positions_approved=positions,
                sources=srcs,
                jobs_found=len(jobs),
            )
            session.add(ss)

        console.print(f"[bold green]Scraped {len(jobs)} new jobs[/bold green]")
        console.print("Run 'python main.py score' to score them against your CV.")

    asyncio.run(_scrape())


# ── Score ─────────────────────────────────────────────────────────────────────

@app.command()
def score(
    use_memory: bool = typer.Option(True, "--memory/--no-memory",
                                    help="Use adaptive memory for scoring"),
    batch: int = typer.Option(50, "--batch"),
):
    """Score all unscored jobs against your CV (with memory adjustments)."""

    async def _score():
        cv = await _load_cv_profile()
        if not cv:
            console.print("[red]No CV profile found. Run 'upload-cv' first.[/red]")
            raise typer.Exit(1)

        if use_memory:
            from memory.adaptive_scorer import AdaptiveScorer
            from memory.user_memory import UserMemoryManager
            from scrapers.aggregator import JobAggregator

            mem = await UserMemoryManager().load()
            scorer = AdaptiveScorer(cv, memory=mem)
            jobs = await JobAggregator.get_unscored_jobs(limit=batch)
            if not jobs:
                console.print("[yellow]No unscored jobs found.[/yellow]")
                return
            results = await scorer.score_batch_adaptive(jobs)
            count = len(results)
        else:
            from matching.scorer import score_all_unscored_jobs
            count = await score_all_unscored_jobs(cv, batch_size=batch)

        console.print(f"[green]Scored {count} jobs[/green]")

        from scrapers.aggregator import JobAggregator
        top = await JobAggregator.get_top_jobs(limit=10)
        table = Table(title="Top Matching Jobs")
        table.add_column("Score", style="green")
        table.add_column("Title")
        table.add_column("Company")
        table.add_column("Location")
        table.add_column("Source")
        for j in top:
            table.add_row(
                f"{j.match_score:.1f}", j.title[:55], j.company[:30],
                (j.location or "")[:25], j.source or ""
            )
        console.print(table)

    asyncio.run(_score())


# ── Feedback ──────────────────────────────────────────────────────────────────

@app.command()
def feedback(
    job_id: Optional[str] = typer.Option(None, "--job-id", "-j",
        help="Job UUID. Omit to show interactive list."),
    decision: Optional[str] = typer.Option(None, "--decision", "-d",
        help="interested|apply|skip|not_interested|applied_manually|"
             "got_interview|got_offer|rejected_by_company"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r",
        help="Why you made this decision"),
    user_score: Optional[float] = typer.Option(None, "--score",
        help="Your own score override (0-10)"),
):
    """
    Record your decision on a job — the core learning signal.

    Examples:
      python main.py feedback --job-id <uuid> --decision apply --reason "Love the energy focus"
      python main.py feedback --job-id <uuid> --decision skip --reason "Too much travel"
      python main.py feedback --job-id <uuid> --decision got_interview
    """
    from memory.user_memory import UserMemoryManager

    async def _feedback():
        mem = await UserMemoryManager().load()

        if not job_id:
            # Interactive: show top unreviewed jobs
            from sqlalchemy import select, outerjoin
            from core.database import get_session
            from core.models import Job, JobFeedback

            async with get_session() as session:
                # Jobs with score >= 7.0 that have no feedback yet
                result = await session.execute(
                    select(Job)
                    .where(Job.match_score >= 7.0)
                    .order_by(Job.match_score.desc())
                    .limit(20)
                )
                jobs = result.scalars().all()

                # Get already-reviewed job IDs
                fb_result = await session.execute(select(JobFeedback.job_id))
                reviewed = {row[0] for row in fb_result.fetchall()}

            pending = [j for j in jobs if j.id not in reviewed]
            if not pending:
                console.print("[yellow]All top jobs already reviewed.[/yellow]")
                return

            table = Table(title="Pending Feedback — Top Jobs")
            table.add_column("#")
            table.add_column("Score", style="green")
            table.add_column("Title")
            table.add_column("Company")
            table.add_column("Source")
            table.add_column("ID")
            for i, j in enumerate(pending[:15], 1):
                table.add_row(
                    str(i), f"{j.match_score:.1f}", j.title[:50],
                    j.company[:25], j.source or "", str(j.id)[:8] + "..."
                )
            console.print(table)
            console.print("\n[yellow]Use --job-id <uuid> --decision <decision> to record feedback.[/yellow]")
            console.print("Decisions: interested | apply | skip | not_interested | applied_manually | got_interview | got_offer | rejected_by_company")
            return

        from uuid import UUID as PyUUID
        jid = PyUUID(job_id)
        dec = decision or typer.prompt(
            "Decision (interested/apply/skip/not_interested/got_interview/got_offer/rejected_by_company)"
        )

        fb = await mem.give_feedback(jid, dec, reason=reason, user_score=user_score)
        console.print(f"[green]Feedback recorded: {dec}[/green]"
                      + (f" — '{reason}'" if reason else ""))
        console.print(f"  (ID: {fb.id})")

    asyncio.run(_feedback())


# ── Remember / skill claims ───────────────────────────────────────────────────

@app.command()
def remember(
    skill: Optional[str] = typer.Option(None, "--skill", "-s",
        help="Skill name to claim"),
    status: str = typer.Option("have_it", "--status",
        help="have_it | learning | no"),
    company_blacklist: Optional[str] = typer.Option(None, "--blacklist-company",
        help="Add a company to the permanent blacklist"),
    note: Optional[str] = typer.Option(None, "--note",
        help="Add a personal note to your memory"),
    prefer_position: Optional[str] = typer.Option(None, "--prefer",
        help="Mark a position as preferred"),
    avoid_position: Optional[str] = typer.Option(None, "--avoid",
        help="Mark a position to avoid"),
    show: bool = typer.Option(False, "--show", help="Show current memory state"),
):
    """
    Update your user memory — add skill claims, blacklist companies, set preferences.

    Examples:
      python main.py remember --skill "Apache Spark" --status have_it
      python main.py remember --skill "Kubernetes" --status learning
      python main.py remember --blacklist-company "Bad Corp GmbH"
      python main.py remember --prefer "Research Engineer"
      python main.py remember --avoid "Frontend Developer"
      python main.py remember --note "I prefer energy + AI intersection roles"
      python main.py remember --show
    """
    from memory.user_memory import UserMemoryManager

    async def _remember():
        mem = await UserMemoryManager().load()

        if skill:
            await mem.claim_skill(skill, status)
            console.print(f"[green]Remembered: '{skill}' → {status}[/green]")

        if company_blacklist:
            await mem.blacklist_company(company_blacklist)
            console.print(f"[green]Blacklisted company: {company_blacklist}[/green]")

        if note:
            await mem.set_preference("notes", note)
            console.print(f"[green]Note saved.[/green]")

        if prefer_position:
            await mem.set_position_preference(prefer_position, "preferred")
            console.print(f"[green]Position preferred: {prefer_position}[/green]")

        if avoid_position:
            await mem.set_position_preference(avoid_position, "avoid")
            console.print(f"[green]Position avoided: {avoid_position}[/green]")

        if show or not any([skill, company_blacklist, note, prefer_position, avoid_position]):
            summary = await mem.summary()
            console.print(summary)

    asyncio.run(_remember())


# ── Gap analysis ──────────────────────────────────────────────────────────────

@app.command()
def gaps(
    min_score: float = typer.Option(7.0, "--min-score"),
    top: int = typer.Option(20, "--top"),
    refresh: bool = typer.Option(True, "--refresh/--no-refresh",
        help="Re-analyse gaps from DB (slower but fresh)"),
):
    """
    Analyse skill gaps across your top-scored jobs.
    Shows what the market wants that your CV doesn't yet have.
    """
    from memory.gap_tracker import GapTracker
    from memory.user_memory import UserMemoryManager

    async def _gaps():
        cv = await _load_cv_profile()
        if not cv:
            console.print("[red]No CV profile found. Run 'upload-cv' first.[/red]")
            raise typer.Exit(1)

        mem = await UserMemoryManager().load()
        tracker = GapTracker(cv, memory=mem)

        if refresh:
            console.print("[yellow]Analysing skill gaps from scored jobs...[/yellow]")
            await tracker.analyze_and_store(min_score=min_score)

        report = await tracker.get_gap_report(top_n=top)
        console.print(report)

    asyncio.run(_gaps())


# ── CV suggestions for Overleaf ───────────────────────────────────────────────

@app.command()
def cv_suggestions(
    output: str = typer.Option("output/overleaf_suggestions.tex", "--output", "-o"),
):
    """
    Generate LaTeX CV suggestions to close your skill gaps.
    Copy the output into your Overleaf CV.
    """
    from memory.gap_tracker import GapTracker
    from memory.user_memory import UserMemoryManager

    async def _suggest():
        cv = await _load_cv_profile()
        if not cv:
            console.print("[red]No CV profile. Run 'upload-cv' first.[/red]")
            raise typer.Exit(1)

        mem = await UserMemoryManager().load()
        tracker = GapTracker(cv, memory=mem)

        suggestions = await tracker.get_overleaf_suggestions()
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(suggestions, encoding="utf-8")

        console.print(f"[green]LaTeX CV suggestions saved to: {out}[/green]")
        console.print(suggestions[:1500])

    asyncio.run(_suggest())


# ── Memory overview ───────────────────────────────────────────────────────────

@app.command()
def memory():
    """Show your current user memory state (skill claims, preferences, feedback stats)."""
    from memory.user_memory import UserMemoryManager

    async def _memory():
        mem = await UserMemoryManager().load()
        summary = await mem.summary()
        console.print(summary)

    asyncio.run(_memory())


# ── Upload CV ─────────────────────────────────────────────────────────────────

@app.command()
def upload_cv(
    path: str = typer.Argument(..., help="Path to CV file (PDF, .tex, or Overleaf dir)"),
):
    """Parse and store your CV."""
    from cv.cv_parser import CVParser

    async def _upload():
        parser = CVParser()
        profile = await parser.parse_and_store(path)
        console.print("[green]CV parsed and stored[/green]")
        console.print(f"  Name:       {profile.full_name}")
        console.print(f"  Email:      {profile.email}")
        console.print(f"  Location:   {profile.location}")
        console.print(f"  Skills:     {len(profile.skills or [])} found")
        console.print(f"  Experience: {len(profile.work_experience or [])} positions")
        console.print(f"  Education:  {len(profile.education or [])} entries")

    asyncio.run(_upload())


# ── Upload document ───────────────────────────────────────────────────────────

@app.command()
def upload_doc(
    path: str = typer.Argument(..., help="Path to document"),
    doc_type: str = typer.Option("other", "--type", "-t"),
    name: Optional[str] = typer.Option(None, "--name"),
):
    """Upload a supporting document (certificate, reference letter, etc.)."""
    from documents.store import DocumentStore
    from core.models import DocumentType

    async def _upload():
        try:
            dt = DocumentType(doc_type)
        except ValueError:
            dt = DocumentType.OTHER

        store = DocumentStore()
        doc = await store.upload(path, dt, name)
        console.print(f"[green]Document stored[/green]: {doc.name} ({doc.doc_type})")

    asyncio.run(_upload())


# ── List jobs ─────────────────────────────────────────────────────────────────

@app.command()
def list_jobs(
    min_score: float = typer.Option(0.0, "--min-score"),
    status: Optional[str] = typer.Option(None, "--status"),
    source: Optional[str] = typer.Option(None, "--source"),
    limit: int = typer.Option(20, "--limit"),
    show_gaps: bool = typer.Option(False, "--gaps", help="Show gap reasons"),
):
    """List scraped jobs with filtering."""
    from sqlalchemy import select
    from core.database import get_session
    from core.models import Job

    async def _list():
        async with get_session() as session:
            query = select(Job)
            if min_score > 0:
                query = query.where(Job.match_score >= min_score)
            if status:
                query = query.where(Job.status == status)
            if source:
                query = query.where(Job.source == source)
            query = query.order_by(Job.match_score.desc().nullslast()).limit(limit)
            result = await session.execute(query)
            jobs = result.scalars().all()

        table = Table(title=f"Jobs (min_score={min_score})")
        table.add_column("Score", style="green")
        table.add_column("Title")
        table.add_column("Company")
        table.add_column("Location")
        table.add_column("Source")
        if show_gaps:
            table.add_column("Top Gap")

        for j in jobs:
            score_str = f"{j.match_score:.1f}" if j.match_score else "—"
            row = [score_str, j.title[:55], j.company[:28],
                   (j.location or "")[:22], j.source or ""]
            if show_gaps:
                gaps = (j.match_reasons or {}).get("gaps", [])
                row.append(gaps[0][:40] if gaps else "—")
            table.add_row(*row)

        console.print(table)

    asyncio.run(_list())


# ── API server ────────────────────────────────────────────────────────────────

@app.command()
def api(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
):
    """Start the FastAPI web server."""
    import uvicorn
    console.print(f"[bold]Starting JobPredator API on http://{host}:{port}[/bold]")
    uvicorn.run("api.main:app", host=host, port=port, reload=reload)


# ── Profile ───────────────────────────────────────────────────────────────────

@app.command()
def profile(
    init: bool = typer.Option(False, "--init", help="Create blank profile template"),
    show: bool = typer.Option(False, "--show", help="Print current profile context"),
    path: str = typer.Option("output/user_profile.yaml", "--path"),
):
    """
    Manage your personal profile (beyond the CV).

    The profile is a YAML file you fill out with personal motivation,
    career goals, skill evidence, experience context, and writing preferences.
    It is used to personalise cover letters and scoring.

    To get started:
      python main.py profile --init
      # Then edit output/user_profile.yaml
    """
    from core.user_profile import UserProfileManager

    mgr = UserProfileManager(path)

    if init:
        p = mgr.init(overwrite=False)
        console.print(f"[green]Profile template created:[/green] {p}")
        console.print("Edit it with any text editor, then use it in cover letter generation.")
        return

    if not mgr.exists():
        console.print("[yellow]No profile found. Run with --init to create one.[/yellow]")
        console.print(f"Expected at: {path}")
        return

    if show:
        ctx = mgr.build_context_for_llm()
        if ctx:
            console.print("[bold]Profile context for LLM:[/bold]")
            console.print(ctx)
        else:
            console.print("[yellow]Profile exists but has no filled content yet.[/yellow]")
        return

    data = mgr.load()
    console.print(f"[green]Profile loaded from:[/green] {path}")
    console.print(f"  Career goals: {len(data.get('career_goals', []))} entries")
    console.print(f"  Experience context: {len(data.get('experience_context', []))} roles")
    console.print(f"  Skills with evidence: {len(data.get('skills_with_evidence', []))} entries")
    console.print(f"  Language preference: {data.get('cover_letter_preferences', {}).get('language', 'de')}")
    console.print("Use [bold]--show[/bold] to see the full context the AI will use.")


# ── Learn cover letter style ──────────────────────────────────────────────────

@app.command()
def learn_style(
    directory: str = typer.Option(
        ...,
        "--dir", "-d",
        help="Path to folder containing existing cover letters (PDF, DOCX, TXT)",
    ),
):
    """
    Learn your writing style from existing cover letters.

    Reads all cover letters in the given folder, analyses tone, structure,
    recurring strengths, and characteristic phrases. Stores the style profile
    in the database for use in future cover letter generation.

    Example:
      python main.py learn-style --dir "C:/mydesktop/Career Application/Cover Letters"
    """
    from cv.cover_letter_learner import CoverLetterLearner

    async def _learn():
        learner = CoverLetterLearner()
        style = await learner.learn_and_store(directory)
        console.print(f"[green]Style learned from {style.sample_count:.0f} cover letters[/green]")
        console.print(f"  Tone: {style.style_summary[:100] if style.style_summary else 'N/A'}")
        if style.strengths_highlighted:
            console.print(f"  Recurring strengths: {', '.join(style.strengths_highlighted[:4])}")
        if style.structure_pattern:
            console.print(f"  Structure: {' → '.join(str(s) for s in style.structure_pattern[:3])}")

    asyncio.run(_learn())


# ── Analyse job (skills matrix + niche keywords) ──────────────────────────────

@app.command()
def analyze_job(
    job_id: Optional[str] = typer.Option(None, "--job-id", help="Specific job UUID to analyse"),
    all_jobs: bool = typer.Option(False, "--all", help="Analyse all jobs above min_score"),
    min_score: float = typer.Option(7.0, "--min-score"),
    limit: int = typer.Option(20, "--limit"),
):
    """
    Analyse job requirements for a specific job or batch of jobs.

    Produces:
      - Skills matrix: which required skills you have vs. are missing
      - Niche keywords: company/domain-specific terms to learn
      - CV sections to emphasise for this job
      - ATS score estimate
      - Interview preparation topics

    Example:
      python main.py analyze-job --job-id abc123
      python main.py analyze-job --all --min-score 7.5 --limit 10
    """
    from sqlalchemy import select
    from core.database import get_session
    from core.models import Job
    from matching.job_skills_analyzer import JobSkillsAnalyzer

    async def _analyze():
        cv_profile = await _load_cv_profile()
        if not cv_profile:
            console.print("[red]No CV found. Run: python main.py upload-cv your_cv.pdf[/red]")
            raise typer.Exit(1)

        analyzer = JobSkillsAnalyzer(cv_profile)

        if job_id:
            async with get_session() as session:
                from uuid import UUID as PYUUID
                job = await session.get(Job, PYUUID(job_id))
            if not job:
                console.print(f"[red]Job {job_id} not found[/red]")
                raise typer.Exit(1)
            matrix = await analyzer.analyze_job(job)
            report = JobSkillsAnalyzer.format_skills_report(matrix, job)
            console.print(report)
        elif all_jobs:
            async with get_session() as session:
                result = await session.execute(
                    select(Job)
                    .where(Job.match_score >= min_score)
                    .where(Job.description.isnot(None))
                    .order_by(Job.match_score.desc())
                    .limit(limit)
                )
                jobs = result.scalars().all()

            if not jobs:
                console.print(f"[yellow]No scored jobs found above {min_score}[/yellow]")
                return

            console.print(f"[bold]Analysing {len(jobs)} jobs...[/bold]")
            matrices = await analyzer.analyze_batch(jobs)
            console.print(f"[green]Analysed {len(matrices)} jobs[/green]")

            # Show summary table
            table = Table(title="Skills Analysis Summary")
            table.add_column("Title", max_width=40)
            table.add_column("Company", max_width=25)
            table.add_column("ATS")
            table.add_column("Have")
            table.add_column("Missing")
            table.add_column("Niche KWs")

            for m, j in zip(matrices, jobs):
                have = sum(1 for s in (m.required_skills or []) if s.get("user_has"))
                miss = sum(1 for s in (m.required_skills or []) if not s.get("user_has"))
                table.add_row(
                    j.title[:40], j.company[:25],
                    f"{m.ats_score:.1f}" if m.ats_score else "—",
                    f"[green]{have}[/green]",
                    f"[red]{miss}[/red]",
                    str(len(m.niche_keywords or [])),
                )
            console.print(table)

    asyncio.run(_analyze())


# ── Generate cover letter ─────────────────────────────────────────────────────

@app.command()
def cover_letter(
    job_id: str = typer.Option(..., "--job-id", help="Job UUID to generate cover letter for"),
    language: Optional[str] = typer.Option(None, "--lang", help="de or en (auto-detected if not set)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save to file path"),
    show: bool = typer.Option(True, "--show/--no-show", help="Print the cover letter"),
):
    """
    Generate a tailored cover letter for a specific job.

    Uses your CV, personal profile context, learned writing style, and
    a deep analysis of the job requirements to write a personalised letter.

    Setup (run once):
      python main.py profile --init                         # fill out your profile
      python main.py learn-style --dir "path/to/CLs"       # learn from existing letters

    Then:
      python main.py cover-letter --job-id <uuid>
      python main.py cover-letter --job-id <uuid> --lang de --output cover.txt
    """
    from core.database import get_session
    from core.models import Job
    from matching.cover_letter_generator import CoverLetterGenerator

    async def _generate():
        cv_profile = await _load_cv_profile()
        if not cv_profile:
            console.print("[red]No CV found. Run: python main.py upload-cv your_cv.pdf[/red]")
            raise typer.Exit(1)

        async with get_session() as session:
            from uuid import UUID as PYUUID
            job = await session.get(Job, PYUUID(job_id))
        if not job:
            console.print(f"[red]Job {job_id} not found[/red]")
            raise typer.Exit(1)

        if not job.description:
            console.print("[yellow]Warning: no description stored for this job. Cover letter will be less tailored.[/yellow]")

        generator = CoverLetterGenerator(cv_profile)
        letter = await generator.generate_for_job(
            job,
            language=language,
            output_file=Path(output) if output else None,
        )

        if show:
            console.print(f"\n[bold]Cover Letter — {job.title} @ {job.company}[/bold]")
            console.print("─" * 65)
            console.print(letter)
            console.print("─" * 65)

        if output:
            console.print(f"[green]Saved to:[/green] {output}")
        else:
            console.print(f"[dim]Tip: Add --output cover.txt to save to file[/dim]")

    asyncio.run(_generate())


# ── Show skills matrix for a job ──────────────────────────────────────────────

@app.command()
def job_skills(
    job_id: str = typer.Option(..., "--job-id", help="Job UUID"),
):
    """
    Show the skills analysis for a specific job.

    Run 'analyze-job --job-id <uuid>' first if not yet analysed.
    Shows: skills you have, missing skills, niche keywords, ATS score.
    """
    from core.database import get_session
    from core.models import Job
    from matching.job_skills_analyzer import JobSkillsAnalyzer

    async def _show():
        async with get_session() as session:
            from uuid import UUID as PYUUID
            job = await session.get(Job, PYUUID(job_id))
        if not job:
            console.print(f"[red]Job {job_id} not found[/red]")
            raise typer.Exit(1)

        matrix = await JobSkillsAnalyzer.get_matrix(job.id)
        if not matrix:
            console.print(f"[yellow]No analysis found for this job.[/yellow]")
            console.print(f"Run: python main.py analyze-job --job-id {job_id}")
            return

        console.print(JobSkillsAnalyzer.format_skills_report(matrix, job))

    asyncio.run(_show())


if __name__ == "__main__":
    app()
