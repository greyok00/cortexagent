#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

DEFAULT_ROOT = Path(os.environ.get("COURSES_ROOT", Path.home() / "courses"))
DEFAULT_OUT = Path(os.environ.get(
    "COURSE_AUDIT_OUT", Path.home() / "tmp" / "course-audit"))
DEFAULT_HUB = Path(os.environ.get(
    "MASTER_HUB", Path.home() / "master-website" / "index.html"))
VIEWPORT = {"width": 390, "height": 844}

EXTERNAL_RE = re.compile(
    r"^(?:[a-z][a-z0-9+.-]*:|//)", re.I)
SOURCE_SUMMARY_RE = re.compile(r"^Sources\s*\((\d+)\)$")
NO_VIDEO = "No verified video for this module"






def find_courses(root: Path) -> list[Path]:

    return sorted(path.parent for path in root.glob("*/*/course.yaml"))


def find_incomplete(root: Path) -> list[Path]:

    found = []
    for path in sorted(root.glob("*/*")):
        if not path.is_dir() or (path / "course.yaml").exists():
            continue
        if any((path / name).exists() for name in ("modules", "assets", "site")):
            found.append(path)
    return found


def course_pages(course_dir: Path) -> list[tuple[str, Path]]:

    site = course_dir / "site"
    pages = [
        ("guide", site / "index.html"),
        ("course", site / "course" / "index.html"),
        ("glossary", site / "course" / "glossary" / "index.html"),
    ]
    modules = sorted(
        (site / "course" / "modules").glob("*/index.html"))
    pages += [(f"module-{m.parent.name}", m) for m in modules]
    return pages






def _resolve_internal(page: Path, raw: str) -> Path | str | None:

    value = (raw or "").strip()
    if not value or value.startswith("#") or EXTERNAL_RE.match(value):
        return None
    path = value.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return None
    return (page.parent / unquote(path)).resolve()


def static_checks(kind: str, path: Path) -> list[str]:

    from bs4 import BeautifulSoup

    problems: list[str] = []
    if not path.exists() or not path.is_file():
        return [f"missing page: {path}"]
    try:
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    except Exception as exc:
        return [f"cannot parse {path}: {exc}"]

    scripts = soup.find_all("script")
    iframes = soup.find_all("iframe")
    if scripts:
        problems.append(f"{len(scripts)} script tag(s)")
    if iframes:
        problems.append(f"{len(iframes)} iframe(s)")


    for tag in soup.find_all(["a", "link", "img"]):
        raw = tag.get("href") or tag.get("src")
        target = _resolve_internal(path, raw)
        if target is None:
            continue
        if not target.exists():
            problems.append(f"broken link: {raw}")
        elif target.is_dir():
            problems.append(f"directory-form link (needs index.html): {raw}")


    for number, table in enumerate(soup.find_all("table"), 1):
        caption = table.find("caption")
        if caption is None or not caption.get_text(" ", strip=True):
            problems.append(f"table {number}: missing caption")
        headers = table.find_all("th")
        if headers:
            unscoped = [th for th in headers if th.get("scope") != "col"]
            if unscoped:
                problems.append(
                    f"table {number}: {len(unscoped)} header cell(s) without "
                    f"scope=\"col\"")
        wrapper = table.find_parent("div", class_="tablewrap")
        if wrapper is None:
            problems.append(f"table {number}: missing .tablewrap scroll wrapper")

    if kind == "guide":
        details = soup.find("details", class_="sources")
        if details is None:
            problems.append("missing collapsed <details class='sources'>")
        else:
            summary = details.find("summary")
            summary_text = summary.get_text(" ", strip=True) if summary else ""
            if not SOURCE_SUMMARY_RE.match(summary_text):
                problems.append(
                    f"sources summary is {summary_text!r}, expected "
                    "'Sources (N)'")
            if not details.find(["li", "a"]):
                problems.append("collapsed sources list is empty")

    if kind.startswith("module-"):
        text = soup.get_text(" ", strip=True)
        count = text.count(NO_VIDEO)
        if count > 1:
            problems.append(
                f"duplicate no-video notes, found {count}")
        if "No worked example is recorded" in text:
            problems.append("no-worked-example placeholder is visible")
        if soup.find("nav", class_="modnav") is None:
            problems.append("missing prev/next module navigation")

    return problems


def audit_hub(path: Path) -> list[str]:

    from bs4 import BeautifulSoup

    if not path.exists():
        return [f"missing hub: {path}"]
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    problems: list[str] = []
    if soup.find_all("script"):
        problems.append(f"{len(soup.find_all('script'))} script tag(s)")
    if soup.find_all("iframe"):
        problems.append(f"{len(soup.find_all('iframe'))} iframe(s)")
    if not soup.find("meta", attrs={"name": "description"}):
        problems.append("missing meta description")
    main = soup.find("main")
    if main is None or main.get("id") != "content":
        problems.append("skip-link target is not <main id='content'>")
    for tag in soup.find_all(["a", "link", "img"]):
        raw = tag.get("href") or tag.get("src")
        target = _resolve_internal(path, raw)
        if target is None:
            continue
        if not target.exists():
            problems.append(f"broken link: {raw}")
        elif target.is_dir():
            problems.append(f"directory-form link (needs index.html): {raw}")
    return problems






