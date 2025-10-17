from django.urls import path
from .views import predict_student_performance,dashboard

app_name = "ai_predictor"


urlpatterns = [   
    path('predict/<uuid:student_id>/', predict_student_performance, name='predict_student_performance'),
    path('dashboard/', dashboard, name='ai_dashboard'),
]