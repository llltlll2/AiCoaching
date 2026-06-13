from django.urls import path
from . import views

urlpatterns = [
    path('study_coaching_hub', views.study_coaching_hub, name='study_coaching_hub'),
]
