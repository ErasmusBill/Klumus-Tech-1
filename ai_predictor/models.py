from django.db import models
from account.models import Student

class PredictedPerformance(models.Model):
    RISK_CHOICES = [
        ("High", "High Risk"),
        ("Medium", "Medium Risk"),
        ("Low", "Low Risk"),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    predicted_grade = models.CharField(max_length=2)
    risk_level = models.CharField(max_length=10, choices=RISK_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.user.first_name} - {self.predicted_grade} ({self.risk_level})"
