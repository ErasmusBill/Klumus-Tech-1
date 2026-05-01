from __future__ import annotations

from typing import Mapping

from django.db.models import Avg
from django.utils import timezone

from account.models import Attendance, Assignment, AssignmentSubmission, ResultSheet

FEATURE_COLUMNS = ("attendance", "average_score", "discipline", "homework")

# Coarse grade bands used by the AI predictor (kept consistent between training and inference).
GRADE_BANDS = (
    (80, "A"),
    (70, "B"),
    (60, "C"),
    (50, "D"),
)

GRADE_TO_RISK = {
    "A": "Low",
    "B": "Low",
    "C": "Medium",
    "D": "High",
    "F": "High",
}


def grade_from_percentage(percentage: float) -> str:
    for threshold, grade in GRADE_BANDS:
        if percentage >= threshold:
            return grade
    return "F"


def normalize_grade(raw_grade: str | None, percentage: float | None = None) -> str:
    normalized = (raw_grade or "").strip().upper()

    if normalized in {"A+", "A", "A-"}:
        return "A"
    if normalized in {"B+", "B", "B-"}:
        return "B"
    if normalized in {"C+", "C", "C-"}:
        return "C"
    if normalized in {"D+", "D"}:
        return "D"
    if normalized in {"E", "F"}:
        return "F"

    if percentage is not None:
        return grade_from_percentage(float(percentage))
    return "F"


def risk_from_grade(grade: str) -> str:
    normalized = normalize_grade(grade)
    return GRADE_TO_RISK.get(normalized, "Low")


def _attendance_metrics(student, lookback_days: int = 30) -> tuple[float, float]:
    since = timezone.now().date() - timezone.timedelta(days=lookback_days)
    attendance_qs = Attendance.objects.filter(student=student, date__gte=since)

    total_attendance = attendance_qs.count()
    if total_attendance == 0:
        return 0.0, 100.0

    present_attendance = attendance_qs.filter(status="present").count()
    attendance_percentage = (present_attendance / total_attendance) * 100

    # Penalty-based discipline score (0-100).
    penalty_weights = {"absent": 10, "late": 5, "excused": 3, "sick": 2}
    penalties = 0
    for status, weight in penalty_weights.items():
        penalties += attendance_qs.filter(status=status).count() * weight

    discipline_score = max(0.0, 100.0 - penalties)
    return attendance_percentage, discipline_score


def _homework_completion(student, school) -> float:
    assignments_count = Assignment.objects.filter(
        student_class=student.student_class,
        subject__school=school,
    ).count()
    if assignments_count == 0:
        return 0.0

    submissions_count = AssignmentSubmission.objects.filter(
        student=student,
        assignment__subject__school=school,
    ).count()
    return (submissions_count / assignments_count) * 100


def latest_result_for_student(student):
    return (
        ResultSheet.objects
        .filter(student=student)
        .order_by("-exam_date", "-created_at")
        .first()
    )


def calculate_student_features(student, school, lookback_days: int = 30) -> dict[str, float]:
    avg_percentage = ResultSheet.objects.filter(student=student).aggregate(avg=Avg("percentage"))["avg"] or 0
    average_score = float(avg_percentage)
    attendance_percentage, discipline_score = _attendance_metrics(student, lookback_days=lookback_days)
    homework_completion = _homework_completion(student, school)

    return {
        "attendance": float(attendance_percentage),
        "average_score": average_score,
        "discipline": float(discipline_score),
        "homework": float(homework_completion),
    }


def build_feature_vector(features: Mapping[str, float]) -> list[float]:
    return [float(features.get(column, 0.0)) for column in FEATURE_COLUMNS]


def heuristic_prediction(features: Mapping[str, float]) -> tuple[str, str]:
    # Weighted academic signal fallback when the model is unavailable.
    attendance = float(features.get("attendance", 0.0))
    average_score = float(features.get("average_score", 0.0))
    discipline = float(features.get("discipline", 0.0))
    homework = float(features.get("homework", 0.0))

    composite_score = (0.55 * average_score) + (0.20 * attendance) + (0.15 * homework) + (0.10 * discipline)
    predicted_grade = grade_from_percentage(composite_score)
    return predicted_grade, risk_from_grade(predicted_grade)
