from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

from jobfit.extraction.job import (
    ExtractedJob,
    JobSource,
    extract_jobposting_jsonld,
    parse_ats_payload,
)

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
MAX_REDIRECTS = 5
MIN_JOB_CHARACTERS = 200
REQUEST_TIMEOUT_SECONDS = 10.0
USER_AGENT = "Mozilla/5.0 (compatible; JobFit/0.1)"
FRIENDLY_BLOCKED_MESSAGE = (
    "Couldn't read this link. Please paste the job description instead."
)

Resolver = Callable[[str], Iterable[str]]
ATSVendor = Literal["greenhouse", "lever", "ashby"]


class JobFetchError(ValueError):
    def __init__(self, code: str, message: str = FRIENDLY_BLOCKED_MESSAGE) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FetchedJob:
    title: str | None
    text: str
    source: JobSource
    url: str


@dataclass(frozen=True)
class _HTTPResult:
    status_code: int
    headers: httpx.Headers
    body: bytes
    text: str
    url: str


def resolve_host(host: str) -> set[str]:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return {record[4][0] for record in records}
    return {str(address)}


def infer_ats_api(url: str) -> tuple[ATSVendor, str] | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        if len(path_parts) >= 3 and path_parts[1] == "jobs":
            board, job_id = path_parts[0], path_parts[2]
            api_url = (
                "https://boards-api.greenhouse.io/v1/boards/"
                f"{quote(board, safe='')}/jobs/{quote(job_id, safe='')}?content=true"
            )
            return "greenhouse", api_url
    elif host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        if len(path_parts) >= 2:
            site, posting_id = path_parts[0], path_parts[1]
            api_host = (
                "api.eu.lever.co" if host == "jobs.eu.lever.co" else "api.lever.co"
            )
            api_url = (
                f"https://{api_host}/v0/postings/{quote(site, safe='')}/"
                f"{quote(posting_id, safe='')}?mode=json"
            )
            return "lever", api_url
    elif host == "jobs.ashbyhq.com" and len(path_parts) >= 2:
        board, posting_id = path_parts[0], path_parts[1]
        api_url = (
            "https://api.ashbyhq.com/posting-api/job-board/"
            f"{quote(board, safe='')}/{quote(posting_id, safe='')}"
        )
        return "ashby", api_url
    return None


class JobFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver = resolve_host,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._resolver = resolver
        self._transport = transport

    def fetch(self, url: str) -> FetchedJob:
        robots_cache: dict[str, RobotFileParser | None] = {}
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
            transport=self._transport,
        ) as client:
            page = self._download(client, url, robots_cache)
            if page.status_code in {403, 429, 999}:
                raise JobFetchError("JOB_LINK_BLOCKED")
            if page.status_code < 200 or page.status_code >= 300:
                raise JobFetchError("JOB_FETCH_FAILED")
            if _looks_blocked(page.text):
                raise JobFetchError("JOB_LINK_BLOCKED")

            jsonld = extract_jobposting_jsonld(page.text)
            if jsonld is not None and _has_enough_text(jsonld.text):
                return _to_fetched_job(jsonld, "json_ld", page.url)

            ats = infer_ats_api(url)
            if ats is not None:
                vendor, api_url = ats
                try:
                    api_response = self._download(client, api_url, robots_cache)
                    if 200 <= api_response.status_code < 300:
                        payload = json.loads(api_response.text)
                        parsed = parse_ats_payload(payload, vendor)
                        if parsed is not None and _has_enough_text(parsed.text):
                            return _to_fetched_job(parsed, "ats_api", page.url)
                except (JobFetchError, json.JSONDecodeError, UnicodeDecodeError):
                    pass

            generic = _extract_generic(page.text)
            if generic is None or not _has_enough_text(generic.text):
                raise JobFetchError("JOB_LINK_BLOCKED")
            return _to_fetched_job(generic, "generic_scrape", page.url)

    def _download(
        self,
        client: httpx.Client,
        url: str,
        robots_cache: dict[str, RobotFileParser | None],
        *,
        check_robots: bool = True,
        max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> _HTTPResult:
        current_url = url
        for redirect_count in range(MAX_REDIRECTS + 1):
            _validate_public_url(current_url, self._resolver)
            if check_robots and not self._robots_allow(
                client, current_url, robots_cache
            ):
                raise JobFetchError("ROBOTS_DISALLOWED")

            try:
                client.cookies.clear()
                with client.stream("GET", current_url) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise JobFetchError("RESPONSE_TOO_LARGE")
                    status_code = response.status_code
                    response_headers = response.headers
                    encoding = response.encoding or "utf-8"
                    response_url = str(response.url)
            except JobFetchError:
                raise
            except httpx.HTTPError as exc:
                raise JobFetchError("JOB_FETCH_FAILED") from exc
            finally:
                client.cookies.clear()

            result = _HTTPResult(
                status_code=status_code,
                headers=response_headers,
                body=bytes(body),
                text=bytes(body).decode(encoding, errors="replace"),
                url=response_url,
            )
            if status_code not in {301, 302, 303, 307, 308}:
                return result
            location = response_headers.get("location")
            if not location or redirect_count == MAX_REDIRECTS:
                raise JobFetchError("JOB_FETCH_FAILED")
            current_url = urljoin(current_url, location)

        raise JobFetchError("JOB_FETCH_FAILED")

    def _robots_allow(
        self,
        client: httpx.Client,
        target_url: str,
        robots_cache: dict[str, RobotFileParser | None],
    ) -> bool:
        parsed = urlsplit(target_url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        if origin not in robots_cache:
            robots_url = f"{origin}/robots.txt"
            try:
                result = self._download(
                    client,
                    robots_url,
                    robots_cache,
                    check_robots=False,
                    max_bytes=MAX_ROBOTS_BYTES,
                )
            except JobFetchError:
                robots_cache[origin] = RobotFileParser()
                return False

            if result.status_code in {404, 410}:
                robots_cache[origin] = None
            elif result.status_code != 200:
                robots_cache[origin] = RobotFileParser()
            else:
                parser = RobotFileParser(robots_url)
                parser.parse(result.text.splitlines())
                robots_cache[origin] = parser

        robot_parser = robots_cache[origin]
        if robot_parser is None:
            return True
        return robot_parser.can_fetch(USER_AGENT, target_url)


def _validate_public_url(url: str, resolver: Resolver):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise JobFetchError("INVALID_URL") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise JobFetchError("INVALID_URL")

    try:
        literal_address = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = set(resolver(host))
        except (OSError, ValueError) as exc:
            raise JobFetchError("JOB_FETCH_FAILED") from exc
    else:
        addresses = {str(literal_address)}
    if not addresses:
        raise JobFetchError("JOB_FETCH_FAILED")
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise JobFetchError("JOB_FETCH_FAILED") from exc
        if (
            isinstance(address, ipaddress.IPv6Address)
            and address.ipv4_mapped is not None
        ):
            address = address.ipv4_mapped
        if not address.is_global:
            raise JobFetchError("SSRF_BLOCKED")
    return parsed


def _extract_generic(html: str) -> ExtractedJob | None:
    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
    )
    if not extracted:
        return None
    metadata = trafilatura.extract_metadata(html)
    title = metadata.title.strip() if metadata and metadata.title else None
    text = "\n".join(part for part in (title, extracted.strip()) if part)
    return ExtractedJob(title=title, text=text)


def _looks_blocked(html: str) -> bool:
    normalized = html.lower()
    return any(
        marker in normalized
        for marker in (
            "sign in to continue",
            "log in to continue",
            "sign in to view",
            "login to view",
            "verify you are human",
            "captcha",
            "access denied",
            "login required",
        )
    )


def _has_enough_text(text: str) -> bool:
    return len(text.strip()) >= MIN_JOB_CHARACTERS


def _to_fetched_job(
    extracted: ExtractedJob,
    source: JobSource,
    url: str,
) -> FetchedJob:
    return FetchedJob(
        title=extracted.title,
        text=extracted.text.strip(),
        source=source,
        url=url,
    )
