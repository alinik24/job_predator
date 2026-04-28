"""Minimal CLI for CV-markdown-based form filling."""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen

import typer
from rich.console import Console
from rich.table import Table

from agents.form_filler_agent import fill_application_form, list_cdp_tabs

app = typer.Typer(help="MVP job form filler")
console = Console()
DEFAULT_CV_MD = (Path(__file__).resolve().parent / "cv" / "cv.md")


def _normalize_cdp_url(cdp_url: str) -> str:
    raw = (cdp_url or "").strip()
    if not raw:
        return "http://127.0.0.1:9222"
    if not raw.startswith(("http://", "https://")):
        raw = f"http://{raw}"
    return raw.rstrip("/")


def _probe_cdp(cdp_url: str) -> Tuple[bool, str]:
    """
    Returns:
      (reachable, resolved_endpoint)
    resolved_endpoint prefers ws endpoint when available.
    """
    normalized = _normalize_cdp_url(cdp_url)
    if normalized.startswith(("ws://", "wss://")):
        try:
            parsed = urlparse(normalized)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port
            if not port:
                return False, normalized
            with urlopen(f"http://{host}:{port}/json/version", timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
            if ws_url:
                return True, ws_url
            return False, normalized
        except Exception:
            return False, normalized

    endpoint = f"{normalized}/json/version"
    try:
        with urlopen(endpoint, timeout=2) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
        if ws_url:
            return True, ws_url
        return True, normalized
    except Exception:
        return False, normalized


def _extract_value_after_flag(cmdline: str, flag: str) -> Optional[str]:
    # Supports both: --flag=value and --flag "value with spaces"
    pattern = rf"{re.escape(flag)}(?:=|\s+)(\"[^\"]+\"|'[^']+'|\S+)"
    m = re.search(pattern, cmdline, flags=re.IGNORECASE)
    if not m:
        return None
    value = m.group(1).strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.strip() or None


def _read_devtools_active_port(user_data_dir: str) -> List[str]:
    candidates: List[str] = []
    try:
        path = Path(user_data_dir) / "DevToolsActivePort"
        if not path.exists():
            return []
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        if not lines:
            return []
        port = lines[0]
        if port.isdigit():
            candidates.append(f"http://127.0.0.1:{port}")
            if len(lines) >= 2:
                ws_path = lines[1]
                if ws_path.startswith("ws://") or ws_path.startswith("wss://"):
                    candidates.append(ws_path)
                elif ws_path.startswith("/"):
                    candidates.append(f"ws://127.0.0.1:{port}{ws_path}")
    except Exception:
        return []
    return candidates


def _get_browser_process_commandlines() -> List[str]:
    """
    Best-effort: read running Chrome/Edge command lines on Windows.
    """
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('chrome.exe','msedge.exe') } | Select-Object -ExpandProperty CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        out = proc.stdout or ""
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def _discover_cdp_candidates(seed_cdp_url: str) -> List[str]:
    out: List[str] = []
    seen = set()

    def add(value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        key = v.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(v)

    add(_normalize_cdp_url(seed_cdp_url))

    for port in [9222, 9223, 9333, 9229, 9230]:
        add(f"http://127.0.0.1:{port}")
        add(f"http://localhost:{port}")

    cmdlines = _get_browser_process_commandlines()
    for cmd in cmdlines:
        dbg_port = _extract_value_after_flag(cmd, "--remote-debugging-port")
        if dbg_port and dbg_port.isdigit():
            add(f"http://127.0.0.1:{dbg_port}")
            add(f"http://localhost:{dbg_port}")

        user_data_dir = _extract_value_after_flag(cmd, "--user-data-dir")
        if user_data_dir:
            for cdp in _read_devtools_active_port(user_data_dir):
                add(cdp)

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        roots = [
            Path(local_app_data) / "Google" / "Chrome" / "User Data",
            Path(local_app_data) / "Microsoft" / "Edge" / "User Data",
        ]
        for root in roots:
            for cdp in _read_devtools_active_port(str(root)):
                add(cdp)

    return out


def _ensure_existing_browser_connection(cdp_url: str) -> str:
    """
    Interactive recovery flow for attaching to the currently-open Chrome session.
    """
    candidates = _discover_cdp_candidates(cdp_url)
    reachable: List[str] = []
    for candidate in candidates:
        ok, resolved = _probe_cdp(candidate)
        if ok:
            reachable.append(resolved)

    if reachable:
        chosen = reachable[0]
        console.print(f"[green]Connected to current browser endpoint:[/green] {chosen}")
        return chosen

    console.print("\n[yellow]Could not reach Chrome debugging endpoint.[/yellow]")
    console.print("[cyan]To use your current browser session (without opening a new browser):[/cyan]")
    console.print("1. In the same Chrome window, open: [bold]chrome://inspect/#remote-debugging[/bold]")
    console.print('2. Enable: [bold]"Allow remote debugging for this browser instance"[/bold]')
    console.print("3. Keep your job tab open, then return here.")
    console.print("4. Confirm it still shows: [bold]Server running at: 127.0.0.1:9222[/bold]")
    console.print("")

    while True:
        retry = typer.confirm("Retry connection to your current Chrome session now?", default=True)
        if not retry:
            raise typer.Exit(1)
        candidates = _discover_cdp_candidates(cdp_url)
        reachable = []
        for candidate in candidates:
            ok, resolved = _probe_cdp(candidate)
            if ok:
                reachable.append(resolved)
        if reachable:
            chosen = reachable[0]
            console.print(f"[green]Connected to your current Chrome session:[/green] {chosen}")
            return chosen
        console.print("[yellow]Still not reachable. Please enable remote debugging in chrome://inspect/#remote-debugging and retry.[/yellow]")


def _select_tab_url(cdp_url: str, tab_index: Optional[int]) -> str:
    tabs = list_cdp_tabs(cdp_url)
    page_tabs = [t for t in tabs if t.get("type") == "page" and t.get("url")]
    if not page_tabs:
        raise ValueError(f"No browser tabs found at CDP endpoint: {cdp_url}")

    table = Table(title="Open Browser Tabs")
    table.add_column("Index", style="cyan")
    table.add_column("Title", style="magenta")
    table.add_column("URL", style="green")
    for idx, tab in enumerate(page_tabs):
        table.add_row(str(idx), (tab.get("title") or "")[:80], tab.get("url") or "")
    console.print(table)

    if tab_index is None:
        tab_index = typer.prompt("Select tab index", default=0, type=int)
    if tab_index < 0 or tab_index >= len(page_tabs):
        raise ValueError(f"Invalid tab index: {tab_index}")
    return page_tabs[tab_index]["url"]


@app.command("list-tabs")
def list_tabs(
    cdp_url: str = typer.Option("http://127.0.0.1:9222", "--cdp-url", help="Chrome CDP endpoint"),
):
    """List tabs from an existing Chrome debug session."""
    try:
        selected_url = _select_tab_url(cdp_url, tab_index=0)
        console.print(f"[green]Sample selected URL:[/green] {selected_url}")
    except Exception as exc:
        console.print(f"[red]Could not list tabs:[/red] {exc}")
        raise typer.Exit(1)


@app.command("fill-form")
def fill_form(
    url: Optional[str] = typer.Option(None, "--url", help="Job application URL"),
    cv_md: str = typer.Option(str(DEFAULT_CV_MD), "--cv-md", help="Path to CV markdown file"),
    engine: str = typer.Option(
        "playwright",
        "--engine",
        help="Automation engine: browser-use or playwright",
    ),
    use_existing_browser: bool = typer.Option(
        True,
        "--use-existing-browser/--new-browser",
        help="Fill in existing browser tab or open a new controlled browser",
    ),
    cdp_url: str = typer.Option("http://127.0.0.1:9222", "--cdp-url", help="Chrome CDP endpoint"),
    tab_url: Optional[str] = typer.Option(None, "--tab-url", help="Exact tab URL to target in existing browser"),
    tab_index: Optional[int] = typer.Option(None, "--tab-index", help="Tab index from CDP list"),
    submit: bool = typer.Option(False, "--submit", help="Submit after filling"),
    headless: bool = typer.Option(False, "--headless", help="Headless mode for new browser mode"),
    browser_use_llm_provider: str = typer.Option(
        "auto",
        "--browser-use-llm-provider",
        help="browser-use LLM provider: auto, azure, browser-use, openai, google, anthropic",
    ),
    browser_use_model: Optional[str] = typer.Option(
        None,
        "--browser-use-model",
        help="Optional browser-use model override",
    ),
    browser_use_max_steps: int = typer.Option(
        120,
        "--browser-use-max-steps",
        help="Maximum browser-use agent steps",
    ),
    chrome_profile: Optional[str] = typer.Option(
        None,
        "--chrome-profile",
        help="Chrome profile directory (e.g. Default, Profile 1) for browser-use",
    ),
    follow: bool = typer.Option(True, "--follow/--one-pass", help="Keep following page changes and update suggestions"),
    follow_interval: float = typer.Option(1.5, "--follow-interval", help="Follower scan interval in seconds"),
    follow_seconds: int = typer.Option(0, "--follow-seconds", help="Follower duration in seconds (0 = until Ctrl+C)"),
):
    """
    Fill job application fields from a CV markdown file.

    Default CV markdown file: C:\\mydesktop\\resproj_thesis\\job_predator\\cv\\cv.md
    """
    cv_md_path = Path(cv_md)
    if not cv_md_path.exists():
        console.print(f"[red]CV markdown file not found:[/red] {cv_md_path}")
        raise typer.Exit(1)

    if not url and not tab_url:
        url = typer.prompt("Job application URL (paste from your browser tab)").strip()

    if use_existing_browser:
        cdp_url = _ensure_existing_browser_connection(cdp_url)

    resolved_tab_url = tab_url
    if use_existing_browser and resolved_tab_url is None and tab_index is not None:
        try:
            resolved_tab_url = _select_tab_url(cdp_url, tab_index)
        except Exception as exc:
            console.print(f"[yellow]Could not resolve tab by index:[/yellow] {exc}")
            console.print("[yellow]Falling back to URL targeting in existing browser.[/yellow]")

    async def _run() -> None:
        try:
            result = await fill_application_form(
                url=url,
                cv_md_path=cv_md_path,
                submit=submit,
                headless=headless,
                use_existing_browser=use_existing_browser,
                cdp_url=cdp_url,
                tab_url=resolved_tab_url,
                follow=follow,
                follow_interval=follow_interval,
                follow_seconds=follow_seconds,
                engine=engine,
                browser_use_llm_provider=browser_use_llm_provider,
                browser_use_model=browser_use_model,
                browser_use_max_steps=browser_use_max_steps,
                chrome_profile=chrome_profile,
            )
        except Exception as exc:
            if use_existing_browser:
                console.print(f"[red]Could not attach to your current browser:[/red] {exc}")
                console.print("[yellow]Tip:[/yellow] Open chrome://inspect/#remote-debugging in your open Chrome, enable remote debugging, then rerun.")
                raise typer.Exit(1)

            console.print(f"[red]Form filling failed:[/red] {exc}")
            raise typer.Exit(1)

        console.print("[bold green]Form filling complete[/bold green]")
        backend = result.get("backend", engine)
        console.print(f"Engine: {backend}")
        console.print(f"Page: {result.get('url', '')}")
        console.print(f"Fields filled: {result['fields_filled']}/{result['total_fields']}")
        console.print(f"Screenshot: {result['screenshot']}")

        browser_use_data = result.get("browser_use", {})
        final_result = str(browser_use_data.get("final_result", "")).strip()
        if final_result:
            console.print("[cyan]browser-use summary:[/cyan]")
            console.print(final_result)

        unresolved = result.get("unfilled_required_fields", [])
        if unresolved:
            console.print("[yellow]Required fields needing manual review:[/yellow]")
            for item in unresolved:
                console.print(f"  - {item.get('label') or item.get('name')} ({item.get('type')})")
                suggested = (item.get("suggested") or "").strip()
                if suggested:
                    console.print(f"    suggestion: {suggested}")

                candidates = item.get("candidate_values") or []
                if candidates:
                    console.print("    copy-paste options:")
                    for idx, value in enumerate(candidates, start=1):
                        console.print(f"      {idx}. {value}")

                options = item.get("options") or []
                if options:
                    console.print("    dropdown options (top):")
                    for idx, value in enumerate(options[:6], start=1):
                        console.print(f"      {idx}. {value}")

    if follow:
        if follow_seconds > 0:
            console.print(f"[cyan]Follower mode active for {follow_seconds}s[/cyan]")
        else:
            console.print("[cyan]Follower mode active until Ctrl+C[/cyan]")
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Follower stopped by user.[/yellow]")


if __name__ == "__main__":
    app()
