# Student Attendance & Performance Dashboard

A reusable Streamlit dashboard for combining tutorial attendance workbooks with Canvas-style gradebook exports.

## What it does

- Upload an attendance `.xlsx` workbook containing multiple tutorial/class sheets.
- Automatically finds the row containing `Student Number` and `Student Name`.
- Extracts only genuine `P` / `A` attendance records, so different class dates and blank spacer columns are handled automatically.
- Counts students by **unique Student Number**, avoiding duplicate-name issues.
- Upload a Canvas gradebook `.csv` or `.xlsx`.
- Match attendance `Student Number` to gradebook `SIS User ID`.
- Choose the grade field used by the dashboard. `Unposted Final Score` is selected by default when available.
- Adjust participation, performance, and alert thresholds in the sidebar.
- View KPI cards, participation chart, performance chart, attendance-vs-grade scatter plot, and an actionable alert list.
- Download the processed student summary as Excel or CSV.
- Includes data-quality checks for skipped sheets, duplicate attendance rows, conflicting P/A entries, missing grades, and missing attendance.

## Run locally

1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Create and activate a virtual environment if desired.
4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Run:

```bash
streamlit run app.py
```

Your browser will open the dashboard.

## Deploy with GitHub + Streamlit Community Cloud

1. Create a GitHub repository.
2. Upload only:
   - `app.py`
   - `requirements.txt`
   - `README.md`
   - `.gitignore`
3. **Do not upload student attendance or grade files to GitHub.**
4. In Streamlit Community Cloud, create a new app from the repository and select `app.py`.
5. Open the deployed app and upload the attendance and grade files through the sidebar.

## Expected attendance structure

The app is designed around the supplied FSE10024 attendance workbook, but it does not hard-code `Sheet1`–`Sheet15` or specific dates.

Each usable sheet should contain:
- a row with the headings `Student Number` and `Student Name`;
- attendance entries represented by `P` and `A`.

Rows above the headings, week-number rows, metadata columns, blank spacer columns, and changing attendance dates are ignored automatically.

## Expected gradebook structure

The gradebook should contain:
- `Student`
- `SIS User ID`
- at least one score column.

The app prioritises these score columns when available:
1. `Unposted Final Score`
2. `Final Score`
3. `Unposted Current Score`
4. `Current Score`

For the supplied Canvas export, `Unposted Final Score` contains the useful calculated marks while `Final Score` is zero, so the app defaults to `Unposted Final Score`.

## Privacy

The code does not deliberately write uploaded source files to disk. Files are processed in memory for the active Streamlit session.

However, if the app is deployed to a cloud hosting provider, student data is processed in that hosting environment. Before using real student records on a hosted deployment, confirm that the deployment method is approved by your institution and complies with applicable privacy/data-handling requirements.

For the strongest control, run the app locally on an institution-managed computer or deploy it on institution-approved infrastructure.
