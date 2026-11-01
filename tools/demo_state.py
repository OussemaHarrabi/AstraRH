"""Prepare the demo company through the real API, after `astra.py seed`.

Every step goes through the same agents and approvals a person would use: it ranks the seeded job,
adds a second job from the CV corpus, approves a shortlist and books interviews.
Run with: python tools/demo_state.py. It costs a few cents in model calls.
"""

import http.cookiejar
import json
import mimetypes
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path(__file__).resolve().parents[1]
PASSWORD = next(
    line.split("=", 1)[1].strip().strip('"')
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    if line.startswith("DEMO_PASSWORD=")
)
BASE = "http://127.0.0.1:8080/api"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
CLEAN_OFFERS = "--withdraw-offers" in sys.argv


def call(path, body=None, files=None):
    headers = {}
    data = None
    for cookie in jar:
        if cookie.name == "astra_csrf":
            headers["x-csrf-token"] = cookie.value
    if files:
        boundary = uuid.uuid4().hex
        parts = []
        for path_on_disk in files:
            kind = mimetypes.guess_type(path_on_disk.name)[0] or "application/octet-stream"
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
                f'filename="{path_on_disk.name}"\r\nContent-Type: {kind}\r\n\r\n'.encode()
                + path_on_disk.read_bytes()
                + b"\r\n"
            )
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["content-type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with opener.open(request, timeout=120) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{path}: {error.code} {error.read()[:300].decode('utf-8', 'replace')}") from error


def login(email):
    jar.clear()
    call("/auth/login", {"tenant": "cds", "email": email, "password": PASSWORD})


def wait(check, label, seconds=420):
    for _ in range(seconds // 4):
        value = check()
        if value:
            return value
        time.sleep(4)
    raise SystemExit(f"Timed out waiting for {label}")


def rank(job_id):
    if call(f"/packs/talent/jobs/{job_id}/shortlist")["candidates"]:
        return
    call(f"/packs/talent/jobs/{job_id}/rankings", {})
    wait(
        lambda: (call(f"/packs/talent/jobs/{job_id}/shortlist")["ranking"] or {}).get("status") == "completed",
        "ranking",
    )


def corpus_job():
    """A second job, read from data/jobs and ranked against the applicants in the corpus."""
    jobs = call("/packs/talent/jobs")
    job = next((row for row in jobs if row["title"] == "Security Analyst"), None)
    if job is None:
        text = (ROOT / "data/jobs/J01_Security_Analyst.md").read_text(encoding="utf-8")
        description = text.split("## About the role", 1)[-1].strip()
        job = call("/packs/talent/jobs", {"title": "Security Analyst", "description": description, "org_unit": "ORG-ENG"})
        print("Job created: Security Analyst")
    job_id = job["id"]
    detail = wait(lambda: (lambda row: row if row["rubrics"] else None)(call(f"/packs/talent/jobs/{job_id}")), "criteria")
    if not detail["active_rubric_id"]:
        call(f"/packs/talent/jobs/{job_id}/rubrics/{detail['rubrics'][0]['id']}/activate", {})
    # Everyone in the corpus applies, so the ranking has to separate real fits from the rest.
    have = {cv["filename"] for cv in call(f"/packs/talent/jobs/{job_id}/cvs")}
    pdfs = [path for path in sorted((ROOT / "data/cvs/pdf").glob("CV*")) if path.name not in have]
    if pdfs:
        result = call(f"/packs/talent/jobs/{job_id}/cvs", files=pdfs)
        print(f"Uploaded {len(result['accepted'])} CVs for Security Analyst")
    wait(lambda: all(cv["status"] != "uploaded" for cv in call(f"/packs/talent/jobs/{job_id}/cvs")), "CV reading", 900)
    shortlist = call(f"/packs/talent/jobs/{job_id}/shortlist")["candidates"]
    if len(shortlist) < len(call(f"/packs/talent/jobs/{job_id}/cvs")):
        call(f"/packs/talent/jobs/{job_id}/rankings", {})
        wait(
            lambda: (call(f"/packs/talent/jobs/{job_id}/shortlist")["ranking"] or {}).get("status") == "completed",
            "ranking",
            900,
        )
    return job_id


def approve(action, match=lambda proposal: True, limit=1):
    done = 0
    for proposal in call("/trust/proposals?status=pending_approval&limit=100"):
        if proposal["action_type"] == action and match(proposal) and done < limit:
            call(f"/trust/proposals/{proposal['id']}/approve", {})
            print("Approved:", proposal["summary"])
            done += 1
    return done


def book_interviews(job_id, how_many):
    candidates = call(f"/packs/talent/jobs/{job_id}/shortlist")["candidates"]
    approve("talent.shortlist.confirm", lambda proposal: proposal["payload"].get("job_id") == job_id)
    wait(
        lambda: any(row["stage"] == "shortlisted" for row in call(f"/packs/talent/jobs/{job_id}/shortlist")["candidates"]),
        "shortlist",
    )
    # An earlier run may have left clashing offers: withdraw them through the normal approval.
    for row in call(f"/packs/talent/jobs/{job_id}/interviews"):
        if row["status"] == "slots_proposed" and CLEAN_OFFERS:
            call(f"/packs/talent/interviews/{row['id']}/cancel", {"reason": "Offer withdrawn", "reschedule": False})
    while approve("talent.interview.cancel", limit=10):
        time.sleep(4)
    wait(
        lambda: all(row["status"] != "slots_proposed" for row in call(f"/packs/talent/jobs/{job_id}/interviews")) or not CLEAN_OFFERS,
        "offers withdrawn",
    )
    known = {
        row["application_id"]: row
        for row in call(f"/packs/talent/jobs/{job_id}/interviews")
        if row["status"] != "cancelled"
    }
    for candidate in candidates[:how_many]:
        application = candidate["application_id"]
        if application not in known:
            call(f"/packs/talent/applications/{application}/interviews", {"interviewer_email": "karim@cds.example.test"})
    for index, candidate in enumerate(candidates[:how_many]):
        application = candidate["application_id"]
        def latest():
            rows = [row for row in call(f"/packs/talent/jobs/{job_id}/interviews") if row["application_id"] == application]
            newest = max(rows, key=lambda row: row["created_at"])
            return None if newest["status"] == "requested" else newest

        interview = wait(latest, "interview times")
        # The last one stays at three held times, so the demo can show that state.
        if interview["status"] != "slots_proposed" or index == how_many - 1:
            continue
        call(f"/packs/talent/interviews/{interview['id']}/book", interview["slots"][index % len(interview["slots"])])
        approve("talent.interview.book")
        wait(
            lambda: any(
                row["id"] == interview["id"] and row["status"] == "booked"
                for row in call(f"/packs/talent/jobs/{job_id}/interviews")
            ),
            "booking",
        )
        print("Booked:", candidate["name"])


def main():
    login("nadia@cds.example.test")
    jobs = call("/packs/talent/jobs")
    rank(jobs[0]["id"])
    book_interviews(jobs[0]["id"], 3)
    corpus_job()
    call("/comms/digest", {})
    for job in call("/packs/talent/jobs"):
        print(job["title"], job["cv_counts"], len(call(f"/packs/talent/jobs/{job['id']}/shortlist")["candidates"]), "ranked")


if __name__ == "__main__":
    main()
