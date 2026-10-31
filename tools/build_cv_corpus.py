"""Build a 30-CV tech corpus from the CC0 LiveCareer resume dataset.

Source: https://huggingface.co/datasets/opensporks/resumes
Original: https://www.kaggle.com/datasets/snehaanbhawal/resume-dataset (CC0-1.0)
The source text is scraped resume *examples*; this script replaces PII,
company placeholders, locations and identities, then renders the same
content as PDF, DOCX, HTML, Markdown, TXT and JSON.
"""

from __future__ import annotations

import csv
import html
import json
import os
import re
import shutil
import textwrap
import unicodedata
from datetime import date
from pathlib import Path

from PIL import Image
import fitz  # PyMuPDF, used only to rasterise the two scanned samples
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Frame, HRFlowable, KeepTogether, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "source" / "Resume.csv"
OUT = ROOT / "data" / "cvs"
JOBS_OUT = ROOT / "data" / "jobs"

NAVY = colors.HexColor("#1F3A5F")
ACCENT = colors.HexColor("#2E6E8E")
MUTED = colors.HexColor("#5B6770")
LIGHT = colors.HexColor("#E8EEF3")
RULE = colors.HexColor("#C9D6E2")

# ---------------------------------------------------------------------------
# Identities: fictional names, demo contacts, no real PII
# ---------------------------------------------------------------------------

IDENTITIES = [
    ("Aïcha Benali", "Paris, France", ["French (native)", "English (C1)", "Arabic (conversational)"]),
    ("Lucas Moreau", "Lyon, France", ["French (native)", "English (C1)"]),
    ("Sofia Rossi", "Milan, Italy", ["Italian (native)", "English (B2)"]),
    ("Youssef El Amrani", "Paris, France", ["Arabic (native)", "French (C1)", "English (C1)"]),
    ("Priya Nair", "Berlin, Germany", ["English (native)", "German (B1)", "Malayalam (native)"]),
    ("Daniel Okafor", "London, United Kingdom", ["English (native)", "Igbo (native)"]),
    ("Mei Lin", "Singapore", ["English (C2)", "Mandarin (native)"]),
    ("Karim Haddad", "Dubai, United Arab Emirates", ["Arabic (native)", "English (C1)", "French (B1)"]),
    ("Elena Petrova", "Warsaw, Poland", ["Russian (native)", "English (C1)", "Polish (B1)"]),
    ("Tomás Silva", "Lisbon, Portugal", ["Portuguese (native)", "English (C1)", "Spanish (B2)"]),
    ("Hana Suzuki", "Tokyo, Japan", ["Japanese (native)", "English (C1)"]),
    ("Omar Farouk", "Munich, Germany", ["Arabic (native)", "English (C1)", "German (B2)"]),
    ("Camille Dubois", "Montreal, Canada", ["French (native)", "English (C1)"]),
    ("Arjun Mehta", "Bangalore, India", ["English (C2)", "Hindi (native)", "Kannada (conversational)"]),
    ("Fatima Zahra", "Casablanca, Morocco", ["Arabic (native)", "French (C1)", "English (C1)"]),
    ("Noah Williams", "Austin, United States", ["English (native)", "Spanish (B1)"]),
    ("Chiara Bianchi", "Rome, Italy", ["Italian (native)", "English (C1)"]),
    ("Viktor Novak", "Prague, Czech Republic", ["Czech (native)", "English (C1)", "German (B1)"]),
    ("Leila Mansour", "Paris, France", ["Arabic (native)", "French (native)", "English (C1)"]),
    ("Samuel Adeyemi", "Lagos, Nigeria", ["English (native)", "Yoruba (native)"]),
    ("Inès Lemaire", "Grenoble, France", ["French (native)", "English (C1)"]),
    ("Ravi Patel", "London, United Kingdom", ["English (native)", "Gujarati (native)", "Hindi (C1)"]),
    ("Anna Kowalska", "Krakow, Poland", ["Polish (native)", "English (C1)"]),
    ("Mohamed Ali", "Tunis, Tunisia", ["Arabic (native)", "French (C1)", "English (B2)"]),
    ("Julia Schneider", "Zurich, Switzerland", ["German (native)", "English (C2)", "French (B1)"]),
    ("Kenji Watanabe", "Osaka, Japan", ["Japanese (native)", "English (B2)"]),
    ("Laura García", "Madrid, Spain", ["Spanish (native)", "English (C1)"]),
    ("David Cohen", "Tel Aviv, Israel", ["Hebrew (native)", "English (C2)"]),
    ("Amina Diallo", "Dakar, Senegal", ["French (native)", "English (B2)", "Wolof (native)"]),
    ("Erik Johansson", "Stockholm, Sweden", ["Swedish (native)", "English (C2)", "German (B1)"]),
]

SELECTED = [
    # source_id, title, field, layout, formats, job
    ("36856210", "Information Security Analyst", "security", "classic", "pdf,docx,html,md,txt,json", "J01"),
    ("18187364", "Information Security Officer", "security", "modern", "pdf,docx,html,md,txt,json", "J01"),
    ("19796840", "IT Auditor", "security", "table", "pdf,docx,html,md,txt,json", "J01"),
    ("27058381", "Systems Administrator", "sysadmin", "classic", "pdf,html,txt,json", "J02"),
    ("63158213", "Senior Network Engineer", "network", "modern", "pdf,docx,html,md,txt,json", "J02"),
    ("57706851", "NOC Engineer", "network", "compact", "pdf,docx,html,md,txt,json", "J02"),
    ("20824105", "Cloud Administrator", "cloud", "classic", "pdf,docx,html,md,txt,json", "J02"),
    ("16186411", ".NET Developer", "backend", "classic", "pdf,docx,html,md,txt,json", "J03"),
    ("12763627", "ASP.NET Web Developer", "backend", "modern", "pdf,docx,html,md,txt,json", "J03"),
    ("20674668", "Drupal Developer", "backend", "compact", "pdf,html,txt,json", "J03"),
    ("43311839", "Software Engineer", "backend", "table", "pdf,docx,html,md,txt,json", "J12"),
    ("51588273", "Engineering Manager", "management", "modern", "pdf,docx,html,md,txt,json", "J08"),
    ("22605864", "Software Engineering Team Lead", "management", "classic", "pdf,docx,html,md,txt,json", "J08"),
    ("12472574", "QA Engineering Team Lead", "qa", "modern", "pdf,docx,html,md,txt,json", "J05"),
    ("83816738", "Test Automation Engineer", "qa", "compact", "pdf,docx,html,md,txt,json", "J05"),
    ("41152404", "QA Test Analyst", "qa", "classic", "pdf,docx,html,md,txt,json", "J05"),
    ("29051656", "Database Administrator", "dba", "table", "pdf,docx,html,md,txt,json", "J06"),
    ("26746496", "Database Programmer", "dba", "classic", "pdf,html,txt,json", "J06"),
    ("15145575", "IT Support Officer", "support", "classic", "pdf,docx,html,md,txt,json", "J07"),
    ("52618188", "IT Help Desk Specialist", "support", "compact", "pdf,docx,html,md,txt,json", "J07"),
    ("40018190", "IT Support Technician", "support", "modern", "pdf,docx,html,md,txt,json", "J07"),
    ("37664296", "Lead UX/UI Designer", "design", "modern", "pdf,docx,html,md,txt,json", "J04"),
    ("34317538", "Lead Interaction Designer", "design", "classic", "pdf,docx,html,md,txt,json", "J04"),
    ("94417768", "Senior Product Designer", "design", "compact", "pdf,docx,html,md,txt,json", "J04"),
    ("25949631", "Web Designer", "design", "table", "pdf,html,txt,json", "J04"),
    ("32985311", "Software Engineering Analyst", "analyst", "classic", "pdf,docx,html,md,txt,json", "J12"),
    ("10265057", "RF Systems Engineer", "embedded", "modern", "pdf,docx,html,md,txt,json", "J10"),
    ("24647794", "Electrical Engineer", "embedded", "classic", "pdf,html,txt,json", "J10"),
    ("93349646", "DevOps / Infrastructure Consultant", "devops", "modern", "pdf,docx,html,md,txt,json", "J09"),
    ("27080812", "Data & Marketing Technology Lead", "data", "classic", "pdf,docx,html,md,txt,json", "J11"),
]

