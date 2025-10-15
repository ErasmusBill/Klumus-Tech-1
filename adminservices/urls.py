from django.urls import path
from . import views



app_name="adminservices"

urlpatterns = [
    path('admin-dashboard',views.admin_dashboard,name='admin-dashboard'),
    path("add-teacher",views.add_teacher, name="add-teacher"),
    path("list-teachers",views.list_teachers, name="list-teachers"),
    path("add-department",views.add_department, name="add-department"),
    path("list-department",views.list_departments,name="list-departments"),
    path("delete-department/<uuid:department_id>",views.delete_department,name="delete-department"),
    path("edit-department/<uuid:department_id>",views.edit_department, name="edit-department"),
    path("delete-teacher/<uuid:teacher_id>",views.delete_teacher,name="delete-teacher"),
    path("edit-teacher/<uuid:teacher_id>",views.update_teacher, name="edit-teacher"),
    path("teacher-detail/<uuid:teacher_id>",views.teacher_detail, name="teacher-detail"),
    path("department-detail/<uuid:department_id>",views.department_detail, name="department-detail"),
    path("add-student",views.add_student,name="add-student"),
    path("list-student",views.list_students,name="list-students"),
    path("edit-student/<uuid:student_id>",views.edit_student,name="edit-student"),
    path("delete-student/<uuid:student_id>",views.delete_student,name="delete-student"),
    path("student-detail/<uuid:student_id>",views.student_detail,name='student-detail'),
    path('add-fees/', views.add_fees, name='add-fees'),
    path('list-fees/', views.list_fees, name='list-fees'),
    path('fees/<uuid:fee_id>/edit/', views.edit_fees, name='edit-fees'),
    path('fees/<uuid:fee_id>/delete/', views.delete_fees, name='delete-fees'),
    path('add-subject/', views.add_subject, name='add-subject'),
    path('list-subjects/', views.list_subjects, name='list-subjects'),
    path('edit-subject/<uuid:subject_id>',views.edit_subject, name='edit-subject'),
    path('subject-detial/<uuid:subject_id>',views.subject_detail, name='subject-detail'),
    path('delete-subject/<uuid:subject_id>',views.delete_subject, name='delete-subject'),
    
    path('announcements/', views.list_announcements, name='announcement_list'),
    path('announcements/new/', views.manage_announcement, name='announcement_create'),
    path('announcements/<uuid:pk>/edit/', views.manage_announcement, name='announcement_edit'),
]
