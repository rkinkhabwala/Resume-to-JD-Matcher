from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from jobfetch.fetcher import JobFetcher, JobFetchError, infer_ats_api
from jobfit.extraction.job import extract_jobposting_jsonld

FIXTURES = Path(__file__).parents[1] / "fixtures" / "jobs"
PUBLIC_IP = "93.184.216.34"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def response(
    request: httpx.Request,
    status_code: int,
    content: bytes = b"",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=content,
        headers=headers,
        request=request,
    )


def public_resolver(_host: str) -> set[str]:
    return {PUBLIC_IP}


def test_jsonld_is_used_before_an_inferred_ats_api() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/robots.txt":
            return response(request, 404)
        return response(request, 200, fixture("jsonld_page.html"))

    fetched = JobFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
    ).fetch("https://boards.greenhouse.io/acme/jobs/1234")

    assert fetched.source == "json_ld"
    assert fetched.title == "Analytics Engineer"
    assert "modern cloud data warehouse" in fetched.text
    assert not any(
        request.url.host == "boards-api.greenhouse.io" for request in requests
    )
    assert all(
        request.headers["user-agent"] == "Mozilla/5.0 (compatible; JobFit/0.1)"
        for request in requests
    )


@pytest.mark.parametrize(
    ("page_url", "page_fixture", "api_host", "api_fixture", "title"),
    [
        (
            "https://boards.greenhouse.io/acme/jobs/1234",
            "greenhouse_page.html",
            "boards-api.greenhouse.io",
            "greenhouse_api.json",
            "Data Engineer",
        ),
        (
            "https://jobs.lever.co/acme/abc123",
            "lever_page.html",
            "api.lever.co",
            "lever_api.json",
            "Product Operations Manager",
        ),
    ],
)
def test_uses_saved_ats_api_payloads(
    page_url: str,
    page_fixture: str,
    api_host: str,
    api_fixture: str,
    title: str,
) -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.path == "/robots.txt":
            return response(request, 404)
        if request.url.host == api_host:
            headers = {"content-type": "application/json"}
            if request.url.host == "boards.greenhouse.io":
                headers["set-cookie"] = "session=must-not-be-reused"
            return response(request, 200, fixture(api_fixture), headers)
        return response(
            request,
            200,
            fixture(page_fixture),
            {"content-type": "text/html"},
        )

    fetched = JobFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
    ).fetch(page_url)

    assert fetched.source == "ats_api"
    assert fetched.title == title
    assert len(fetched.text) >= 200
    assert api_host in requested_hosts


def test_greenhouse_fetch_does_not_reuse_set_cookie() -> None:
    api_request_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return response(request, 404)
        if request.url.host == "boards.greenhouse.io":
            return response(
                request,
                200,
                fixture("greenhouse_page.html"),
                {"set-cookie": "session=private"},
            )
        api_request_headers.append(request.headers)
        return response(request, 200, fixture("greenhouse_api.json"))

    JobFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
    ).fetch("https://boards.greenhouse.io/acme/jobs/1234")

    assert api_request_headers
    assert "cookie" not in api_request_headers[0]


def test_generic_page_uses_trafilatura_fixture() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return response(request, 404)
        return response(
            request,
            200,
            fixture("generic_page.html"),
            {"content-type": "text/html"},
        )

    fetched = JobFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
    ).fetch("https://careers.example.com/jobs/analyst")

    assert fetched.source == "generic_scrape"
    assert fetched.title == "Operations Research Analyst"
    assert "quantitative models" in fetched.text


def test_blocked_http_status_returns_paste_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return response(request, 404)
        return response(request, 403, fixture("blocked_page.html"))

    with pytest.raises(JobFetchError, match="paste the job description") as error:
        JobFetcher(
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        ).fetch("https://www.linkedin.com/jobs/view/123")

    assert error.value.code == "JOB_LINK_BLOCKED"