JOBS = [
    dict(id="J01", title="Security Analyst", company="Umbra Shield", location="Dubai, UAE", mode="On-site", level="Mid", years=3,
         must=["SIEM", "incident response", "MITRE ATT&CK", "EDR", "security operations"],
         nice=["Python", "Splunk", "ISO 27001", "threat hunting", "phishing response"],
         summary="Monitor, triage and contain security incidents across cloud and endpoint telemetry. Write detections that survive real traffic."),
    dict(id="J02", title="Network / Cloud Engineer", company="Zephyr Mesh", location="Remote (EU)", mode="Remote", level="Senior", years=5,
         must=["network design", "BGP", "firewalls", "AWS or Azure", "automation"],
         nice=["Cisco", "Terraform", "Kubernetes", "observability", "CCNP"],
         summary="Own a hybrid network and cloud estate: routing, segmentation, connectivity and the automation that keeps it reproducible."),
    dict(id="J03", title=".NET / Web Developer", company="Helios Forge", location="Lyon, France", mode="Hybrid", level="Mid", years=3,
         must=["C#", "ASP.NET", "SQL Server", "JavaScript", "REST APIs"],
         nice=["Azure", "Entity Framework", "React", "CI/CD", "testing"],
         summary="Build and maintain business-critical web applications in .NET, with a focus on clean APIs and reliable releases."),
    dict(id="J04", title="UX/UI Designer", company="Northwind Atlas", location="Paris, France", mode="Remote-friendly", level="Senior", years=4,
         must=["Figma", "design systems", "usability research", "prototyping", "accessibility"],
         nice=["HTML/CSS", "mobile design", "workshop facilitation", "analytics"],
         summary="Design complex B2B workflows end to end: research, prototypes, design-system components and accessible shipped UI."),
    dict(id="J05", title="QA Automation Engineer", company="Lantern Retail", location="Remote (EU)", mode="Remote", level="Senior", years=4,
         must=["Playwright or Selenium", "test automation", "API testing", "CI/CD", "test design"],
         nice=["TypeScript", "performance testing", "accessibility", "contract testing"],
         summary="Build automation that shortens release qualification and catches the regressions that matter."),
    dict(id="J06", title="Database Administrator", company="Quartz River", location="London, UK", mode="Hybrid", level="Senior", years=6,
         must=["PostgreSQL or SQL Server", "performance tuning", "backup/recovery", "replication", "SQL"],
         nice=["Oracle", "partitioning", "Ansible", "cloud databases", "observability"],
         summary="Keep production databases fast, available and recoverable. Own tuning, migrations and the runbooks."),
    dict(id="J07", title="IT Support Officer", company="Willow Health", location="Tunis, Tunisia", mode="On-site", level="Junior", years=2,
         must=["Windows", "Microsoft 365", "Active Directory", "ticketing", "networking"],
         nice=["macOS", "Linux", "Intune", "ITIL", "asset management"],
         summary="Support employees across devices, identity and SaaS. Write the knowledge-base article after fixing the issue."),
    dict(id="J08", title="Engineering Manager", company="Glacier Cloud", location="Berlin, Germany", mode="Hybrid", level="Manager", years=8,
         must=["people management", "delivery", "backend or platform", "hiring", "incident management"],
         nice=["distributed systems", "OKRs", "coaching", "architecture"],
         summary="Lead a backend/platform team: hiring, growth, delivery predictability and a healthy on-call culture."),
    dict(id="J09", title="DevOps Engineer", company="Glacier Cloud", location="Remote (EU)", mode="Remote", level="Senior", years=5,
         must=["AWS", "Terraform", "Kubernetes", "CI/CD", "observability"],
         nice=["Go", "Argo CD", "Prometheus", "security", "cost optimisation"],
         summary="Build golden paths and reliable infrastructure for a multi-tenant SaaS platform."),
    dict(id="J10", title="Embedded / RF Engineer", company="Xenon Motion", location="Munich, Germany", mode="On-site", level="Senior", years=5,
         must=["C/C++", "embedded systems", "RF or electronics", "debugging", "testing"],
         nice=["RTOS", "ARM", "PCB", "MATLAB", "safety"],
         summary="Develop and debug embedded/RF systems from prototype to production, with rigorous test and documentation habits."),
    dict(id="J11", title="Data Analyst", company="Mosaic Ridge", location="Dakar, Senegal", mode="Remote-friendly", level="Junior", years=2,
         must=["SQL", "dashboards", "statistics", "stakeholder communication"],
         nice=["Power BI", "Python", "experimentation", "data quality"],
         summary="Turn operational data into decisions: dashboards, analyses and clear recommendations."),
    dict(id="J12", title="Software Engineer", company="Helios Forge", location="Paris, France", mode="Hybrid", level="Senior", years=5,
         must=["software design", "SQL", "APIs", "testing", "code review"],
         nice=["Python", "C#", "cloud", "observability", "mentoring"],
         summary="Design and ship maintainable services and internal tools, with strong review and testing habits."),
]

