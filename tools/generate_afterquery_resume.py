"""One-off script: builds the AfterQuery Physicist resume as a .docx file."""
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT_PATH = "Tommy_Orok_Resume_AfterQuery_Physicist.docx"

doc = Document()

# Base style
style = doc.styles["Normal"]
style.font.name = "Calibri"
style.font.size = Pt(10.5)

for section in doc.sections:
    section.top_margin = Inches(0.5)
    section.bottom_margin = Inches(0.5)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)


def add_heading(text):
    p = doc.add_paragraph()
    run = p.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = None
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.border_bottom = None
    return p


def add_bullet(text):
    p = doc.add_paragraph(style="List Bullet")
    p.add_run(text)
    p.paragraph_format.space_after = Pt(2)


# --- Header ---
name_p = doc.add_paragraph()
name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
name_run = name_p.add_run("Tommy Orok")
name_run.bold = True
name_run.font.size = Pt(20)

headline_p = doc.add_paragraph()
headline_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
headline_run = headline_p.add_run(
    "Senior Physicist | AI Problem Designer & Model-Validation Expert | "
    "Real-World Physics & Reasoning Specialist (Remote)"
)
headline_run.italic = True
headline_run.font.size = Pt(11)

contact_p = doc.add_paragraph()
contact_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
contact_p.add_run(
    "(770) 383-5362  |  tommyorok43@gmail.com  |  Powder Springs, GA  |  "
    "linkedin.com/in/tommy-orok-8273ab120"
).font.size = Pt(9.5)

# --- Summary ---
add_heading("Summary")
summary_lines = [
    "I align with AfterQuery's mission to craft and verify physics reasoning by pairing a Columbia "
    "University physics concentration with rigorous computational methods. My coursework in Quantum "
    "Mechanics I & II and Special Relativity under Professor Brian Greene, combined with years tutoring "
    "physics, including astrophysics, relativity, quantum field theory, and quantum "
    "chromodynamics (the strong force, gluons, and color charge), gives me the physical "
    "intuition and the habit of precise, checkable reasoning this role demands.",
    "I led a machine learning platform for mean reversion trading using Python and PyTorch, built data "
    "pipelines in S3, and engineered features such as z-scores, realized volatility, volume anomalies, "
    "bid-ask spreads, and moving averages, with walk-forward validation to mirror live trading.",
    "I evaluated models on Sharpe ratio, maximum drawdown, and profit factor, and deployed them on AWS "
    "SageMaker endpoints with Processing Jobs and Hyperparameter Tuning for continual improvement.",
    "I built a scalable backend in Node.js with MongoDB for Redfish Beach Equipment Rental Platform, "
    "encoding business rules and preserving data integrity, and I designed a comprehensive API layer "
    "with unit and integration tests plus feature flags to enable safe rollout.",
    "I developed The Tommy Planner to manage recursive, long running work with preserved context, "
    "current-topic pointers, subplans, cycles, and a traceable history of decisions and handoff notes.",
]
for line in summary_lines:
    p = doc.add_paragraph()
    p.add_run(line)
    p.paragraph_format.space_after = Pt(6)

# --- Physics Coursework & Teaching ---
add_heading("Physics Coursework & Teaching")
add_bullet(
    "Completed physics concentration coursework at Columbia University under Professor Brian Greene: "
    "Quantum Mechanics I (PHYS G4021) and Quantum Mechanics II (PHYS G4022), Fall 2012, and Special "
    "Relativity (PHYS C2001), Spring 2014."
)
add_bullet(
    "Tutored physics throughout college and in the years since, covering astrophysics, special and "
    "general relativity, quantum field theory, and quantum chromodynamics, including the strong "
    "force, gluon-mediated interactions, and color charge."
)

# --- Professional Experience ---
add_heading("Professional Experience")

