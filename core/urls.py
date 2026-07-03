from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

from reservations import views


urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Tik Google login 
    path("accounts/", include("allauth.urls")),

    # Uždraudžiam paprastą signup formą
    path(
        "accounts/signup/",
        RedirectView.as_view(url="/accounts/login/", permanent=False),
    ),

    # Pagrindinis puslapis (datos)
    path("", views.home, name="home"),

    # Grafikas pagal datą
    path(
        "schedule/<str:date_str>/",
        views.teacher_schedule,
        name="teacher_schedule",
    ),

    # Rezervacija
    path(
        "teacher/<int:teacher_id>/reserve/",
        views.reserve_timeslot,
        name="reserve_timeslot",
    ),
    path(
        "profile/delete-child/<int:child_id>/",
        views.delete_child,
        name="delete_child",
    ),
    # Profilio redagavimas
    path(
        "profile/edit/",
        views.edit_profile,
        name="edit_profile",
    ),

    # Vaiko pridėjimas
    path(
        "profile/add-child/",
        views.add_child,
        name="add_child",
    ),

    # Aktyvaus vaiko pasirinkimas
    path(
        "profile/set-child/<int:child_id>/",
        views.set_active_child,
        name="set_active_child",
    ),

    # Mano rezervacijos
    path(
        "my-reservations/",
        views.my_reservations,
        name="my_reservations",
    ),

    # Rezervacijos atšaukimas (>= 24h)
    path(
        "my-reservations/<int:reservation_id>/cancel/",
        views.cancel_reservation,
        name="cancel_reservation",
    ),

    # Mokytojo grafikas valdymas
    path("teacher/dashboard/", views.teacher_dashboard, name="teacher_dashboard"),
    path("teacher/workinghours/add/", views.teacher_add_workinghours, name="teacher_add_workinghours"),
    path("teacher/workinghours/<int:wh_id>/delete/", views.teacher_delete_workinghours, name="teacher_delete_workinghours"),
    path("teacher/workinghours/<int:wh_id>/break/add/", views.teacher_add_break, name="teacher_add_break"),
    path("teacher/break/<int:break_id>/delete/", views.teacher_delete_break, name="teacher_delete_break"),
]