DEGREES = {
    "security": ("BSc Cybersecurity", "Atlas Polytechnic", 2018),
    "sysadmin": ("BSc Information Technology", "Northvale University", 2017),
    "network": ("BSc Network Engineering", "Meridia Institute of Technology", 2016),
    "cloud": ("BSc Cloud Computing", "Lakeside University", 2019),
    "backend": ("BSc Software Engineering", "Northvale University", 2017),
    "management": ("MSc Software Engineering", "Cedar Valley University", 2012),
    "qa": ("BSc Information Systems", "Meridia Institute of Technology", 2016),
    "dba": ("MSc Database Systems", "Atlas Polytechnic", 2013),
    "support": ("BSc Information Technology", "Lakeside University", 2020),
    "design": ("BA Interaction Design", "Cedar Valley University", 2016),
    "analyst": ("MSc Computer Science", "Northvale University", 2015),
    "embedded": ("MSc Electrical Engineering", "Meridia Institute of Technology", 2014),
    "devops": ("BSc Computer Engineering", "Atlas Polytechnic", 2015),
    "data": ("MSc Data Science", "Cedar Valley University", 2018),
}

FIELD_SKILLS = {
    "security": ["SIEM", "Incident Response", "MITRE ATT&CK", "EDR", "Vulnerability Management", "Python", "Splunk", "ISO 27001"],
    "sysadmin": ["Windows Server", "Active Directory", "Microsoft 365", "PowerShell", "VMware", "Backup", "Networking", "Linux"],
    "network": ["BGP", "OSPF", "Cisco", "Firewalls", "MPLS", "VPN", "Wireshark", "Network Automation"],
    "cloud": ["AWS", "Azure", "Terraform", "Kubernetes", "Linux", "CI/CD", "Monitoring", "IAM"],
    "backend": ["C#", "ASP.NET", "SQL Server", "REST APIs", "JavaScript", "Entity Framework", "Azure", "Git"],
    "management": ["Team Leadership", "Hiring", "Delivery", "Architecture", "Incident Management", "OKRs", "Coaching", "Stakeholders"],
    "qa": ["Test Automation", "Selenium", "Playwright", "API Testing", "CI/CD", "Test Design", "Jira", "Agile"],
    "dba": ["PostgreSQL", "SQL Server", "Oracle", "Performance Tuning", "Backup/Recovery", "Replication", "SQL", "Linux"],
    "support": ["Windows", "Microsoft 365", "Active Directory", "Ticketing", "Networking", "Hardware", "Customer Service", "ITIL"],
    "design": ["Figma", "Design Systems", "Usability Research", "Prototyping", "Accessibility", "HTML/CSS", "Adobe CC", "Wireframing"],
    "analyst": ["SQL", "Python", "Data Analysis", "Reporting", "APIs", "Testing", "Agile", "Documentation"],
    "embedded": ["C", "C++", "Embedded Systems", "RF", "Electronics", "Debugging", "MATLAB", "Testing"],
    "devops": ["AWS", "Terraform", "Kubernetes", "CI/CD", "Linux", "Ansible", "Prometheus", "Docker"],
    "data": ["SQL", "Python", "Tableau", "Power BI", "Analytics", "Data Quality", "ETL", "Stakeholders"],
}

CERT_FALLBACK = {
    "security": ["CompTIA Security+", "CISSP (in progress)"],
    "network": ["CCNP Enterprise", "CompTIA Network+"],
    "cloud": ["AWS Solutions Architect — Associate", "Azure Administrator"],
    "backend": ["Microsoft Certified: Azure Developer Associate"],
    "management": ["Certified ScrumMaster"],
    "qa": ["ISTQB Certified Tester"],
    "dba": ["PostgreSQL Associate", "Oracle Certified Professional"],
    "support": ["CompTIA A+", "Microsoft 365 Fundamentals"],
    "design": ["Nielsen Norman Group UX Certification"],
    "embedded": ["Certified Electronics Technician"],
    "devops": ["CKA", "AWS Solutions Architect — Associate"],
    "data": ["Google Data Analytics"],
}

HEADINGS = [
    "PROFESSIONAL SUMMARY", "Professional Summary", "EXECUTIVE PROFILE", "Executive Profile",
    "CAREER OVERVIEW", "Career Overview", "CAREER FOCUS", "Career Focus",
    "CORE QUALIFICATIONS", "Core Qualifications", "SKILL HIGHLIGHTS", "Skill Highlights",
    "PROFESSIONAL PROFILE", "Professional Profile", "WORK HISTORY", "Work History",
    "PROFESSIONAL EXPERIENCE", "Professional Experience", "WORK EXPERIENCE", "Work Experience",
    "ACCOMPLISHMENTS", "Accomplishments", "CERTIFICATIONS", "Certifications",
    "SUMMARY", "Summary", "PROFILE", "Profile", "OBJECTIVE", "Objective",
    "HIGHLIGHTS", "Highlights", "SKILLS", "Skills", "EXPERIENCE", "Experience",
    "EDUCATION", "Education", "LANGUAGES", "Languages", "REFERENCES", "References",
]
HEAD_RE = re.compile(r"\b(" + "|".join(re.escape(h) for h in HEADINGS) + r")\b")


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_")


