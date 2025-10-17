from django.urls import path
from . import views

app_name = 'teacher'

urlpatterns = [
    path('dashboard/', views.teacher_dashboard, name='teacher-dashboard'),
    path('my-subjects/', views.my_subjects, name='my-subjects'),
    
    # Student management URLs
    path('students/', views.teacher_students, name='teacher-students'),
    path('students/subject/<uuid:subject_id>/', views.teacher_students_by_subject, name='teacher-students-by-subject'),
     path("results/<uuid:student_id>/", views.view_result, name="view-result"),
    
    # Results management
    path('bulk-grades/<uuid:subject_id>/', views.enter_bulk_grades, name='enter-bulk-grades'),
    path('edit-result/<uuid:result_id>/', views.edit_result, name='edit-result'),
    path('list-result/', views.list_result, name='list-result'),
    path('delete-result/<uuid:result_id>/', views.delete_result, name='delete-result'),

    # Attendance management
    path('mark-attendance/', views.mark_attendance, name='mark-attendance'),
    path('attendance-update/<uuid:attendance_id>/', views.attendance_update, name='attendance-update'),
    path('attendance-delete/<uuid:attendance_id>/', views.attendance_delete, name='attendance-delete'),
    path('attendance-list/', views.attendance_list, name='attendance-list'),
    
    # Assignment management
    path('add-assignment/', views.add_assignment, name='add-assignment'),
    path('edit-assignment/<uuid:assignment_id>/', views.edit_assignment, name='edit-assignment'),
    path('assignment-list/', views.list_assignment, name='assignment-list'),
    path('delete-assignment/<uuid:assignment_id>/', views.delete_assignment, name='delete-assignment'),
    
    path('assignment/<uuid:assignment_id>/submissions/', views.view_assignment_submissions, name='assignment-submissions'),
    path('submission/<uuid:submission_id>/download/', views.download_submission_file, name='download-submission'),
    path('submission/<uuid:submission_id>/grade/', views.grade_assignment, name='grade-assignment'),
    path('assignment/<uuid:assignment_id>/bulk-download/', views.bulk_download_submissions, name='bulk-download-submissions'),
]