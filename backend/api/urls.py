from django.urls import path
from . import views

urlpatterns = [
    path('study_coaching_hub', views.study_coaching_hub, name='study_coaching_hub'),
    path('sessions/', views.session_list_create, name='session_list_create'),
    path('sessions/<uuid:id>/history/', views.session_history, name='session_history'),
    path('sessions/<uuid:id>/message/', views.session_message, name='session_message'),
]

