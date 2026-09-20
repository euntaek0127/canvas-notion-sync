#!/usr/bin/env python3
"""Sync active-course Canvas assignments into a Notion Agenda database."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


NOTION_VERSION = "2025-09-03"


class SyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class CoursePage:
    page_id: str
    title: str


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not value.strip():
        raise SyncError(f"Missing required environment variable: {name}")
    return value.strip()


def normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def course_pattern(title: str) -> re.Pattern[str]:
    match = re.search(r"([A-Za-z]+)\s*([0-9]+)", title)
    if match:
        subject, number = map(re.escape, match.groups())
        return re.compile(subject + r"[A-Z]*" + number, re.IGNORECASE)
    return re.compile(re.escape(normalize(title)), re.IGNORECASE)


def match_course(canvas_course: dict[str, Any], courses: Iterable[CoursePage]) -> CoursePage | None:
    haystack = normalize(
        " ".join(
            str(canvas_course.get(field) or "")
            for field in ("course_code", "name", "original_name")
        )
    )
    matches = [course for course in courses if course_pattern(course.title).search(haystack)]
    return max(matches, key=lambda course: len(normalize(course.title)), default=None)


def assignment_type(assignment: dict[str, Any]) -> str:
    name = str(assignment.get("name") or "").lower()
    submission_types = set(assignment.get("submission_types") or [])
    if "online_quiz" in submission_types or re.search(r"\b(quiz|exam|midterm|final)\b", name):
        return "💭 Exam"
    if "presentation" in name:
        return "🗣️ Presentation"
    if re.search(r"\b(read|reading)\b", name):
        return "📖 Reading"
    return "📝 Homework"


def submitted(assignment: dict[str, Any]) -> bool:
    state = (assignment.get("submission") or {}).get("workflow_state")
    return state in {"submitted", "graded", "pending_review"}


def rich_text(content: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": content[:2000]}}]}


def title(content: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": content[:2000]}}]}


def build_properties(
    canvas_course: dict[str, Any],
    assignment: dict[str, Any],
    notion_course: CoursePage,
    *,
    creating: bool,
) -> dict[str, Any]:
    key = f"{canvas_course['id']}:{assignment['id']}"
    properties: dict[str, Any] = {
        "Agenda Entry": title(str(assignment.get("name") or "Untitled Canvas assignment")),
        "Canvas Key": rich_text(key),
        "Canvas URL": {"url": assignment.get("html_url")},
        "Canvas Updated At": {
            "date": {"start": assignment["updated_at"]} if assignment.get("updated_at") else None
        },
        "Due": {"date": {"start": assignment["due_at"]} if assignment.get("due_at") else None},
        "Course": {"relation": [{"id": notion_course.page_id}]},
        "Course Color": {"select": {"name": notion_course.title}},
        "Type": {"select": {"name": assignment_type(assignment)}},
    }
    if creating or submitted(assignment):
        properties["Done"] = {"checkbox": submitted(assignment)}
    return properties


class JsonClient:
    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8")
                return (json.loads(raw) if raw else None), dict(response.headers.items())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SyncError(f"{method} {url} failed ({exc.code}): {detail[:1000]}") from exc
        except URLError as exc:
            raise SyncError(f"{method} {url} failed: {exc.reason}") from exc


class CanvasClient:
    def __init__(self, http: JsonClient, base_url: str, token: str):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def paginated(self, path: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
        url: str | None = f"{self.base_url}{path}?{urlencode(params)}"
        results: list[dict[str, Any]] = []
        while url:
            body, headers = self.http.request("GET", url, self.headers)
            if not isinstance(body, list):
                raise SyncError(f"Canvas returned an unexpected response for {path}")
            results.extend(body)
            url = next_link(headers.get("Link", ""))
        return results

    def active_courses(self) -> list[dict[str, Any]]:
        return self.paginated(
            "/api/v1/courses",
            [("enrollment_state", "active"), ("state[]", "available"), ("per_page", "100")],
        )

    def assignments(self, course_id: int | str) -> list[dict[str, Any]]:
        return self.paginated(
            f"/api/v1/courses/{course_id}/assignments",
            [("include[]", "submission"), ("order_by", "due_at"), ("per_page", "100")],
        )


def next_link(header: str) -> str | None:
    for part in header.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', part)
        if match and match.group(2) == "next":
            return match.group(1)
    return None


class NotionClient:
    def __init__(self, http: JsonClient, token: str):
        self.http = http
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }

    def query(self, data_source_id: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        request_body = dict(payload or {})
        request_body.setdefault("page_size", 100)
        results: list[dict[str, Any]] = []
        while True:
            body, _ = self.http.request(
                "POST", f"{self.base_url}/data_sources/{data_source_id}/query", self.headers, request_body
            )
            results.extend(body.get("results", []))
            if not body.get("has_more"):
                return results
            request_body["start_cursor"] = body["next_cursor"]

    def course_pages(self, data_source_id: str) -> list[CoursePage]:
        pages = self.query(data_source_id)
        output: list[CoursePage] = []
        for page in pages:
            fragments = page.get("properties", {}).get("Course", {}).get("title", [])
            course_title = "".join(fragment.get("plain_text", "") for fragment in fragments).strip()
            if course_title:
                output.append(CoursePage(page_id=page["id"], title=course_title))
        return output

    def find_assignment(self, data_source_id: str, key: str) -> dict[str, Any] | None:
        pages = self.query(
            data_source_id,
            {"filter": {"property": "Canvas Key", "rich_text": {"equals": key}}, "page_size": 2},
        )
        if len(pages) > 1:
            raise SyncError(f"Duplicate Notion rows found for Canvas Key {key}")
        return pages[0] if pages else None

    def create_assignment(self, data_source_id: str, properties: dict[str, Any]) -> None:
        self.http.request(
            "POST",
            f"{self.base_url}/pages",
            self.headers,
            {"parent": {"type": "data_source_id", "data_source_id": data_source_id}, "properties": properties},
        )

    def update_assignment(self, page_id: str, properties: dict[str, Any]) -> None:
        self.http.request(
            "PATCH", f"{self.base_url}/pages/{page_id}", self.headers, {"properties": properties}
        )


def sync() -> tuple[int, int, int]:
    http = JsonClient()
    canvas = CanvasClient(http, env("CANVAS_BASE_URL"), env("CANVAS_API_TOKEN"))
    notion = NotionClient(http, env("NOTION_API_TOKEN"))
    agenda_id = env("NOTION_AGENDA_DATA_SOURCE_ID")
    courses_id = env("NOTION_COURSES_DATA_SOURCE_ID")
    dry_run = os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}

    notion_courses = notion.course_pages(courses_id)
    if not notion_courses:
        raise SyncError("No courses were readable from the Notion Courses database")

    created = updated = skipped = 0
    for canvas_course in canvas.active_courses():
        notion_course = match_course(canvas_course, notion_courses)
        label = canvas_course.get("course_code") or canvas_course.get("name") or canvas_course.get("id")
        if notion_course is None:
            print(f"Skipping unmatched Canvas course: {label}")
            continue
        print(f"Matched {label} -> {notion_course.title}")
        for assignment in canvas.assignments(canvas_course["id"]):
            if assignment.get("published") is False:
                continue
            key = f"{canvas_course['id']}:{assignment['id']}"
            existing = notion.find_assignment(agenda_id, key)
            properties = build_properties(
                canvas_course, assignment, notion_course, creating=existing is None
            )
            if dry_run:
                print(f"DRY RUN: {'create' if existing is None else 'update'} {key} {assignment.get('name')}")
            elif existing is None:
                notion.create_assignment(agenda_id, properties)
            else:
                notion.update_assignment(existing["id"], properties)
            if existing is None:
                created += 1
            else:
                updated += 1

    print(f"Sync complete: {created} created, {updated} updated, {skipped} skipped")
    return created, updated, skipped


def main() -> int:
    try:
        sync()
        return 0
    except SyncError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
