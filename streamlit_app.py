import json
import os
import time
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.getenv("JOBFIT_API_BASE_URL", "http://localhost:8000").rstrip("/")


def api_get(path: str) -> dict[str, Any]:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=30)
    if response.status_code >= 400:
        payload = response.json() if response.content else {}
        raise RuntimeError(payload.get("detail", payload.get("message", response.text)))
    return response.json()


def api_post(
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE_URL}{path}",
        json=json_body,
        files=files,
        data=data,
        timeout=60,
    )
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        raise RuntimeError(
            payload.get(
                "detail",
                payload.get("message", payload.get("title", response.text)),
            )
        )
    return payload


def render_verdict_color(value: str) -> str:
    palette = {
        "met": "#2ecc71",
        "partial": "#f1c40f",
        "missing": "#e74c3c",
        "unrelated": "#95a5a6",
    }
    return palette.get(value, "#7f8c8d")


st.set_page_config(page_title="JobFit", page_icon="✅", layout="wide")

st.title("JobFit Match Assistant")
st.caption(
    "Upload a resume, fetch or paste a job description, and review the "
    "evidence-backed match."
)

if "job_text" not in st.session_state:
    st.session_state.job_text = ""
if "last_result" not in st.session_state:
    st.session_state.last_result = None

with st.sidebar:
    st.markdown("### Workflow")
    st.markdown("1. Upload your resume")
    st.markdown("2. Fetch a link or paste the description")
    st.markdown("3. Review the editable JD and analyze")
    st.markdown("4. Download the JSON report")
    st.caption(f"API endpoint: {API_BASE_URL}")

resume_file = st.file_uploader(
    "Upload resume",
    type=["pdf", "docx", "txt"],
    help="PDF, DOCX, or TXT resumes are supported.",
)

job_mode = st.tabs(["Link", "Paste"])

with job_mode[0]:
    job_url = st.text_input("Job link", value="", placeholder="https://example.com/job")
    if st.button("Fetch job preview"):
        if not job_url:
            st.warning("Enter a job URL before fetching the preview.")
        else:
            try:
                payload = api_post("/api/v1/extract-job", json_body={"url": job_url})
                st.session_state.job_text = payload.get("text", "")
                st.success(f"Fetched from {payload.get('source', 'job link')}.")
                if payload.get("title"):
                    st.caption(f"Detected title: {payload['title']}")
            except RuntimeError as exc:
                st.error(str(exc))

with job_mode[1]:
    st.session_state.job_text = st.text_area(
        "Paste the job description",
        value=st.session_state.job_text,
        height=220,
        help=("Paste the full job description to compare against your resume."),
    )

job_text = st.session_state.job_text.strip()
if job_text:
    st.subheader("Editable job preview")
    job_text = st.text_area(
        "Job description to analyze",
        value=job_text,
        height=220,
        key="editable_job_text",
    )
    st.session_state.job_text = job_text
else:
    job_text = st.text_area(
        "Job description to analyze",
        value="",
        height=220,
        key="editable_job_text",
    )
    st.session_state.job_text = job_text

analyze_clicked = st.button(
    "Analyze match",
    type="primary",
    disabled=not bool(resume_file) or not bool(job_text),
)

if analyze_clicked:
    if not resume_file:
        st.warning("Upload a resume before running the analysis.")
    elif not job_text.strip():
        st.warning("Paste or fetch a job description before running the analysis.")
    else:
        with st.spinner("Submitting your resume and job description..."):
            try:
                response = api_post(
                    "/api/v1/analyses",
                    files={
                        "resume_file": (
                            resume_file.name,
                            resume_file.getvalue(),
                            resume_file.type or "application/octet-stream",
                        )
                    },
                    data={"job_text": job_text},
                )
                analysis_id = response["analysis_id"]
                status_url = response["status_url"]
            except RuntimeError as exc:
                st.error(str(exc))
                st.stop()

        progress = st.empty()
        status = "queued"
        while True:
            try:
                status_payload = api_get(status_url)
            except RuntimeError as exc:
                st.error(f"Polling failed: {exc}")
                break

            status = status_payload.get("status", "queued")
            progress.info(
                f"Status: {status} — {status_payload.get('message', 'Processing...')}"
            )
            if status in {"completed", "failed"}:
                break
            time.sleep(1.5)

        if status == "completed":
            result = status_payload.get("result")
            st.session_state.last_result = result
            if not result:
                st.error("The analysis completed without a result payload.")
                st.stop()

            score = int(result.get("score", 0))
            confidence = result.get("confidence", {})
            label = confidence.get("label", "Low")
            reasons = confidence.get("reasons", [])

            st.subheader("Results")
            st.metric("Match score", f"{score}/100")
            st.badge(
                label,
                icon=("✅" if label == "High" else "⚠️" if label == "Medium" else "❌"),
            )
            if reasons:
                st.write("Confidence reasons:")
                for reason in reasons:
                    st.caption(f"• {reason}")

            summary = result.get("summary", "")
            if summary:
                st.write(summary)

            cols = st.columns(3)
            cols[0].metric(
                "Keyword coverage",
                f"{float(result.get('keyword_coverage', 0)) * 100:.0f}%",
            )
            cols[1].metric("Model", result.get("model", "n/a"))
            cols[2].metric("Prompt version", result.get("prompt_version", "n/a"))

            requirements = result.get("requirements", [])
            if requirements:
                st.subheader("Requirement checklist")
                rows = []
                for item in requirements:
                    rows.append(
                        {
                            "Requirement": item.get("text", ""),
                            "Importance": item.get("importance", "medium"),
                            "Verdict": item.get("verdict", "missing"),
                            "Evidence": " | ".join(item.get("evidence", [])[:2]),
                        }
                    )
                table = st.dataframe(
                    rows,
                    column_config={
                        "Requirement": st.column_config.TextColumn(width="large"),
                        "Verdict": st.column_config.TextColumn(),
                        "Importance": st.column_config.TextColumn(),
                        "Evidence": st.column_config.TextColumn(width="large"),
                    },
                    use_container_width=True,
                )
                if table is not None:
                    st.caption(
                        "Color coding: green = met, yellow = partial, red = missing."
                    )

            strengths = result.get("strengths", [])
            gaps = result.get("gaps", [])
            suggestions = result.get("resume_suggestions", [])

            if strengths or gaps or suggestions:
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.subheader("Strengths")
                    for item in strengths or ["No clear strengths found."]:
                        st.write(f"• {item}")
                with col_b:
                    st.subheader("Gaps")
                    for item in gaps or ["No gaps identified."]:
                        st.write(f"• {item}")
                with col_c:
                    st.subheader("Suggestions")
                    for item in suggestions or ["No suggestions generated."]:
                        st.write(f"• {item}")

            st.download_button(
                "Download JSON report",
                data=json.dumps(result, indent=2, ensure_ascii=False),
                file_name="jobfit_report.json",
                mime="application/json",
            )
        elif status == "failed":
            st.error(
                "The analysis failed. Please verify the resume file and job "
                "description and try again."
            )
            if status_payload.get("result"):
                st.write(status_payload["result"])

if st.session_state.last_result:
    st.caption("Last successful analysis is available in session memory.")
