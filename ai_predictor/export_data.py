from pathlib import Path

import pandas as pd

from account.models import Student
from ai_predictor.feature_engineering import (
    calculate_student_features,
    latest_result_for_student,
    normalize_grade,
)


def export_training_data():
    base_dir = Path(__file__).resolve().parent.parent
    output_path = base_dir / "training_data.csv"

    data = []
    students = Student.objects.select_related("user", "school")
    for student in students:
        result = latest_result_for_student(student)
        if not result:
            continue

        features = calculate_student_features(student, school=student.school)
        final_grade = normalize_grade(result.grade, float(result.percentage or 0))
        data.append(
            {
                "student_id": student.student_id,
                "student_name": student.user.get_full_name(),
                "attendance": features["attendance"],
                "average_score": features["average_score"],
                "discipline": features["discipline"],
                "homework": features["homework"],
                "final_grade": final_grade,
            }
        )

    df = pd.DataFrame(data)
    df.to_csv(output_path, index=False)
    print(f"Training data exported to {output_path}")
