# Advising Packet + Degree Audit Generator MVP

This pilot application generates advising packets and degree audit forms from CSV exports.

## What it does

- Imports student profile data
- Imports program requirements
- Imports student course history
- Imports Blackboard activity data
- Calculates a Student Success Risk score
- Generates missing course and prerequisite issue lists
- Creates advisor recommendations
- Exports a PDF advising packet and audit form

## Run locally

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:5000
```

## CSV files

Place CSV files in the `data` folder or upload them through the web interface.

Required files:

- `students.csv`
- `program_requirements.csv`
- `course_history.csv`
- `blackboard_activity.csv`

## Pilot recommendation

Use sample or de-identified student data first. Do not use live student records until school leadership/IT confirms FERPA, data security, and system access requirements.