def clean_text(s: str) -> str:
    s = s.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def sanitize(text: str, ident: dict) -> str:
    text = text.replace("Company Name", ident["company"])
    text = text.replace("－", "-").replace("–", "-").replace("—", "-")
    for real, fake in [
        ("Encore capital Group", "Northwind Atlas"),
        ("Encore Capital Group", "Northwind Atlas"),
        ("Avanade", "Helios Forge"),
        ("Diligent", "Cobalt Harbor"),
        ("Sprint", "Zephyr Mesh"),
        ("CYIENT", "Orchid Byte"),
        ("SKSIT", "Cobalt Harbor"),
        ("Thapar University", "Meridia Institute of Technology"),
        ("University of Missouri", "Northvale University"),
    ]:
        text = text.replace(real, fake)
    text = re.sub(r"City\s*,\s*State", ident["location"], text)
    text = re.sub(r"Your City, State, Zip Code", ident["location"], text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", ident["email"], text)
    text = re.sub(r"https?://\S+|www\.\S+", ident["portfolio"], text)
    text = re.sub(r"\+?\d[\d\s().-]{7,}\d", ident["phone"], text)
    text = re.sub(r"(?i)\b(?:secret|top secret|ts/sci|public trust)\s+(?:security\s+)?clearance\b", "", text)
    text = re.sub(r"(?i)\b(?:u\.?s\.?\s+)?(?:army|navy|air force|marine corps|military)\b", "a multinational organisation", text)
    text = re.sub(r"(?i)\b(?:date of birth|dob|marital status|religion|nationality|age)\b\s*[:\-]?\s*[^\n]{0,80}", "", text)
    text = re.split(r"(?i)\bREFERENCES\b", text)[0]
    text = re.sub(r"(?im)^\s*(?:name|candidate)\s*:\s*.+$", "", text)
    text = re.sub(r"(?i)my name is [^.]{0,80}\.", "", text)
    text = re.sub(r"(?im)^\s*(?:permanent\s+)?address\s*[:\-].*$", "", text)
    text = re.sub(r"(?i)\b(?:permanent\s+address|current\s+address|correspondence\s+address|contact\s+address)\b\s*[:\-]?\s*[^\n]{0,180}", "", text)
    text = re.sub(r"(?i)\bH\s*No\.?\s*\d+[^\n]{0,120}", "", text)
    text = re.sub(r"(?i)\b(?:pin|zip)\s*[:\-]?\s*\d{5,6}\b", "", text)
    text = re.sub(r"(?i)\bnew\s+delhi\s*-\s*\d{6}\b", "", text)
    text = re.sub(r"(?i)\bblah,\s*blah\b", "", text)
    text = re.sub(r"(?i)\bname\s+[A-Z][A-Za-z.]+\s+[A-Z][A-Za-z.]+\b", "", text)
    text = re.sub(r"(?i)\b(?:permanent residency|resident of|citizen of)\b[^.]{0,80}\.", "", text)
    text = re.sub(r"(?i)\b(?:interests|hobbies|recreational activities)\b\s*[:\-]?\s*[^\n]{0,120}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sections(text: str) -> dict[str, str]:
    matches = list(HEAD_RE.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = m.group(1).upper()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        val = clean_text(text[m.end():end])
        if val and key not in out:
            out[key] = val
    return out


def first_section(sec: dict[str, str], keys: list[str]) -> str:
    for k in keys:
        if k in sec and sec[k].strip():
            return sec[k]
    return ""


def extract_summary(text: str, sec: dict[str, str]) -> str:
    raw = first_section(sec, ["PROFESSIONAL SUMMARY", "EXECUTIVE PROFILE", "CAREER OVERVIEW", "CAREER FOCUS", "PROFESSIONAL PROFILE", "SUMMARY", "PROFILE", "OBJECTIVE"])
    if not raw:
        raw = text
    raw = re.sub(r"\s+", " ", raw)
    # Take the first 2-3 sentences, capped
    parts = re.split(r"(?<=[.!?])\s+", raw)
    out = " ".join(parts[:3]).strip()
    if len(out) > 440:
        out = out[:437].rsplit(" ", 1)[0] + "..."
    return out


def extract_skills(text: str, sec: dict[str, str], field: str) -> list[str]:
    raw = first_section(sec, ["SKILL HIGHLIGHTS", "CORE QUALIFICATIONS", "SKILLS", "HIGHLIGHTS"])
    items: list[str] = []
    if raw:
        chunks = re.split(r"[\n•·]+|\s{2,}", raw)
        for c in chunks:
            c = re.sub(r"\s+", " ", c).strip(" -–—:;,")
            if 2 <= len(c) <= 42 and not c.lower().startswith(("summary", "experience", "education")):
                items.append(c)
    # Add field keywords found in the whole text
    t = text.lower()
    for s in FIELD_SKILLS.get(field, []):
        if s.lower() in t:
            items.append(s)
    # Dedupe, preserve order
    seen, out = set(), []
    for s in items:
        k = s.lower()
        if k not in seen:
            seen.add(k)
            out.append(s)
    if len(out) < 8:
        for s in FIELD_SKILLS.get(field, []):
            if s.lower() not in seen:
                out.append(s)
                seen.add(s.lower())
    return out[:20]


def extract_experience(text: str, sec: dict[str, str]) -> list[str]:
    raw = first_section(sec, ["PROFESSIONAL EXPERIENCE", "WORK EXPERIENCE", "WORK HISTORY", "EXPERIENCE"])
    if not raw:
        # fall back to everything after the skills section
        raw = text
    bullets: list[str] = []
    bad_markers = ["address", "date of birth", "permanent residency", "blah, blah"]
    head_starts = ("SUMMARY", "SKILLS", "EDUCATION", "CERTIFICATIONS", "EXPERIENCE", "PROFILE", "OBJECTIVE", "HIGHLIGHTS", "ACCOMPLISHMENTS")

    def usable(s: str) -> bool:
        s = re.sub(r"\s+", " ", s).strip(" -–—:;,")
        if len(s) < 45 or len(s) > 320:
            return False
        if s.upper().startswith(head_starts):
            return False
        if any(x in s.lower() for x in bad_markers):
            return False
        return True

    for segment in re.split(r"•", raw):
        flat = re.sub(r"\s+", " ", segment)
        for sent in re.split(r"(?<=[.!?])\s+", flat):
            if usable(sent):
                bullets.append(sent.strip())
    # dedupe and cap
    seen, out = set(), []
    for b in bullets:
        k = b.lower()[:80]
        if k not in seen:
            seen.add(k)
            out.append(b)
    return out[:12]


def extract_certs(sec: dict[str, str], field: str) -> list[str]:
    raw = first_section(sec, ["CERTIFICATIONS", "CORE QUALIFICATIONS"])
    certs = []
    if raw:
        for c in re.split(r"[\n•·,;]+|\s{2,}", raw):
            c = re.sub(r"\s+", " ", c).strip(" -–—:;,")
            if 3 <= len(c) <= 55 and any(w in c.lower() for w in ["cert", "ccna", "ccnp", "cissp", "security+", "aws", "azure", "oracle", "istqb", "pmp", "itil", "comptia", "mcse", "ccna", "cct"]):
                certs.append(c)
    if not certs:
        certs = CERT_FALLBACK.get(field, [])
    return certs[:5]


def field_summary(title: str, skills: list[str], field: str) -> str:
    s = (skills + ["the core stack"] * 3)[:3]
    templates = {
        "security": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Focused on detection quality, incident response and clear documentation.",
        "sysadmin": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Strong on reliable operations, troubleshooting and tidy runbooks.",
        "network": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Strong on troubleshooting, documentation and keeping complex networks boring.",
        "cloud": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Focused on secure, reproducible infrastructure and cost-aware operations.",
        "backend": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Builds maintainable services with strong review and testing habits.",
        "management": f"{title} with a track record of leading teams across {s[0]}, {s[1]} and {s[2]}. Focused on delivery predictability, hiring and healthy on-call.",
        "qa": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Focused on automation that shortens releases and catches the regressions that matter.",
        "dba": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Focused on performance, recoverability and zero-drama migrations.",
        "support": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Calm with users, precise with evidence, and disciplined about documentation.",
        "design": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Turns complex workflows into accessible, shipped interfaces.",
        "analyst": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Comfortable moving between data, code and business stakeholders.",
        "embedded": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Strong on debugging, test rigs and documentation from prototype to production.",
        "devops": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Focused on golden paths, reliability and secure supply chains.",
        "data": f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Turns operational data into decisions and measurable outcomes.",
    }
    return templates.get(field, f"{title} with hands-on experience in {s[0]}, {s[1]} and {s[2]}. Focused on reliable delivery and measurable outcomes.")


def build_cv(src: dict, idx: int, title: str, field: str, layout: str, job: str) -> dict:
    name, location, languages = IDENTITIES[idx]
    slug = slugify(name)
    ident = dict(
        name=name, location=location, languages=languages,
        email=f"{slug.lower()}@example.com",
        phone=f"+33 6 00 00 {idx+1:02d}",
        portfolio=f"portfolio.example.com/{slug.lower()}",
        company=["Northwind Atlas", "Cobalt Harbor", "Juniper Lane", "Helios Forge", "Quartz River",
                 "Glacier Cloud", "Lantern Retail", "Mosaic Ridge", "Orchid Byte", "Umbra Shield"][idx % 10],
    )
    text = sanitize(src["Resume_str"], ident)
    sec = sections(text)
    degree, university, grad_year = DEGREES[field]
    skills = extract_skills(text, sec, field)
    summary = field_summary(title, skills, field)
    experience = extract_experience(text, sec)
    if len(experience) < 3:
        experience += [
            f"Delivered production work using {skills[0]} and {skills[1]}, with tests, documentation and a clean handover.",
            "Partnered with product, design and operations on scoping, delivery and post-release support.",
            "Improved team standards through code review, runbooks and incident follow-ups.",
        ]
    return dict(
        id=f"CV{idx+1:02d}",
        source_id=src["ID"],
        name=name,
        slug=slug,
        title=title,
        field=field,
        layout=layout,
        job=job,
        location=location,
        email=ident["email"],
        phone=ident["phone"],
        portfolio=ident["portfolio"],
        summary=summary,
        skills=skills,
        experience=experience,
        education=[(degree, university, f"{grad_year-2} – {grad_year}")],
        certifications=extract_certs(sec, field),
        languages=languages,
        source_url="https://huggingface.co/datasets/opensporks/resumes",
        license="CC0-1.0",
    )


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def styles():
    ss = getSampleStyleSheet()
    return {
        "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=19, leading=22, textColor=NAVY, spaceAfter=1),
        "title": ParagraphStyle("title", fontName="Helvetica", fontSize=10.5, leading=13, textColor=ACCENT, spaceAfter=5),
        "contact": ParagraphStyle("contact", fontName="Helvetica", fontSize=8.2, leading=10.5, textColor=MUTED, spaceAfter=2),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=9.4, leading=11, textColor=NAVY, spaceBefore=8, spaceAfter=2),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.2, leading=12.2, textColor=colors.HexColor("#222222")),
        "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.0, leading=11.8, textColor=colors.HexColor("#222222"), leftIndent=9, bulletIndent=1, spaceAfter=1.5),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.2, leading=10.4, textColor=MUTED),
        "sidebar": ParagraphStyle("sidebar", fontName="Helvetica", fontSize=7.9, leading=10.4, textColor=colors.HexColor("#222222"), spaceAfter=1),
        "sidebar_h": ParagraphStyle("sidebar_h", fontName="Helvetica-Bold", fontSize=7.8, leading=9.5, textColor=ACCENT, spaceBefore=6, spaceAfter=2),
        "compact": ParagraphStyle("compact", fontName="Helvetica", fontSize=8.3, leading=10.5, textColor=colors.HexColor("#222222")),
        "compact_bullet": ParagraphStyle("compact_bullet", fontName="Helvetica", fontSize=8.2, leading=10.3, textColor=colors.HexColor("#222222"), leftIndent=8, bulletIndent=1, spaceAfter=1),
    }


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(colors.HexColor("#8A97A3"))
    canvas.drawString(17 * mm, 9 * mm, "Synthetic demo CV — fictional identity, CC0 source text")
    canvas.drawRightString(A4[0] - 17 * mm, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def job_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(colors.HexColor("#8A97A3"))
    canvas.drawString(18 * mm, 10 * mm, "Synthetic job description — fictional company and salary")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"{doc.page}")
    canvas.restoreState()


def header_flow(cv, st):
    return [
        Paragraph(escape(cv["name"]), st["name"]),
        Paragraph(escape(cv["title"]), st["title"]),
        Paragraph(escape(f'{cv["location"]}  ·  {cv["email"]}  ·  {cv["phone"]}  ·  {cv["portfolio"]}'), st["contact"]),
        HRFlowable(width="100%", thickness=0.8, color=RULE, spaceBefore=2, spaceAfter=5),
    ]


def section_flow(title, st):
    return [Paragraph(title.upper(), st["h2"]), HRFlowable(width="100%", thickness=0.4, color=RULE, spaceAfter=3)]


def exp_flow(cv, st, bullet_style="bullet", limit=12):
    flow = []
    for b in cv["experience"][:limit]:
        flow.append(Paragraph(escape(b), st[bullet_style], bulletText="•"))
    return flow


def pdf_classic(cv, path: Path):
    st = styles()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=17*mm, rightMargin=17*mm,
                          topMargin=14*mm, bottomMargin=14*mm,
                          title=f'{cv["name"]} — {cv["title"]}', author="Synthetic demo CV")
    story = []
    story += header_flow(cv, st)
    story += section_flow("Summary", st)
    story.append(Paragraph(escape(cv["summary"]), st["body"]))
    story += section_flow("Core skills", st)
    story.append(Paragraph(escape(" · ".join(cv["skills"])), st["body"]))
    story += section_flow("Experience", st)
    story += exp_flow(cv, st, limit=12)
    story += section_flow("Education", st)
    for deg, uni, yrs in cv["education"]:
        story.append(Paragraph(f"<b>{escape(deg)}</b> — {escape(uni)} · {escape(yrs)}", st["body"]))
    if cv["certifications"]:
        story += section_flow("Certifications", st)
        story.append(Paragraph(escape(" · ".join(cv["certifications"])), st["body"]))
    story += section_flow("Languages", st)
    story.append(Paragraph(escape(" · ".join(cv["languages"])), st["body"]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def pdf_modern(cv, path: Path):
    st = styles()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14*mm, rightMargin=14*mm,
                          topMargin=13*mm, bottomMargin=13*mm,
                          title=f'{cv["name"]} — {cv["title"]}', author="Synthetic demo CV")
    left = [
        Paragraph("CONTACT", st["sidebar_h"]),
        Paragraph(escape(cv["location"]), st["sidebar"]),
        Paragraph(escape(cv["email"]), st["sidebar"]),
        Paragraph(escape(cv["phone"]), st["sidebar"]),
        Paragraph(escape(cv["portfolio"]), st["sidebar"]),
        Paragraph("SKILLS", st["sidebar_h"]),
    ]
    for s in cv["skills"][:16]:
        left.append(Paragraph(escape(s), st["sidebar"], bulletText="–"))
    left += [Paragraph("LANGUAGES", st["sidebar_h"])]
    for l in cv["languages"]:
        left.append(Paragraph(escape(l), st["sidebar"]))
    if cv["certifications"]:
        left += [Paragraph("CERTIFICATIONS", st["sidebar_h"])]
        for c in cv["certifications"]:
            left.append(Paragraph(escape(c), st["sidebar"]))

    right = [Paragraph(escape(cv["name"]), st["name"]), Paragraph(escape(cv["title"]), st["title"]),
             HRFlowable(width="100%", thickness=0.8, color=RULE, spaceBefore=2, spaceAfter=4)]
    right += section_flow("Summary", st)
    right.append(Paragraph(escape(cv["summary"]), st["body"]))
    right += section_flow("Experience", st)
    right += exp_flow(cv, st, limit=10)
    right += section_flow("Education", st)
    for deg, uni, yrs in cv["education"]:
        right.append(Paragraph(f"<b>{escape(deg)}</b> — {escape(uni)} · {escape(yrs)}", st["body"]))
    table = Table([[left, right]], colWidths=[52*mm, 126*mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (1, 0), (1, 0), 2),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    doc.build([table], onFirstPage=footer, onLaterPages=footer)


def pdf_compact(cv, path: Path):
    st = styles()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14*mm, rightMargin=14*mm,
                          topMargin=11*mm, bottomMargin=12*mm,
                          title=f'{cv["name"]} — {cv["title"]}', author="Synthetic demo CV")
    story = []
    story.append(Paragraph(escape(cv["name"]), ParagraphStyle("cn", parent=st["name"], fontSize=16, leading=18)))
    story.append(Paragraph(escape(cv["title"]), ParagraphStyle("ct", parent=st["title"], fontSize=9.5, spaceAfter=2)))
    story.append(Paragraph(escape(f'{cv["location"]} · {cv["email"]} · {cv["phone"]}'), st["contact"]))
    story.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceBefore=1, spaceAfter=3))
    story.append(Paragraph(escape(cv["summary"]), st["compact"]))
    story.append(Paragraph("SKILLS", st["h2"]))
    story.append(Paragraph(escape(" · ".join(cv["skills"][:18])), st["compact"]))
    story.append(Paragraph("EXPERIENCE", st["h2"]))
    for b in cv["experience"][:9]:
        story.append(Paragraph(escape(b), st["compact_bullet"], bulletText="•"))
    story.append(Paragraph("EDUCATION", st["h2"]))
    for deg, uni, yrs in cv["education"]:
        story.append(Paragraph(escape(f"{deg} — {uni} · {yrs}"), st["compact"]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def pdf_table(cv, path: Path):
    st = styles()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
                          topMargin=13*mm, bottomMargin=13*mm,
                          title=f'{cv["name"]} — {cv["title"]}', author="Synthetic demo CV")
    story = header_flow(cv, st)
    story += section_flow("Summary", st)
    story.append(Paragraph(escape(cv["summary"]), st["body"]))
    story += section_flow("Skills", st)
    half = (len(cv["skills"]) + 1) // 2
    rows = []
    for i in range(half):
        a = cv["skills"][i]
        b = cv["skills"][i + half] if i + half < len(cv["skills"]) else ""
        rows.append([Paragraph(escape(a), st["small"]), Paragraph(escape(b), st["small"])])
    t = Table(rows, colWidths=[85*mm, 85*mm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
    ]))
    story.append(t)
    story += section_flow("Experience", st)
    for b in cv["experience"][:11]:
        story.append(Paragraph(escape(b), st["bullet"], bulletText="•"))
    story += section_flow("Education", st)
    ed = Table([[Paragraph(escape(d), st["small"]), Paragraph(escape(u), st["small"]), Paragraph(escape(y), st["small"])] for d, u, y in cv["education"]],
               colWidths=[55*mm, 75*mm, 40*mm])
    ed.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(ed)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


