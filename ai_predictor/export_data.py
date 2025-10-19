import pandas as pd
from account.models import ResultSheet

def export_training_data():
    data = []
    for result in ResultSheet.objects.select_related("student"):
        total = (result.class_score or 0) + (result.mid_semester or 0) + (result.end_of_term_exams or 0)

        # Assign a letter grade automatically
        if total >= 80:
            grade = "A"
        elif total >= 70:
            grade = "B"
        elif total >= 60:
            grade = "C"
        elif total >= 50:
            grade = "D"
        else:
            grade = "E"

        data.append({
            "student_id": result.student.id,
            "student_name": result.student.user.get_full_name(),
            "attendance": 90,     
            "average_score": total / 3,
            "discipline": 4,      # placeholder
            "homework": 3,        # placeholder
            "final_grade": grade,
        })

    df = pd.DataFrame(data)
    df.to_csv("training_data.csv", index=False)
    print("✅ Training data exported to training_data.csv")