def load_sync_playwright():

    try:
        from patchright.sync_api import sync_playwright  # type: ignore
        return sync_playwright, "patchright"
    except Exception:
        from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright, "playwright"


def audit_page(page, label: str, path: Path, out_dir: Path) -> dict:
    result = {"label": label, "path": str(path), "ok": False}
    if not path.exists():
        result["error"] = f"missing page: {path}"
        return result
    page.set_viewport_size(VIEWPORT)
    page.goto(path.as_uri(), wait_until="load")
    metrics = page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth,"
        " innerWidth: window.innerWidth,"
        " clientWidth: document.documentElement.clientWidth,"
        " scripts: document.querySelectorAll('script, iframe').length})")
    shot = out_dir / f"{label}.png"
    page.screenshot(path=str(shot))
    result.update(metrics)
    result["screenshot"] = str(shot)


    result["ok"] = (
        int(metrics["scrollWidth"]) <= int(metrics["innerWidth"])
        and int(metrics["scrollWidth"]) <= int(metrics["clientWidth"])
        and int(metrics["scripts"]) == 0)
    return result


def run_browser_checks(pages_by_course, out_dir: Path,
                       hub: Path | None = None) -> list[str]:
    sync_playwright, engine = load_sync_playwright()
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    with sync_playwright() as playwright:


        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception:
            browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        for course_dir, pages in pages_by_course:
            prefix = f"{course_dir.parent.name}-{course_dir.name}"
            for kind, path in pages:
                label = f"{prefix}-{kind}"
                check = audit_page(page, label, path, out_dir)
                if not check["ok"]:
                    detail = check.get("error")
                    if not detail:
                        if check.get("scrollWidth", 0) > check.get("innerWidth", 0):
                            detail = (f"scrollWidth {check.get('scrollWidth')} "
                                      f"> innerWidth {check.get('innerWidth')}")
                        elif (check.get("scrollWidth", 0)
                              > check.get("clientWidth", 0)):
                            detail = (f"scrollWidth {check.get('scrollWidth')} "
                                      f"> clientWidth {check.get('clientWidth')}")
                        else:
                            detail = f"{check.get('scripts')} script/iframe tag(s)"
                    failures.append(f"{course_dir.name}/{label}: {detail}")
        if hub is not None and hub.exists():
            check = audit_page(page, "hub", hub, out_dir)
            if not check["ok"]:
                detail = check.get("error") or (
                    f"scrollWidth {check.get('scrollWidth')} > innerWidth "
                    f"{check.get('innerWidth')}; "
                    f"{check.get('scripts')} script/iframe tag(s)")
                failures.append(f"hub: {detail}")
        context.close()
        browser.close()
    print(f"browser engine: {engine}")
    return failures






def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit built course sites: links, tables, sources, "
                    "placeholders, scripts, and 390px overflow.")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                    help=f"course root (default {DEFAULT_ROOT})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"screenshot directory (default {DEFAULT_OUT})")
    ap.add_argument("--only", default=None,
                    help="audit one family, slug, or family/slug")
    ap.add_argument("--hub", type=Path, default=DEFAULT_HUB,
                    help=f"master hub page (default {DEFAULT_HUB})")
    ap.add_argument("--no-browser", action="store_true",
                    help="static checks only (no 390px screenshots)")
    args = ap.parse_args(argv)

    courses = find_courses(args.root)
    if args.only:
        courses = [c for c in courses
                   if args.only in (c.name, c.parent.name,
                                    f"{c.parent.name}/{c.name}")]
    if not courses:
        print(f"no courses found under {args.root}", file=sys.stderr)
        return 1

    failures: list[str] = []
    incomplete: list[str] = []
    completed: list[tuple[Path, list[tuple[str, Path]]]] = []
    total_pages = 0

    for course_dir in courses:
        pages = course_pages(course_dir)
        if not pages[0][1].exists():
            incomplete.append(f"{course_dir.parent.name}/{course_dir.name}")
            continue
        completed.append((course_dir, pages))
        total_pages += len(pages)
        for kind, path in pages:
            for problem in static_checks(kind, path):
                failures.append(
                    f"{course_dir.parent.name}/{course_dir.name}/{kind}: "
                    f"{problem}")

    hub_problems = audit_hub(args.hub)
    failures.extend(f"hub: {problem}" for problem in hub_problems)

    if not args.no_browser:
        failures.extend(run_browser_checks(completed, args.out, args.hub))
    else:
        print("browser checks skipped (--no-browser)")

    for course_dir, pages in completed:
        label = f"{course_dir.parent.name}/{course_dir.name}"
        print(f"{label}: {len(pages)} page(s) checked")

    for path in find_incomplete(args.root):
        incomplete.append(f"{path.parent.name}/{path.name} (no course.yaml)")
    if incomplete:
        print("incomplete (skipped): " + "; ".join(incomplete))

    print(f"audit: {len(completed)} completed course(s), {total_pages} "
          f"course page(s), {len(failures)} failure(s)")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