# ---------------------------------------------------------------------------
# DOCX / HTML / Markdown / TXT / JSON
# ---------------------------------------------------------------------------

def docx_cv(cv, path: Path):
    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(1.8)
    sec.top_margin = sec.bottom_margin = Cm(1.5)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    p = doc.add_paragraph()
    r = p.add_run(cv["name"])
    r.bold = True
    r.font.size = Pt(20)
    r.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    p = doc.add_paragraph(cv["title"])
    p.runs[0].font.size = Pt(11)
    p.runs[0].font.color.rgb = RGBColor(0x2E, 0x6E, 0x8E)
    p = doc.add_paragraph(f'{cv["location"]}  ·  {cv["email"]}  ·  {cv["phone"]}  ·  {cv["portfolio"]}')
    p.runs[0].font.size = Pt(8.5)
    doc.add_paragraph("Summary").runs[0].bold = True
    doc.add_paragraph(cv["summary"])
    doc.add_paragraph("Core skills").runs[0].bold = True
    t = doc.add_table(rows=0, cols=2)
    t.style = "Light Grid Accent 1"
    for i in range(0, len(cv["skills"]), 2):
        cells = t.add_row().cells
        cells[0].text = cv["skills"][i]
        if i + 1 < len(cv["skills"]):
            cells[1].text = cv["skills"][i + 1]
    doc.add_paragraph("Experience").runs[0].bold = True
    for b in cv["experience"][:11]:
        doc.add_paragraph(b, style="List Bullet")
    doc.add_paragraph("Education").runs[0].bold = True
    for deg, uni, yrs in cv["education"]:
        doc.add_paragraph(f"{deg} — {uni} · {yrs}")
    if cv["certifications"]:
        doc.add_paragraph("Certifications").runs[0].bold = True
        doc.add_paragraph(" · ".join(cv["certifications"]))
    doc.add_paragraph("Languages").runs[0].bold = True
    doc.add_paragraph(" · ".join(cv["languages"]))
    f = sec.footer.paragraphs[0]
    f.text = "Synthetic demo CV — fictional identity, CC0 source text"
    f.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in f.runs:
        run.font.size = Pt(7)
        run.font.color.rgb = RGBColor(0x8A, 0x97, 0xA3)
    doc.save(str(path))


