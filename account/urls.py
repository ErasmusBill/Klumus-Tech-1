from django.urls import path
from . import views

app_name = "account"

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register_school, name='register-school'),
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),
    path('initiate_package/<uuid:package_id>/', views.initiate_payment, name='initiate-package'),
    path('select-package/', views.select_package, name='select-package'),
    path('verify-payment/<uuid:school_id>/', views.verify_payment_view, name='verify-payment'),
    path('upgrade/<int:new_package_id>/', views.upgrade_package, name='upgrade-package'),
    path('downgrade/<int:new_package_id>/', views.downgrade_package, name='downgrade-package'),
    path('forgot-password/', views.request_for_password_reset, name='forgot-password'),
    path('change-password/', views.change_password, name='change-password'),
    path('notifications/<uuid:notification_id>/go/', views.notification_go, name='notification-go'),
    path('notifications/clear/', views.notifications_clear, name='notifications-clear'),
    path('notifications/', views.notifications_list, name='notifications-list'),
    path('notifications/<uuid:notification_id>/read/', views.notification_mark_read, name='notification-mark-read'),
    path('notifications/<uuid:notification_id>/unread/', views.notification_mark_unread, name='notification-mark-unread'),
    path('notifications/<uuid:notification_id>/delete/', views.notification_delete, name='notification-delete'),
    path('notifications/delete-all/', views.notifications_delete_all, name='notifications-delete-all'),
    
    path('reset-password/<str:token>/', views.verify_reset_token, name='verify-reset-token'),
]
