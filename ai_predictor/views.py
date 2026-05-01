from pathlib import Path

import joblib
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from account.cache_utils import make_cache_key, should_cache
from account.models import ResultSheet, Student
from ai_predictor.feature_engineering import (
    build_feature_vector,
    calculate_student_features,
    heuristic_prediction,
    normalize_grade,
    risk_from_grade,
)
from ai_predictor.models import PredictedPerformance


MODEL_PATH = Path(__file__).resolve().parent / "performance_model.pkl"
LEGACY_GRADE_MAP_REVERSE = {5: "A", 4: "B", 3: "C", 2: "D", 1: "F"}
_model = None


def _get_user_school(user):
    if user.role == "admin":
        return getattr(user, "managed_school", None)
    if user.role == "teacher":
        teacher = getattr(user, "teacher_profile", None)
        return teacher.school if teacher else None
    if user.role == "student":
        student = getattr(user, "student_profile", None)
        return student.school if student else None
    return None


def _coerce_model_grade(raw_prediction) -> str:
    if raw_prediction is None:
        return "F"

    try:
        numeric_prediction = int(float(raw_prediction))
    except (TypeError, ValueError):
        numeric_prediction = None

    if numeric_prediction in LEGACY_GRADE_MAP_REVERSE:
        return LEGACY_GRADE_MAP_REVERSE[numeric_prediction]
    return normalize_grade(str(raw_prediction))


def get_model():
    global _model
    if _model is None and MODEL_PATH.exists():
        _model = joblib.load(MODEL_PATH)
    return _model


@login_required
def predict_student_performance(request, student_id):
    if request.user.role not in {"admin", "teacher", "student"}:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    school = _get_user_school(request.user)
    if not school:
        return JsonResponse({"error": "Profile not configured for school access"}, status=403)

    student = get_object_or_404(Student, student_id=student_id, school=school)
    if request.user.role == "student" and request.user.student_profile.id != student.id:
        return JsonResponse({"error": "You can only view your own prediction."}, status=403)

    cache_key = make_cache_key("ai_predictions", school.id, f"predict:{student_id}:{request.user.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    has_results = ResultSheet.objects.filter(student=student).exists()
    if not has_results:
        return JsonResponse({"error": "No result found for this student."}, status=404)

    features_dict = calculate_student_features(student, school=school)
    feature_vector = [build_feature_vector(features_dict)]

    model_source = "model"
    try:
        model = get_model()
        if model is None:
            raise RuntimeError("Model file not found")
        raw_prediction = model.predict(feature_vector)[0]
        predicted_grade = _coerce_model_grade(raw_prediction)
        risk = risk_from_grade(predicted_grade)
    except Exception:
        predicted_grade, risk = heuristic_prediction(features_dict)
        model_source = "heuristic"

    PredictedPerformance.objects.update_or_create(
        student=student,
        defaults={
            "predicted_grade": predicted_grade,
            "risk_level": risk,
        },
    )

    payload = {
        "student": student.user.get_full_name(),
        "student_id": student.student_id,
        "predicted_grade": predicted_grade,
        "risk_level": risk,
        "model_source": model_source,
        "message": f"{student.user.get_full_name()} ({student.student_id}) is at {risk} risk of underperforming.",
    }
    response = JsonResponse(payload)
    if should_cache(request):
        cache.set(cache_key, response, 120)
    return response


@login_required
def dashboard(request):
    if request.user.role not in {"admin", "teacher", "student"}:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    school = _get_user_school(request.user)
    if not school:
        return JsonResponse({"error": "Profile not configured for school access"}, status=403)

    cache_key = make_cache_key("ai_predictions", school.id, f"dashboard:{request.user.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    data = PredictedPerformance.objects.select_related("student", "student__user").filter(student__school=school)
    if request.user.role == "student":
        data = data.filter(student=request.user.student_profile)

    risk_summary = data.values("risk_level").annotate(count=Count("id"))

    response = render(
        request,
        "ai_predictor/dashboard.html",
        {
            "data": data,
            "risk_summary": risk_summary,
        },
    )
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response
