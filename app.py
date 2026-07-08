from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, render_template, request, send_file, redirect, url_for, flash
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "generated_reports"
REPORT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = "change-this-before-production"


def read_csv_dicts(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_data() -> Dict[str, List[Dict[str, str]]]:
    return {
        "students": read_csv_dicts(DATA_DIR / "students.csv"),
        "requirements": read_csv_dicts(DATA_DIR / "program_requirements.csv"),
        "history": read_csv_dicts(DATA_DIR / "course_history.csv"),
        "activity": read_csv_dicts(DATA_DIR / "blackboard_activity.csv"),
    }


def as_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def risk_score(student: Dict[str, str], activity: Optional[Dict[str, str]], audit: Dict) -> Dict:
    gpa = as_float(student.get("gpa"))
    gpa_score = min(max((gpa / 4.0) * 100, 0), 100)

    if not activity:
        current_grade = attendance = 75.0
        missing_assignments = 0
        discussion_posts = 1
        last_login = 3
    else:
        current_grade = as_float(activity.get("current_grade"))
        attendance = as_float(activity.get("attendance_percent"))
        missing_assignments = as_int(activity.get("missing_assignments"))
        discussion_posts = as_int(activity.get("discussion_posts"))
        last_login = as_int(activity.get("last_login_days_ago"))

    assignment_score = max(100 - (missing_assignments * 10), 0)
    discussion_score = min(discussion_posts * 20, 100)
    login_score = max(100 - (last_login * 10), 0)
    completion_score = audit["completion_percent"]

    overall = round(
        (gpa_score * 0.25)
        + (current_grade * 0.20)
        + (attendance * 0.20)
        + (assignment_score * 0.15)
        + (discussion_score * 0.10)
        + (login_score * 0.05)
        + (completion_score * 0.05),
        1,
    )

    if overall >= 80:
        level = "Green - On Track"
    elif overall >= 65:
        level = "Yellow - Needs Attention"
    else:
        level = "Red - Immediate Intervention"

    return {
        "overall": overall,
        "level": level,
        "gpa_score": round(gpa_score, 1),
        "current_grade": current_grade,
        "attendance": attendance,
        "assignment_score": assignment_score,
        "discussion_score": discussion_score,
        "login_score": login_score,
        "completion_score": completion_score,
        "missing_assignments": missing_assignments,
        "discussion_posts": discussion_posts,
        "last_login": last_login,
    }


def build_audit(student_id: int, data: Dict[str, List[Dict[str, str]]]) -> Dict:
    student = next((s for s in data["students"] if as_int(s.get("student_id")) == student_id), None)
    if not student:
        raise ValueError("Student not found")

    reqs = [
        r for r in data["requirements"]
        if r.get("program") == student.get("program") and as_int(r.get("catalog_year")) == as_int(student.get("catalog_year"))
    ]
    history = [h for h in data["history"] if as_int(h.get("student_id")) == student_id]
    activity = next((a for a in data["activity"] if as_int(a.get("student_id")) == student_id), None)

    completed_codes = {h.get("course_code") for h in history if h.get("status", "").lower() == "completed"}
    in_progress_codes = {h.get("course_code") for h in history if h.get("status", "").lower() == "in progress"}
    failed_codes = {h.get("course_code") for h in history if h.get("status", "").lower() == "failed"}

    audit_rows: List[Dict] = []
    missing: List[str] = []
    prereq_issues: List[str] = []

    for req in reqs:
        code = req.get("course_code", "")
        prereq = (req.get("prerequisite") or "").strip()
        if code in completed_codes:
            status = "Complete"
        elif code in in_progress_codes:
            status = "In Progress"
        else:
            status = "Not Started"
            missing.append(code)

        if status in {"In Progress", "Not Started"} and prereq and prereq not in completed_codes:
            prereq_issues.append(f"{code} requires {prereq} before enrollment/completion.")

        audit_rows.append({
            "course_code": code,
            "course_title": req.get("course_title", ""),
            "credits": as_int(req.get("credits")),
            "prerequisite": prereq,
            "status": status,
        })

    total_required = sum(as_int(r.get("credits")) for r in reqs)
    completed_required = sum(row["credits"] for row in audit_rows if row["status"] == "Complete")
    completion_percent = round((completed_required / total_required) * 100, 1) if total_required else 0
    credits_remaining = max(total_required - completed_required, 0)

    audit = {
        "student": student,
        "activity": activity or {},
        "rows": audit_rows,
        "missing_courses": missing,
        "failed_courses": sorted(list(failed_codes)),
        "prereq_issues": prereq_issues,
        "total_required": total_required,
        "completed_required": completed_required,
        "credits_remaining": credits_remaining,
        "completion_percent": completion_percent,
        "generated_on": datetime.now().strftime("%B %d, %Y"),
    }
    audit["risk"] = risk_score(student, activity, audit)
    audit["recommendations"] = generate_recommendations(audit)
    return audit


def generate_recommendations(audit: Dict) -> List[str]:
    recs = []
    risk = audit["risk"]
    student = audit["student"]

    if risk["overall"] < 65:
        recs.append("Schedule immediate advisor follow-up and document an academic action plan.")
    elif risk["overall"] < 80:
        recs.append("Schedule advisor check-in within 7-14 days to review progress and participation.")
    else:
        recs.append("Student appears on track; continue standard advising and registration planning.")

    if as_float(student.get("gpa")) < 2.0:
        recs.append("Review GPA recovery plan, SAP risk, and possible course repeat options.")
    if risk["missing_assignments"] >= 3:
        recs.append("Advise student to submit missing assignments and contact current instructors.")
    if risk["discussion_posts"] == 0:
        recs.append("Remind student to complete required Blackboard discussion participation.")
    if audit["failed_courses"]:
        recs.append("Review failed courses for repeat scheduling and prerequisite impact.")
    if audit["prereq_issues"]:
        recs.append("Review prerequisite sequencing before approving next-term registration.")
    if str(student.get("va_student", "")).lower() == "yes" and risk["overall"] < 75:
        recs.append("Document VA-related attendance/participation risk and advise student on immediate participation requirements.")
    if audit["missing_courses"]:
        recs.append("Use missing course list to plan the next registration sequence.")
    return recs


def generate_pdf(audit: Dict) -> Path:
    student = audit["student"]
    filename = f"advising_audit_{student['student_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = REPORT_DIR / filename

    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    header_style = styles["Heading2"]
    normal = styles["BodyText"]
    small = ParagraphStyle("small", parent=normal, fontSize=8, leading=10)
    story = []

    story.append(Paragraph("Advising Packet & Degree Audit Form", title_style))
    story.append(Paragraph(f"Generated: {audit['generated_on']}", normal))
    story.append(Spacer(1, 0.15 * inch))

    snapshot = [
        ["Student", f"{student['first_name']} {student['last_name']}", "Student ID", str(student['student_id'])],
        ["Program", student["program"], "Catalog Year", str(student["catalog_year"])],
        ["GPA", str(student["gpa"]), "Academic Standing", student["academic_standing"]],
        ["Credits Earned", str(student["credits_earned"]), "Credits Remaining", str(audit["credits_remaining"])],
        ["Completion", f"{audit['completion_percent']}%", "Risk Level", audit["risk"]["level"]],
    ]
    story.append(Table(snapshot, colWidths=[1.25 * inch, 2.0 * inch, 1.4 * inch, 2.1 * inch], style=table_style()))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Degree Audit", header_style))
    rows = [["Course", "Title", "Credits", "Prerequisite", "Status"]]
    for row in audit["rows"]:
        rows.append([row["course_code"], Paragraph(row["course_title"], small), row["credits"], row["prerequisite"], row["status"]])
    story.append(Table(rows, colWidths=[0.9 * inch, 2.45 * inch, 0.7 * inch, 1.1 * inch, 1.3 * inch], style=table_style(header=True)))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Academic Risk Analysis", header_style))
    risk = audit["risk"]
    risk_rows = [
        ["Overall Score", risk["overall"], "Risk Level", risk["level"]],
        ["Current Grade", risk["current_grade"], "Attendance", f"{risk['attendance']}%"],
        ["Missing Assignments", risk["missing_assignments"], "Discussion Posts", risk["discussion_posts"]],
        ["Last Login", f"{risk['last_login']} days ago", "Completion", f"{risk['completion_score']}%"],
    ]
    story.append(Table(risk_rows, colWidths=[1.6 * inch, 1.4 * inch, 1.6 * inch, 1.8 * inch], style=table_style()))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Advisor Recommendations", header_style))
    for rec in audit["recommendations"]:
        story.append(Paragraph(f"• {rec}", normal))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Advisor Notes", header_style))
    notes = (
        f"Student reviewed degree progress for the {student['program']} program. "
        f"The student has completed {audit['completed_required']} required credits and has approximately "
        f"{audit['credits_remaining']} required credits remaining. Risk level is {audit['risk']['level']}. "
        "Advisor should review course sequencing, participation status, and registration recommendations with the student."
    )
    story.append(Paragraph(notes, normal))
    story.append(Spacer(1, 0.35 * inch))

    signature_rows = [["Student Signature", "Date", "Advisor Signature", "Date"], ["", "", "", ""]]
    story.append(Table(signature_rows, colWidths=[2.0 * inch, 1.0 * inch, 2.0 * inch, 1.0 * inch], rowHeights=[0.3 * inch, 0.45 * inch], style=signature_style()))

    doc.build(story)
    return path


def table_style(header: bool = False) -> TableStyle:
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey))
        commands.append(("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"))
    return TableStyle(commands)


def signature_style() -> TableStyle:
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])


@app.route("/")
def index():
    data = load_data()
    students = sorted(data["students"], key=lambda x: (x.get("last_name", ""), x.get("first_name", "")))
    return render_template("index.html", students=students)


@app.route("/student/<int:student_id>")
def student_detail(student_id: int):
    try:
        audit = build_audit(student_id, load_data())
        return render_template("student_detail.html", audit=audit)
    except ValueError:
        flash("Student not found.")
        return redirect(url_for("index"))


@app.route("/student/<int:student_id>/pdf")
def student_pdf(student_id: int):
    audit = build_audit(student_id, load_data())
    pdf_path = generate_pdf(audit)
    return send_file(pdf_path, as_attachment=True)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        expected = {
            "students": DATA_DIR / "students.csv",
            "requirements": DATA_DIR / "program_requirements.csv",
            "history": DATA_DIR / "course_history.csv",
            "activity": DATA_DIR / "blackboard_activity.csv",
        }
        for field, target in expected.items():
            file = request.files.get(field)
            if file and file.filename:
                file.save(target)
        flash("CSV files updated successfully.")
        return redirect(url_for("index"))
    return render_template("upload.html")


if __name__ == "__main__":
    app.run(debug=True)
