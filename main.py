"""Minimal CLI for CV-markdown-based form filling."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen

import typer
from rich.console import Console
from rich.table import Table

from agents.form_filler_agent import fill_application_form, list_cdp_tabs

app = typer.Typer(help="MVP job form filler")
console = Console()
DEFAULT_CV_MD = (Path(__file__).resolve().parent / "cv" / "cv.md")
MANAGED_CHROME_DIR = Path(__file__).resolve().parent / "output" / "managed_chrome_profile"


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
            with urlopen(f"http://{host}:{port}/json/version", timeout=3) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
            if ws_url:
                return True, ws_url
            return False, normalized
        except Exception:
            return False, normalized

    endpoint = f"{normalized}/json/version"
    try:
        with urlopen(endpoint, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
        if ws_url:
            return True, ws_url
        # Even without ws_url, if we got a response, connection is valid
        return True, normalized
    except Exception as e:
        # Try /json endpoint as fallback
        try:
            with urlopen(f"{normalized}/json", timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if isinstance(data, list) and len(data) > 0:
                    # CDP is reachable
                    return True, normalized
        except Exception:
            pass
        return False, normalized


def _get_chrome_executable() -> Optional[str]:
    """Find Chrome executable path."""
    paths = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def _get_default_chrome_user_data_dir() -> Optional[Path]:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        return None
    candidate = Path(local_app_data) / "Google" / "Chrome" / "User Data"
    return candidate if candidate.exists() else None


def _copy_profile_tree_once(src_root: Path, dst_root: Path) -> None:
    """
    Create managed debug profile by cloning current Chrome profile once.
    We intentionally avoid copying lock and crash artifacts.
    """
    if dst_root.exists():
        return

    dst_root.parent.mkdir(parents=True, exist_ok=True)
    ignore_names = {
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
        "DevToolsActivePort",
        "BrowserMetrics",
        "Crashpad",
        "Safe Browsing",
        "ShaderCache",
        "Code Cache",
        "GrShaderCache",
        "DawnCache",
    }

    def ignore_filter(_dir: str, names: list[str]) -> set[str]:
        ignored = set()
        for name in names:
            if name in ignore_names:
                ignored.add(name)
        return ignored

    shutil.copytree(src_root, dst_root, dirs_exist_ok=False, ignore=ignore_filter)


def _ensure_managed_profile_dir() -> Path:
    """
    Return a persistent managed user-data-dir for Chrome remote debugging.
    On first use, clone from the default Chrome User Data so auth/session persists.
    """
    managed_root = MANAGED_CHROME_DIR
    if managed_root.exists():
        return managed_root

    src_root = _get_default_chrome_user_data_dir()
    if not src_root:
        managed_root.mkdir(parents=True, exist_ok=True)
        return managed_root

    console.print("[cyan]Preparing managed Chrome profile (first run only)...[/cyan]")
    try:
        _copy_profile_tree_once(src_root, managed_root)
    except Exception:
        # Fallback to empty managed directory if cloning fails.
        managed_root.mkdir(parents=True, exist_ok=True)
    return managed_root


def _parse_cdp_port(cdp_url: str) -> int:
    normalized = _normalize_cdp_url(cdp_url)
    parsed = urlparse(normalized)
    return parsed.port or 9222


def _start_managed_chrome(port: int) -> bool:
    """
    Launch (or relaunch) Chrome in deterministic debug mode.
    Keeps session via Chrome's own session restore.
    """
    chrome_exe = _get_chrome_executable()
    if not chrome_exe:
        console.print("[red]Chrome executable not found.[/red]")
        return False

    # Required on Windows to ensure debug flag applies to the new browser process.
    console.print("[cyan]Restarting Chrome in managed debug mode...[/cyan]")
    try:
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except Exception:
        pass
    time.sleep(1.5)

    managed_user_data_dir = _ensure_managed_profile_dir()

    args = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={managed_user_data_dir}",
        "--profile-directory=Default",
        "--restore-last-session",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return True
    except Exception:
        return False


def _wait_for_cdp(cdp_url: str, timeout_seconds: int = 25) -> Optional[str]:
    start = time.time()
    while (time.time() - start) < timeout_seconds:
        ok, resolved = _probe_cdp(cdp_url)
        if ok:
            return resolved
        time.sleep(0.75)
    return None


def _ensure_managed_debug_chrome(cdp_url: str) -> str:
    """
    Deterministic mode:
      - attach if already reachable
      - otherwise restart Chrome once in debug mode and wait
    """
    initial = _wait_for_cdp(cdp_url, timeout_seconds=2)
    if initial:
        console.print(f"[green]Connected to managed Chrome:[/green] {initial}")
        return initial

    port = _parse_cdp_port(cdp_url)
    if not _start_managed_chrome(port):
        raise typer.Exit("Failed to launch managed Chrome in debug mode.")

    resolved = _wait_for_cdp(f"http://127.0.0.1:{port}", timeout_seconds=30)
    if resolved:
        console.print(f"[green]Managed Chrome ready:[/green] {resolved}")
        return resolved

    # One recovery pass: rebuild managed profile and relaunch.
    console.print("[yellow]Managed profile may be stale. Rebuilding once and retrying...[/yellow]")
    try:
        if MANAGED_CHROME_DIR.exists():
            shutil.rmtree(MANAGED_CHROME_DIR, ignore_errors=True)
    except Exception:
        pass
    if _start_managed_chrome(port):
        resolved = _wait_for_cdp(f"http://127.0.0.1:{port}", timeout_seconds=30)
        if resolved:
            console.print(f"[green]Managed Chrome ready after rebuild:[/green] {resolved}")
            return resolved

    chrome_exe = _get_chrome_executable() or "chrome.exe"
    managed_user_data_dir = _ensure_managed_profile_dir()
    raise typer.Exit(
        "Managed Chrome did not expose CDP.\n"
        "Run this manually once, then retry:\n"
        f'"{chrome_exe}" --remote-debugging-port={port} --remote-debugging-address=127.0.0.1 '
        f'--user-data-dir="{managed_user_data_dir}" --profile-directory=Default --restore-last-session'
    )


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
        cdp_url = _ensure_managed_debug_chrome(cdp_url)

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