def test_login_wall_with_success_status_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return response(request, 404)
        return response(request, 200, fixture("blocked_page.html"))

    with pytest.raises(JobFetchError) as error:
        JobFetcher(
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        ).fetch("https://careers.example.com/jobs/hidden")

    assert error.value.code == "JOB_LINK_BLOCKED"


def test_respects_robots_disallow_from_saved_fixture() -> None:
    requested_job = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_job
        if request.url.path == "/robots.txt":
            return response(request, 200, fixture("robots_disallow.txt"))
        requested_job = True
        return response(request, 200, fixture("generic_page.html"))

    with pytest.raises(JobFetchError) as error:
        JobFetcher(
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        ).fetch("https://careers.example.com/private/job")

    assert error.value.code == "ROBOTS_DISALLOWED"
    assert not requested_job


@pytest.mark.parametrize(
    ("url", "resolver"),
    [
        ("http://localhost/job", lambda _host: {"127.0.0.1"}),
        ("http://10.10.20.30/job", public_resolver),
        ("http://169.254.169.254/latest/meta-data", public_resolver),
        ("http://127.0.0.1/job", public_resolver),
    ],
)
def test_blocks_private_ssrf_targets(
    url: str,
    resolver: Callable[[str], set[str]],
) -> None:
    requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return response(request, 200)

    with pytest.raises(JobFetchError) as error:
        JobFetcher(
            resolver=resolver,
            transport=httpx.MockTransport(handler),
        ).fetch(url)

    assert error.value.code == "SSRF_BLOCKED"
    assert not requested


def test_blocks_private_dns_answer_even_if_another_answer_is_public() -> None:
    with pytest.raises(JobFetchError) as error:
        JobFetcher(
            resolver=lambda _host: {PUBLIC_IP, "10.0.0.8"},
            transport=httpx.MockTransport(lambda request: response(request, 200)),
        ).fetch("https://mixed-dns.example/job")

    assert error.value.code == "SSRF_BLOCKED"


def test_blocks_redirect_to_private_ip_before_following_it() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return response(request, 404)
        return response(
            request,
            302,
            headers={"location": "http://10.0.0.4/internal"},
        )

    with pytest.raises(JobFetchError) as error:
        JobFetcher(
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        ).fetch("https://careers.example.com/job")

    assert error.value.code == "SSRF_BLOCKED"
    assert not any("10.0.0.4" in url for url in requested_urls)


def test_rejects_non_http_url_without_requesting_it() -> None:
    with pytest.raises(JobFetchError) as error:
        JobFetcher(
            resolver=public_resolver,
            transport=httpx.MockTransport(lambda request: response(request, 200)),
        ).fetch("file:///etc/passwd")

    assert error.value.code == "INVALID_URL"


def test_caps_download_at_two_megabytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return response(request, 404)
        return response(request, 200, b"x" * (2 * 1024 * 1024 + 1))

    with pytest.raises(JobFetchError) as error:
        JobFetcher(
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        ).fetch("https://careers.example.com/oversized")

    assert error.value.code == "RESPONSE_TOO_LARGE"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://boards.greenhouse.io/acme/jobs/1234?gh_src=campaign",
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs/1234?content=true",
        ),
        (
            "https://jobs.lever.co/acme/abc123",
            "https://api.lever.co/v0/postings/acme/abc123?mode=json",
        ),
        (
            "https://jobs.ashbyhq.com/acme/abc123",
            "https://api.ashbyhq.com/posting-api/job-board/acme/abc123",
        ),
    ],
)
def test_infers_public_ats_api_urls(url: str, expected: str) -> None:
    result = infer_ats_api(url)

    assert result is not None
    assert result[1] == expected


def test_extracts_jsonld_job_posting_fixture() -> None:
    extracted = extract_jobposting_jsonld(fixture("jsonld_page.html").decode())

    assert extracted is not None
    assert extracted.title == "Analytics Engineer"
    assert "cloud data warehouse" in extracted.text
