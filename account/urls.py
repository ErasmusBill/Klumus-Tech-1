from django.urls import path
from . import views

app_name = "account"

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register_school, name='register-school'),
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),
    path('initiate_package/', views.initiate_payment, name='initiate-package'),
    path('select-package/', views.select_package, name='select-package'),
    path('verify-payment/<int:school_id>/', views.verify_payment_view, name='verify-payment'),
    path('upgrade/<int:new_package_id>/', views.upgrade_package, name='upgrade-package'),
    path('downgrade/<int:new_package_id>/', views.downgrade_package, name='downgrade-package'),
    path('forgot-password/', views.request_for_password_reset, name='forgot-password'),
    path('change-password/', views.change_password, name='change-password'),
    
    path('reset-password/<str:token>/', views.verify_reset_token, name='verify-reset-token'),
]