jobs = [
    {
        "title": "AI Consultant",
        "comp": "Kacha Inc",
        "loc": "Atlanta, GA",
        "dates": "Aug 2023 – Present",
        "bullets": [
            "Directed a structured multi-LLM review cycle in which a worker model drafted a solution and "
            "a reviewer model audited it against a scoring rubric, iterating through revisions until the "
            "response reached a 9-out-of-10 quality threshold.",
            "Audited AI-generated outputs for logical consistency, correctness, and completeness against "
            "documented requirements, applying a structured 10-point rubric to flag reasoning errors "
            "before they reached production.",
            "Maintained a centralized, traceable knowledge base linking decisions, requirements, and "
            "prior review outcomes across sessions, ensuring reasoning and rationale could be audited and "
            "reproduced over time.",
        ],
    },
    {
        "title": "Software Consultant",
        "comp": "Ivy Kode",
        "loc": "Atlanta, GA",
        "dates": "2019 – 2025",
        "bullets": [
            "Provided one-on-one instruction and debugging support across multiple programming "
            "languages, breaking down complex technical concepts into clear, step-by-step explanations "
            "tailored to each learner's level.",
            "Worked directly with stakeholders to clarify ambiguous or incomplete requirements, often "
            "identifying that the request as stated didn't match the underlying problem that needed to "
            "be solved before recommending a corrected approach.",
            "Adapted quickly across a wide range of technology stacks and problem domains from one "
            "engagement to the next, applying consistent underlying principles and problem-solving "
            "methodology regardless of the specific tools involved.",
        ],
    },
    {
        "title": "Head Systems Engineer",
        "comp": "Gryphus Trading",
        "loc": "New York, NY",
        "dates": "Dec 2015 – Aug 2019",
        "bullets": [
            "Designed and built a C++ validation framework using GoogleTest that replayed historical data "
            "through the system and flagged any output that diverged from expected, previously verified "
            "results.",
            "Used a systematic, hypothesis-driven diagnostic process, isolating variables one at a time "
            "to distinguish between application-level and infrastructure-level causes, to pinpoint the "
            "exact source of incorrect or unexpected system behavior.",
            "Built a data-normalization layer that converted raw exchange data into accurate "
            "floating-point values, applying documented conversion factors precisely to preserve "
            "mathematical correctness across every transformation.",
        ],
    },
    {
        "title": "Software Developer",
        "comp": "21st Century Realty",
        "loc": "Austell, GA",
        "dates": "Oct 2017 – May 2020",
        "bullets": [
            "Built repair and reconciliation tooling that diagnosed inconsistencies between stored data "
            "and canonical calculations, previewed corrective changes, and validated that final records "
            "matched expected ground-truth values before applying them.",
            "Implemented validation logic across frontend, API, and database layers to catch inconsistent "
            "or invalid data before it could reach production, ensuring every business rule was enforced "
            "and verifiable at each stage.",
            "Translated complex, interdependent business rules, such as contract entitlements, inventory "
            "availability, and multi-step checkout logic, into precise, testable system behavior, "
            "ensuring consistent outcomes across a wide range of edge cases.",
        ],
    },
]

for job in jobs:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(1)
    run = p.add_run(f"{job['title']} — {job['comp']}")
    run.bold = True
    run.font.size = Pt(11)
    p.add_run(f"    {job['loc']}").italic = True

    dates_p = doc.add_paragraph()
    dates_p.paragraph_format.space_after = Pt(2)
    dates_run = dates_p.add_run(job["dates"])
    dates_run.italic = True
    dates_run.font.size = Pt(9.5)

    for b in job["bullets"]:
        add_bullet(b)

# --- Education ---
add_heading("Education")
edu_p = doc.add_paragraph()
edu_run = edu_p.add_run("Bachelor's Degree, Computer Science — Columbia University")
edu_run.bold = True
edu_p.add_run("    New York, NY").italic = True
dates_p = doc.add_paragraph()
dates_p.paragraph_format.space_after = Pt(2)
dates_run = dates_p.add_run("Aug 2012 – May 2016")
dates_run.italic = True
dates_run.font.size = Pt(9.5)
add_bullet("Concentration in Physics")
add_bullet(
    "Relevant coursework under Professor Brian Greene: Quantum Mechanics I (PHYS G4021), Quantum "
    "Mechanics II (PHYS G4022), and Special Relativity (PHYS C2001)"
)

# --- Skills ---
add_heading("Skills")
skills = [
    "Physics Problem Formulation", "Model Validation", "General & Special Relativity",
    "Quantum Field Theory", "Quantum Chromodynamics", "Astrophysics", "Technical Writing",
    "Python Programming", "Research Methodology", "Team Leadership", "Physics Tutoring",
    "Web Scraping",
]
skills_p = doc.add_paragraph()
skills_p.add_run("  •  ".join(skills)).font.size = Pt(10)

doc.save(OUT_PATH)
print(f"Saved to {OUT_PATH}")
