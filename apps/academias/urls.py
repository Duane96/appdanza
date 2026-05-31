# apps/academias/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'academias'

urlpatterns = [
    # 🌍 La Landing pública de la academia: web.com/duane-y-aleja/
    path('<slug:slug_academia>/', views.LandingAcademiaView.as_view(), name='index'),
    
    # 🔑 El Login personalizado: web.com/duane-y-aleja/login/
    path('<slug:slug_academia>/login/', views.LoginAcademiaView.as_view(), name='login'),
    path('<slug:slug_academia>/logout/', views.LogoutAcademiaView.as_view(), name='logout'),
    
    # El Dashboard administrativo que ya creamos
    path('<slug:slug_academia>/dashboard/', views.DashboardAdminView.as_view(), name='dashboard'),
    path('<slug:slug_academia>/configuracion/', views.BrandingConfigView.as_view(), name='configuracion'),
]