def html_cv(cv, path: Path):
    skills = "".join(f"<li>{html.escape(s)}</li>" for s in cv["skills"])
    exp = "".join(f"<li>{html.escape(b)}</li>" for b in cv["experience"][:12])
    ed = "".join(f"<li><b>{html.escape(d)}</b> — {html.escape(u)} · {html.escape(y)}</li>" for d, u, y in cv["education"])
    certs = "".join(f"<li>{html.escape(c)}</li>" for c in cv["certifications"])
    langs = "".join(f"<li>{html.escape(l)}</li>" for l in cv["languages"])
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{html.escape(cv['name'])} — {html.escape(cv['title'])}</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;color:#222;max-width:820px;margin:32px auto;padding:0 24px;line-height:1.45}}
h1{{color:#1F3A5F;margin:0;font-size:28px}} .role{{color:#2E6E8E;font-size:15px;margin:4px 0 8px}}
.contact{{color:#5B6770;font-size:12px;border-bottom:2px solid #C9D6E2;padding-bottom:10px;margin-bottom:16px}}
h2{{color:#1F3A5F;font-size:14px;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid #C9D6E2;padding-bottom:3px;margin-top:20px}}
ul{{margin:6px 0 0 18px;padding:0}} li{{margin:3px 0}} .small{{font-size:12px;color:#5B6770}}
</style></head><body>
<h1>{html.escape(cv['name'])}</h1><div class="role">{html.escape(cv['title'])}</div>
<div class="contact">{html.escape(cv['location'])} · {html.escape(cv['email'])} · {html.escape(cv['phone'])} · {html.escape(cv['portfolio'])}</div>
<h2>Summary</h2><p>{html.escape(cv['summary'])}</p>
<h2>Skills</h2><ul>{skills}</ul>
<h2>Experience</h2><ul>{exp}</ul>
<h2>Education</h2><ul>{ed}</ul>
<h2>Certifications</h2><ul>{certs}</ul>
<h2>Languages</h2><ul>{langs}</ul>
<p class="small">Synthetic demo CV — fictional identity. Source text CC0-1.0.</p>
</body></html>"""
    path.write_text(doc, encoding="utf-8")


def markdown_cv(cv, path: Path):
    lines = [f"# {cv['name']}", f"**{cv['title']}**", "",
             f"{cv['location']} · {cv['email']} · {cv['phone']} · {cv['portfolio']}", "",
             "## Summary", cv["summary"], "", "## Core skills", ""]
    lines += [f"- {s}" for s in cv["skills"]]
    lines += ["", "## Experience", ""]
    lines += [f"- {b}" for b in cv["experience"][:12]]
    lines += ["", "## Education", ""]
    lines += [f"- **{d}** — {u} · {y}" for d, u, y in cv["education"]]
    if cv["certifications"]:
        lines += ["", "## Certifications", ""] + [f"- {c}" for c in cv["certifications"]]
    lines += ["", "## Languages", ""] + [f"- {l}" for l in cv["languages"]]
    lines += ["", "---", "*Synthetic demo CV — fictional identity. Source text CC0-1.0.*"]
    path.write_text("\n".join(lines), encoding="utf-8")


def txt_cv(cv, path: Path):
    lines = [cv["name"].upper(), cv["title"], f'{cv["location"]} | {cv["email"]} | {cv["phone"]} | {cv["portfolio"]}', "", "SUMMARY", cv["summary"], "", "CORE SKILLS", ", ".join(cv["skills"]), "", "EXPERIENCE"]
    lines += [f"- {b}" for b in cv["experience"][:12]]
    lines += ["", "EDUCATION"] + [f"- {d} — {u} ({y})" for d, u, y in cv["education"]]
    if cv["certifications"]:
        lines += ["", "CERTIFICATIONS"] + [f"- {c}" for c in cv["certifications"]]
    lines += ["", "LANGUAGES", ", ".join(cv["languages"]), "", "Synthetic demo CV — fictional identity. Source text CC0-1.0."]
    path.write_text("\n".join(lines), encoding="utf-8")


def json_cv(cv, path: Path):
    path.write_text(json.dumps(cv, indent=2, ensure_ascii=False), encoding="utf-8")


def scanned_pdf(src: Path, dst: Path):
    doc = fitz.open(str(src))
    imgs = []
    for page in doc:
        pix = page.get_pixmap(dpi=140)
        imgs.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
    if not imgs:
        raise RuntimeError("no pages")
    imgs[0].save(str(dst), "PDF", resolution=140, save_all=True, append_images=imgs[1:])
    doc.close()


# ---------------------------------------------------------------------------
# Jobs / index / applications
# ---------------------------------------------------------------------------

def job_markdown(job):
    return f"""# {job['title']}

**{job['company']}** · {job['location']} · {job['mode']} · {job['level']} · {job['years']}+ years

## About the role

{job['summary']}

## What you will do

- Own the day-to-day work of a {job['title'].lower()} on a small, product-focused team.
- Partner with product, design and security on scoped, measurable outcomes.
- Improve reliability, documentation and the team's engineering standards.
- Mentor peers and contribute to hiring and onboarding.

## Must have

{chr(10).join('- ' + x for x in job['must'])}

## Nice to have

{chr(10).join('- ' + x for x in job['nice'])}

## What we offer

- A fictional demo company, a real problem, and a team that reviews its own work.
- Hybrid/remote flexibility, learning budget, and a calm on-call rotation.

*Synthetic job description for demo purposes. Company and salary are fictional.*
"""


def job_pdf(job, path: Path):
    st = styles()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                          topMargin=16*mm, bottomMargin=16*mm,
                          title=f"{job['title']} — {job['company']}", author="Synthetic demo job")
    story = [
        Paragraph(escape(job["company"]), ParagraphStyle("co", fontName="Helvetica-Bold", fontSize=9, textColor=ACCENT, spaceAfter=2)),
        Paragraph(escape(job["title"]), ParagraphStyle("jt", fontName="Helvetica-Bold", fontSize=20, textColor=NAVY, leading=23, spaceAfter=2)),
        Paragraph(escape(f"{job['location']} · {job['mode']} · {job['level']} · {job['years']}+ years"), st["contact"]),
        HRFlowable(width="100%", thickness=0.8, color=RULE, spaceBefore=3, spaceAfter=8),
        Paragraph("About the role", st["h2"]),
        Paragraph(escape(job["summary"]), st["body"]),
        Paragraph("What you will do", st["h2"]),
    ]
    for b in [
        f"Own the day-to-day work of a {job['title'].lower()} on a small, product-focused team.",
        "Partner with product, design and security on scoped, measurable outcomes.",
        "Improve reliability, documentation and the team's engineering standards.",
        "Mentor peers and contribute to hiring and onboarding.",
    ]:
        story.append(Paragraph(escape(b), st["bullet"], bulletText="•"))
    story.append(Paragraph("Must have", st["h2"]))
    for b in job["must"]:
        story.append(Paragraph(escape(b), st["bullet"], bulletText="•"))
    story.append(Paragraph("Nice to have", st["h2"]))
    for b in job["nice"]:
        story.append(Paragraph(escape(b), st["bullet"], bulletText="•"))
    story.append(Paragraph("What we offer", st["h2"]))
    story.append(Paragraph("A fictional demo company, a real problem, and a team that reviews its own work. Hybrid/remote flexibility, learning budget, and a calm on-call rotation.", st["body"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Synthetic job description — company and salary are fictional.", st["small"]))
    doc.build(story, onFirstPage=job_footer, onLaterPages=job_footer)


def main():
    if not SRC.exists():
        raise SystemExit(f"missing {SRC}")
    rows = {}
    with SRC.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            rows[r["ID"]] = r
    for d in [OUT / "pdf", OUT / "docx", OUT / "html", OUT / "md", OUT / "txt", OUT / "json", OUT / "scanned", JOBS_OUT]:
        d.mkdir(parents=True, exist_ok=True)

    cvs = []
    for i, (src_id, title, field, layout, formats, job) in enumerate(SELECTED):
        if src_id not in rows:
            raise SystemExit(f"missing source {src_id}")
        cv = build_cv(rows[src_id], i, title, field, layout, job)
        cvs.append(cv)
        base = f'{cv["id"]}_{cv["slug"]}'
        if layout == "classic":
            pdf_classic(cv, OUT / "pdf" / f"{base}.pdf")
        elif layout == "modern":
            pdf_modern(cv, OUT / "pdf" / f"{base}.pdf")
        elif layout == "compact":
            pdf_compact(cv, OUT / "pdf" / f"{base}.pdf")
        elif layout == "table":
            pdf_table(cv, OUT / "pdf" / f"{base}.pdf")
        docx_cv(cv, OUT / "docx" / f"{base}.docx")
        html_cv(cv, OUT / "html" / f"{base}.html")
        markdown_cv(cv, OUT / "md" / f"{base}.md")
        txt_cv(cv, OUT / "txt" / f"{base}.txt")
        json_cv(cv, OUT / "json" / f"{base}.json")

    # two image-only "scanned" versions for OCR/parsing tests
    for cv in [cvs[8], cvs[20]]:
        base = f'{cv["id"]}_{cv["slug"]}'
        src = OUT / "pdf" / f"{base}.pdf"
        if src.exists():
            scanned_pdf(src, OUT / "scanned" / f"{base}_scanned.pdf")

    # index
    with (OUT / "index.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["candidate_id", "name", "title", "field", "source_id", "source_url", "license", "layout", "formats", "job_id", "email", "location"])
        for cv in cvs:
            fmts = ["pdf", "txt", "json"]
            if (OUT / "docx" / f'{cv["id"]}_{cv["slug"]}.docx').exists(): fmts.insert(1, "docx")
            if (OUT / "html" / f'{cv["id"]}_{cv["slug"]}.html').exists(): fmts.insert(1, "html")
            if (OUT / "md" / f'{cv["id"]}_{cv["slug"]}.md').exists(): fmts.insert(1, "md")
            w.writerow([cv["id"], cv["name"], cv["title"], cv["field"], cv["source_id"], cv["source_url"], cv["license"], cv["layout"], ",".join(fmts), cv["job"], cv["email"], cv["location"]])

    # applications
    statuses = ["applied", "screening", "interview", "offer", "rejected", "withdrawn"]
    with (OUT / "applications.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["application_id", "candidate_id", "job_id", "applied_at", "status", "source", "note"])
        for i, cv in enumerate(cvs):
            w.writerow([f"A{i+1:03d}", cv["id"], cv["job"], f"2026-10-{(i % 25) + 1:02d}", statuses[i % len(statuses)], ["careers_page", "linkedin", "referral", "agency"][i % 4], "Synthetic application"])
            if i % 3 == 0:
                other = "J02" if cv["job"] != "J02" else "J03"
                w.writerow([f"A{i+1:03d}b", cv["id"], other, f"2026-10-{(i % 25) + 2:02d}", "applied", "job_board", "Synthetic second application"])

    # jobs
    for job in JOBS:
        (JOBS_OUT / f"{job['id']}_{slugify(job['title'])}.md").write_text(job_markdown(job), encoding="utf-8")
        job_pdf(job, JOBS_OUT / f"{job['id']}_{slugify(job['title'])}.pdf")

    (OUT / "ground_truth.json").write_text(json.dumps({"cvs": cvs, "jobs": JOBS}, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "sources.md").write_text(
        "# CV corpus sources\n\n"
        "- **Dataset:** `opensporks/resumes` on Hugging Face — 2,484 resume examples, CC0-1.0.\n"
        "  https://huggingface.co/datasets/opensporks/resumes\n"
        "- **Original:** Kaggle `snehaanbhawal/resume-dataset` (CC0-1.0), scraped from LiveCareer resume examples.\n"
        "  https://www.kaggle.com/datasets/snehaanbhawal/resume-dataset\n"
        "- **Selection:** 30 technical resumes from Information Technology, Engineering, Designer and Digital Media categories.\n"
        "- **Transformation:** source text is sanitized (emails, phones, URLs, company placeholders, locations, clearance/military references), paired with fictional identities and regenerated in PDF/DOCX/HTML/Markdown/TXT/JSON.\n"
        "- **No real person is represented by the final files.** Source text may contain residual template artifacts; report them before redistribution.\n"
        "- **Generated:** 2026-10-31.\n",
        encoding="utf-8",
    )

    # Zip next to the folder, not inside it: an archive written into the folder it zips
    # keeps adding itself and grows without end.
    shutil.make_archive(str(ROOT / "data" / "tech_cv_corpus"), "zip", str(OUT))
    print(f"built {len(cvs)} CVs")
    print("formats:", {k: len(list((OUT / k).glob('*'))) for k in ['pdf', 'docx', 'html', 'md', 'txt', 'json', 'scanned']})
    print("jobs:", len(JOBS))


if __name__ == "__main__":
    main()
