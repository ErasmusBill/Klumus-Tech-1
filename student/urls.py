from django.urls import path
from . import views

app_name = "student"

urlpatterns = [
    # Dashboard
    path("dashboard/", views.student_dashboard, name="student-dashboard"),
    path("results/<uuid:student_id>/", views.view_result, name="view-result"),
    path("courses/", views.student_enrolled_courses, name="enrolled-courses"),
    # path("change-class/", views.student_change_class, name="change-class"),
    path("fees/<uuid:student_id>/", views.list_fees_related, name="fees-list"),
]