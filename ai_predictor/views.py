import numpy as np
import joblib
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from account.models import Student, ResultSheet  # Make sure ResultSheet is imported
from .models import PredictedPerformance
from django.db.models import Count
from django.shortcuts import render
from .models import PredictedPerformance

# Load trained model
model = joblib.load("ai_predictor/performance_model.pkl")

def predict_student_performance(request, student_id):
    """
    Predict a student's performance using their features.
    student_id refers to Student.student_id (e.g., STU-NXSANR)
    """
    student = get_object_or_404(Student, student_id=student_id)
    result = ResultSheet.objects.filter(student=student).last()

    if not result:
        return JsonResponse({"error": "No result found for this student."}, status=404)

    # Features must match training order
    features = np.array([[student.attendance_percentage,
                          result.average_score,
                          student.discipline_points,
                          student.homework_completion]])

    # Predict grade
    prediction = model.predict(features)[0]
    grade_map_reverse = {5: "A", 4: "B", 3: "C", 2: "D", 1: "E"}
    predicted_grade = grade_map_reverse.get(prediction, "N/A")

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