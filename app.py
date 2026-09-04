import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(
    page_title="Student Attendance & Performance Dashboard",
    page_icon="🎓",
    layout="wide",
)

st.title("🎓 Student Attendance & Performance Dashboard")
st.caption(
    "Upload an attendance workbook and a Canvas gradebook export. "
    "The app cleans, combines, matches, analyses, and visualises the data automatically."
)


# ----------------------------
# Helpers
# ----------------------------

def clean_student_number(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    text = re.sub(r"\s+", "", text)
    return text or None


def clean_text(value):
    if pd.isna(value):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def make_unique_headers(values):
    seen = {}
    result = []
    for i, value in enumerate(values):
        if pd.isna(value) or str(value).strip() == "":
            base = f"Unnamed_{i+1}"
        else:
            base = str(value).strip()
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.append(base if count == 0 else f"{base}_{count+1}")
    return result


def find_attendance_header(raw):
    max_rows = min(len(raw), 25)
    for idx in range(max_rows):
        vals = [str(v).strip().lower() for v in raw.iloc[idx].tolist() if pd.notna(v)]
        if "student number" in vals and "student name" in vals:
            return idx
    return None


@st.cache_data(show_spinner=False)
def parse_attendance(file_bytes):
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    records = []
    sheet_stats = []
    skipped = []

    for sheet in xls.sheet_names:
        raw = pd.read_excel(xls, sheet_name=sheet, header=None)
        header_row = find_attendance_header(raw)

        if header_row is None:
            skipped.append(sheet)
            continue

        headers = make_unique_headers(raw.iloc[header_row].tolist())
        df = raw.iloc[header_row + 1 :].copy()
        df.columns = headers

        if "Student Number" not in df.columns or "Student Name" not in df.columns:
            skipped.append(sheet)
            continue

        df["Student Number"] = df["Student Number"].map(clean_student_number)
        df["Student Name"] = df["Student Name"].map(clean_text)
        df = df[df["Student Number"].notna()].copy()

        id_cols = ["Student Number", "Student Name"]
        long_df = df.melt(
            id_vars=id_cols,
            value_vars=[c for c in df.columns if c not in id_cols],
            var_name="Class Date",
            value_name="Attendance",
        )

        long_df["Attendance"] = (
            long_df["Attendance"]
            .astype(str)
            .str.strip()
            .str.upper()
        )

        # Robustly ignores metadata columns and blank spacer columns:
        # only genuine P/A records survive.
        long_df = long_df[long_df["Attendance"].isin(["P", "A"])].copy()
        long_df["Tutorial Sheet"] = sheet

        # Clean the displayed class-date heading.
        long_df["Class Date"] = long_df["Class Date"].astype(str).str.strip()

        records.append(
            long_df[
                ["Tutorial Sheet", "Student Number", "Student Name", "Class Date", "Attendance"]
            ]
        )
        sheet_stats.append(
            {
                "Sheet": sheet,
                "Students with attendance": int(long_df["Student Number"].nunique()),
                "Attendance records": int(len(long_df)),
            }
        )

    if not records:
        return pd.DataFrame(), pd.DataFrame(), skipped, 0, 0

    attendance = pd.concat(records, ignore_index=True)

    # Detect duplicate student/date records before deduplication.
    dup_mask = attendance.duplicated(
        subset=["Student Number", "Class Date"], keep=False
    )
    duplicate_records = int(dup_mask.sum())

    # Detect conflicting P/A entries for the same student and class-date.
    conflict_count = (
        attendance.groupby(["Student Number", "Class Date"])["Attendance"]
        .nunique()
        .gt(1)
        .sum()
    )

    # Avoid double-counting the same student on the same class date.
    attendance = attendance.drop_duplicates(
        subset=["Student Number", "Class Date"], keep="first"
    ).copy()

    return (
        attendance,
        pd.DataFrame(sheet_stats),
        skipped,
        duplicate_records,
        int(conflict_count),
    )


def find_grade_header(raw):
    max_rows = min(len(raw), 25)
    for idx in range(max_rows):
        vals = [str(v).strip() for v in raw.iloc[idx].tolist() if pd.notna(v)]
        if "SIS User ID" in vals and "Student" in vals:
            return idx
    return None


@st.cache_data(show_spinner=False)
def read_grade_file(file_bytes, filename):
    suffix = Path(filename).suffix.lower()

    if suffix == ".csv":
        # First try normal Canvas CSV structure.
        df = pd.read_csv(io.BytesIO(file_bytes))
        if "SIS User ID" in df.columns and "Student" in df.columns:
            return df

        raw = pd.read_csv(io.BytesIO(file_bytes), header=None)
    else:
        # Try the first sheet. If headers are not in row 1, detect them.
        first = pd.read_excel(io.BytesIO(file_bytes))
        if "SIS User ID" in first.columns and "Student" in first.columns:
            return first
        raw = pd.read_excel(io.BytesIO(file_bytes), header=None)

    header_row = find_grade_header(raw)
    if header_row is None:
        raise ValueError(
            "Could not locate gradebook headers. Expected columns including "
            "'Student' and 'SIS User ID'."
        )

    headers = make_unique_headers(raw.iloc[header_row].tolist())
    df = raw.iloc[header_row + 1 :].copy()
    df.columns = headers
    return df


def candidate_grade_columns(df):
    preferred = [
        "Unposted Final Score",
        "Final Score",
        "Unposted Current Score",
        "Current Score",
    ]
    found = [c for c in preferred if c in df.columns]

    score_like = [
        c
        for c in df.columns
        if c not in found
        and isinstance(c, str)
        and any(k in c.lower() for k in ["score", "grade", "total"])
    ]
    return found + score_like


def prepare_grades(df, grade_column):
    required = ["Student", "SIS User ID", grade_column]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Missing required grade columns: " + ", ".join(missing))

    grades = df[required].copy()
    grades = grades.rename(
        columns={
            "Student": "Grade Student Name",
            "SIS User ID": "Student Number",
            grade_column: "Grade",
        }
    )

    grades["Student Number"] = grades["Student Number"].map(clean_student_number)
    grades["Grade Student Name"] = grades["Grade Student Name"].map(clean_text)
    grades["Grade"] = pd.to_numeric(grades["Grade"], errors="coerce")

    # Removes Canvas rows such as Points Possible / Manual Posting because they
    # do not have a usable SIS User ID and numeric grade.
    grades = grades[
        grades["Student Number"].notna() & grades["Grade"].notna()
    ].copy()

    duplicate_grade_rows = int(
        grades.duplicated(subset=["Student Number"], keep=False).sum()
    )

    # One grade per student. Canvas normally has one row; keep the final
    # occurrence if duplicate rows exist.
    grades = grades.drop_duplicates(subset=["Student Number"], keep="last")

    return grades, duplicate_grade_rows


def build_attendance_summary(attendance):
    if attendance.empty:
        return pd.DataFrame()

    attendance = attendance.copy()
    attendance["Present"] = (attendance["Attendance"] == "P").astype(int)
    attendance["Absent"] = (attendance["Attendance"] == "A").astype(int)

    def first_name(series):
        vals = [clean_text(v) for v in series if clean_text(v)]
        return vals[0] if vals else None

    def tutorial_list(series):
        values = list(dict.fromkeys(str(v) for v in series if pd.notna(v)))
        return ", ".join(values)

    summary = (
        attendance.groupby("Student Number", as_index=False)
        .agg(
            **{
                "Student Name": ("Student Name", first_name),
                "Tutorial Sheet": ("Tutorial Sheet", tutorial_list),
                "Present": ("Present", "sum"),
                "Absent": ("Absent", "sum"),
                "Classes Recorded": ("Attendance", "size"),
            }
        )
    )
    summary["Attendance %"] = (
        summary["Present"] / summary["Classes Recorded"] * 100
    )
    return summary


def classify_students(
    summary,
    high_attendance,
    medium_attendance,
    excellent_grade,
    good_grade,
    satisfactory_grade,
    attendance_alert,
    grade_alert,
):
    result = summary.copy()

    result["Participation"] = np.select(
        [
            result["Attendance %"].ge(high_attendance),
            result["Attendance %"].ge(medium_attendance),
        ],
        ["High", "Medium"],
        default="Low",
    )

    result["Performance"] = np.select(
        [
            result["Grade"].ge(excellent_grade),
            result["Grade"].ge(good_grade),
            result["Grade"].ge(satisfactory_grade),
        ],
        ["Excellent", "Good", "Satisfactory"],
        default="At Risk",
    )

    def reason(row):
        att_missing = pd.isna(row.get("Attendance %"))
        grade_missing = pd.isna(row.get("Grade"))

        if att_missing and grade_missing:
            return "Missing attendance & grade"
        if att_missing:
            return "Missing attendance"
        if grade_missing:
            return "Missing grade"

        low_att = row["Attendance %"] < attendance_alert
        low_grade = row["Grade"] < grade_alert
        if low_att and low_grade:
            return "Low attendance & grade"
        if low_att:
            return "Low attendance"
        if low_grade:
            return "Low grade"
        return "OK"

    result["Alert Reason"] = result.apply(reason, axis=1)
    result["Alert"] = np.where(result["Alert Reason"].eq("OK"), "OK", "Needs Attention")
    return result


def make_excel_download(student_summary, attendance_detail, sheet_stats):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        student_summary.to_excel(writer, index=False, sheet_name="Student Summary")
        attendance_detail.to_excel(writer, index=False, sheet_name="Attendance Detail")
        sheet_stats.to_excel(writer, index=False, sheet_name="Sheet Quality")
    output.seek(0)
    return output.getvalue()


# ----------------------------
# Uploads
# ----------------------------

st.sidebar.header("1. Upload files")
attendance_file = st.sidebar.file_uploader(
    "Attendance workbook",
    type=["xlsx", "xlsm"],
    help="Workbook containing tutorial/class sheets with Student Number, Student Name, and P/A attendance entries.",
)

grades_file = st.sidebar.file_uploader(
    "Gradebook export",
    type=["csv", "xlsx"],
    help="Canvas-style gradebook containing Student, SIS User ID, and score columns.",
)

st.sidebar.divider()
st.sidebar.header("2. Thresholds")

high_attendance = st.sidebar.number_input(
    "High participation ≥ (%)", min_value=0.0, max_value=100.0, value=80.0, step=1.0
)
medium_attendance = st.sidebar.number_input(
    "Medium participation ≥ (%)", min_value=0.0, max_value=100.0, value=60.0, step=1.0
)
attendance_alert = st.sidebar.number_input(
    "Attendance alert below (%)", min_value=0.0, max_value=100.0, value=60.0, step=1.0
)

excellent_grade = st.sidebar.number_input(
    "Excellent grade ≥", min_value=0.0, max_value=100.0, value=80.0, step=1.0
)
good_grade = st.sidebar.number_input(
    "Good grade ≥", min_value=0.0, max_value=100.0, value=70.0, step=1.0
)
satisfactory_grade = st.sidebar.number_input(
    "Satisfactory grade ≥", min_value=0.0, max_value=100.0, value=50.0, step=1.0
)
grade_alert = st.sidebar.number_input(
    "Grade alert below", min_value=0.0, max_value=100.0, value=50.0, step=1.0
)

with st.sidebar.expander("Privacy"):
    st.write(
        "This app code does not save uploaded files. When deployed to a cloud "
        "service, uploaded student data is processed by that hosting environment. "
        "Use only a deployment approved by your institution for student records."
    )


if not attendance_file or not grades_file:
    st.info(
        "Upload both files in the sidebar to generate the dashboard. "
        "Nothing needs to be renamed before upload."
    )
    st.stop()


# ----------------------------
# Parse and prepare
# ----------------------------

try:
    with st.spinner("Reading attendance workbook..."):
        (
            attendance_detail,
            sheet_stats,
            skipped_sheets,
            duplicate_attendance_records,
            conflicting_attendance_records,
        ) = parse_attendance(attendance_file.getvalue())

    if attendance_detail.empty:
        st.error(
            "No P/A attendance records were found. Check that the workbook contains "
            "Student Number, Student Name, and attendance values P or A."
        )
        st.stop()

    with st.spinner("Reading gradebook..."):
        raw_grades = read_grade_file(grades_file.getvalue(), grades_file.name)

    grade_options = candidate_grade_columns(raw_grades)
    if not grade_options:
        st.error(
            "I found the gradebook, but could not identify a score column. "
            "Expected a column such as Unposted Final Score, Final Score, "
            "Unposted Current Score, or Current Score."
        )
        st.stop()

except Exception as exc:
    st.exception(exc)
    st.stop()


st.sidebar.divider()
st.sidebar.header("3. Grade source")
default_idx = (
    grade_options.index("Unposted Final Score")
    if "Unposted Final Score" in grade_options
    else 0
)
grade_column = st.sidebar.selectbox(
    "Grade column",
    grade_options,
    index=default_idx,
    help="For the sample Canvas export, Unposted Final Score contains the useful calculated grade.",
)

try:
    grades, duplicate_grade_rows = prepare_grades(raw_grades, grade_column)
except Exception as exc:
    st.exception(exc)
    st.stop()

attendance_summary = build_attendance_summary(attendance_detail)

# Outer merge means students present in only one source are still visible and flagged.
student_summary = attendance_summary.merge(
    grades,
    on="Student Number",
    how="outer",
)

# Prefer attendance name; fall back to gradebook name.
if "Student Name" not in student_summary:
    student_summary["Student Name"] = student_summary["Grade Student Name"]
else:
    student_summary["Student Name"] = student_summary["Student Name"].fillna(
        student_summary["Grade Student Name"]
    )

student_summary = classify_students(
    student_summary,
    high_attendance,
    medium_attendance,
    excellent_grade,
    good_grade,
    satisfactory_grade,
    attendance_alert,
    grade_alert,
)

student_summary = student_summary[
    [
        "Student Number",
        "Student Name",
        "Tutorial Sheet",
        "Present",
        "Absent",
        "Classes Recorded",
        "Attendance %",
        "Grade",
        "Participation",
        "Performance",
        "Alert",
        "Alert Reason",
    ]
].sort_values(["Alert", "Student Name"], ascending=[True, True], na_position="last")


# ----------------------------
# Dashboard
# ----------------------------

unique_students = int(student_summary["Student Number"].nunique())
avg_attendance = student_summary["Attendance %"].mean()
avg_grade = student_summary["Grade"].mean()
needs_attention = int(student_summary["Alert"].eq("Needs Attention").sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total students", f"{unique_students:,}")
c2.metric(
    "Average attendance",
    "—" if pd.isna(avg_attendance) else f"{avg_attendance:.1f}%",
)
c3.metric(
    "Average grade",
    "—" if pd.isna(avg_grade) else f"{avg_grade:.1f}",
)
c4.metric("Needs attention", f"{needs_attention:,}")

st.divider()

left, right = st.columns(2)

with left:
    participation_order = ["High", "Medium", "Low"]
    participation = (
        student_summary["Participation"]
        .value_counts()
        .reindex(participation_order, fill_value=0)
        .rename_axis("Participation")
        .reset_index(name="Students")
    )
    fig_part = px.pie(
        participation,
        names="Participation",
        values="Students",
        hole=0.55,
        title="Student Participation",
    )
    fig_part.update_traces(textposition="inside", textinfo="label+value+percent")
    fig_part.update_layout(legend_title_text="")
    st.plotly_chart(fig_part, use_container_width=True)

with right:
    performance_order = ["Excellent", "Good", "Satisfactory", "At Risk"]
    performance = (
        student_summary["Performance"]
        .value_counts()
        .reindex(performance_order, fill_value=0)
        .rename_axis("Performance")
        .reset_index(name="Students")
    )
    fig_perf = px.bar(
        performance,
        x="Performance",
        y="Students",
        text="Students",
        title="Student Performance",
    )
    fig_perf.update_traces(textposition="outside", cliponaxis=False)
    fig_perf.update_layout(xaxis_title="", yaxis_title="Students")
    st.plotly_chart(fig_perf, use_container_width=True)

scatter_data = student_summary.dropna(subset=["Attendance %", "Grade"]).copy()
fig_scatter = px.scatter(
    scatter_data,
    x="Attendance %",
    y="Grade",
    hover_name="Student Name",
    hover_data={
        "Student Number": True,
        "Participation": True,
        "Performance": True,
        "Alert Reason": True,
    },
    title="Attendance vs Grade",
)
fig_scatter.add_vline(
    x=attendance_alert,
    line_dash="dash",
    annotation_text=f"Attendance alert {attendance_alert:.0f}%",
)
fig_scatter.add_hline(
    y=grade_alert,
    line_dash="dash",
    annotation_text=f"Grade alert {grade_alert:.0f}",
)
fig_scatter.update_xaxes(range=[0, 100], title="Attendance %")
fig_scatter.update_yaxes(range=[0, 100], title="Grade")
st.plotly_chart(fig_scatter, use_container_width=True)


# ----------------------------
# Alerts and searchable data
# ----------------------------

st.subheader("Students Needing Attention")
alert_data = student_summary[student_summary["Alert"].eq("Needs Attention")].copy()

reason_options = sorted(alert_data["Alert Reason"].dropna().unique().tolist())
selected_reasons = st.multiselect(
    "Filter alert reasons",
    reason_options,
    default=reason_options,
)

if selected_reasons:
    alert_view = alert_data[alert_data["Alert Reason"].isin(selected_reasons)]
else:
    alert_view = alert_data.iloc[0:0]

st.dataframe(
    alert_view[
        [
            "Student Number",
            "Student Name",
            "Tutorial Sheet",
            "Attendance %",
            "Grade",
            "Alert Reason",
        ]
    ],
    use_container_width=True,
    hide_index=True,
    column_config={
        "Attendance %": st.column_config.NumberColumn(format="%.1f%%"),
        "Grade": st.column_config.NumberColumn(format="%.2f"),
    },
)

with st.expander("All students"):
    search = st.text_input("Search name or student number")
    all_view = student_summary.copy()
    if search:
        mask = (
            all_view["Student Name"].fillna("").str.contains(search, case=False, regex=False)
            | all_view["Student Number"].fillna("").str.contains(search, case=False, regex=False)
        )
        all_view = all_view[mask]

    st.dataframe(
        all_view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Attendance %": st.column_config.NumberColumn(format="%.1f%%"),
            "Grade": st.column_config.NumberColumn(format="%.2f"),
        },
    )


# ----------------------------
# Data quality
# ----------------------------

with st.expander("Data quality checks"):
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Attendance sheets read", len(sheet_stats))
    q2.metric("Skipped sheets", len(skipped_sheets))
    q3.metric("Duplicate attendance rows", duplicate_attendance_records)
    q4.metric("Conflicting P/A records", conflicting_attendance_records)

    if skipped_sheets:
        st.warning("Skipped sheets: " + ", ".join(skipped_sheets))

    missing_grade = int(student_summary["Grade"].isna().sum())
    missing_attendance = int(student_summary["Attendance %"].isna().sum())
    st.write(
        f"Students missing a grade: **{missing_grade}** · "
        f"Students missing attendance: **{missing_attendance}** · "
        f"Duplicate grade rows detected before deduplication: **{duplicate_grade_rows}**"
    )

    if not sheet_stats.empty:
        st.dataframe(sheet_stats, use_container_width=True, hide_index=True)


# ----------------------------
# Downloads
# ----------------------------

st.subheader("Download")
excel_bytes = make_excel_download(student_summary, attendance_detail, sheet_stats)

d1, d2 = st.columns(2)
d1.download_button(
    "⬇️ Download analysed Excel workbook",
    data=excel_bytes,
    file_name="student_dashboard_results.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
d2.download_button(
    "⬇️ Download student summary CSV",
    data=student_summary.to_csv(index=False).encode("utf-8-sig"),
    file_name="student_summary.csv",
    mime="text/csv",
    use_container_width=True,
)

st.caption(
    "Tip: only the app code belongs in GitHub. Do not commit real student "
    "attendance or grade files to a public repository."
)
