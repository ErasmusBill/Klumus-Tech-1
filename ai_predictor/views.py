import numpy as np
import joblib
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from account.models import Student, ResultSheet, Attendance, Assignment, AssignmentSubmission
from .models import PredictedPerformance
from django.db.models import Count
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

# Lazy load model to prevent startup crashes
_model = None

def get_model():
    global _model
    if _model is None:
        _model = joblib.load("ai_predictor/performance_model.pkl")
    return _model

@login_required
def predict_student_performance(request, student_id):
    """
    Predict a student's performance using their features.
    student_id refers to Student.student_id (e.g., STU-NXSANR)
    """
    student = get_object_or_404(Student, student_id=student_id)
    result = ResultSheet.objects.filter(student=student).last()

    if not result:
        return JsonResponse({"error": "No result found for this student."}, status=404)

    # Attendance percentage (last 30 days if available)
    since = timezone.now().date() - timezone.timedelta(days=30)
    attendance_qs = Attendance.objects.filter(student=student, date__gte=since)
    total_att = attendance_qs.count()
    present_att = attendance_qs.filter(status="present").count()
    attendance_percentage = (present_att / total_att * 100) if total_att else 0

    # Average score proxy from latest result
    if result.percentage:
        average_score = float(result.percentage)
    else:
        result.calculate_total()
        average_score = float(result.total_marks or 0)

    # Homework completion proxy (submissions / assignments for class)
    assignments_count = Assignment.objects.filter(student_class=student.student_class).count()
    submissions_count = AssignmentSubmission.objects.filter(student=student).count()
    homework_completion = (submissions_count / assignments_count * 100) if assignments_count else 0

    # Discipline points not modeled; default to 0
    discipline_points = 0

    # Features must match training order
    features = np.array([[attendance_percentage,
                          average_score,
                          discipline_points,
                          homework_completion]])

    # Predict grade - use lazy loaded model
    try:
        model = get_model()
        prediction = model.predict(features)[0]
    except Exception as exc:
        return JsonResponse({"error": f"Model error: {exc}"}, status=500)

    grade_map_reverse = {5: "A", 4: "B", 3: "C", 2: "D", 1: "E"}
    if isinstance(prediction, (int, float, np.integer, np.floating)):
        predicted_grade = grade_map_reverse.get(int(prediction), "N/A")
    else:
        predicted_grade = str(prediction)

    # Risk logic
    if predicted_grade in ["D", "E"]:
        risk = "High"
    elif predicted_grade == "C":
        risk = "Medium"
    else:
        risk = "Low"

    # Save to PredictedPerformance model
    PredictedPerformance.objects.update_or_create(
        student=student,
        defaults={
            "predicted_grade": predicted_grade,
            "risk_level": risk,
        }
    )

    return JsonResponse({
        "student": student.user.get_full_name(),
        "student_id": student.student_id,
        "predicted_grade": predicted_grade,
        "risk_level": risk,
        "message": f"{student.user.get_full_name()} ({student.student_id}) is at {risk} risk of underperforming."
    })

@login_required
def dashboard(request):
    """
    Show AI prediction summary and risk analysis.
    """
    data = PredictedPerformance.objects.select_related("student", "student__user").all()

    # Count students by risk level
    risk_summary = (
        PredictedPerformance.objects
        .values("risk_level")
        .annotate(count=Count("id"))
    )

    return render(request, "ai_predictor/dashboard.html", {
        "data": data,
        "risk_summary": risk_summary,
    })
