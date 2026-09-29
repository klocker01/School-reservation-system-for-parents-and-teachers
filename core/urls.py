from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

from reservations import views, views_vadovas


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
    path("teacher/workinghours/<int:wh_id>/slot/delete/", views.teacher_delete_slot, name="teacher_delete_slot"),
    path("teacher/workinghours/<int:wh_id>/break/add/", views.teacher_add_break, name="teacher_add_break"),
    path("teacher/break/<int:break_id>/delete/", views.teacher_delete_break, name="teacher_delete_break"),

    # Mokytojo pokalbiai su vadovu
    path("teacher/vadovas/", views_vadovas.pokalbiai_vadovas, name="pokalbiai_vadovas"),
    path("teacher/vadovas/<int:vadovas_id>/reserve/", views_vadovas.pokalbiai_vadovas_rezervuoti, name="pokalbiai_vadovas_rezervuoti"),
    path("teacher/vadovas/reservation/<int:rezervacija_id>/cancel/", views_vadovas.pokalbiai_vadovas_atsaukti, name="pokalbiai_vadovas_atsaukti"),

    # Vadovo grafiko valdymas
    path("vadovas/dashboard/", views_vadovas.vadovas_dashboard, name="vadovas_dashboard"),
    path("vadovas/laikas/add/", views_vadovas.vadovas_add_laikas, name="vadovas_add_laikas"),
    path("vadovas/laikas/<int:laikas_id>/delete/", views_vadovas.vadovas_delete_laikas, name="vadovas_delete_laikas"),
    path("vadovas/laikas/<int:laikas_id>/slot/delete/", views_vadovas.vadovas_delete_slot, name="vadovas_delete_slot"),
    path("vadovas/laikas/<int:laikas_id>/break/add/", views_vadovas.vadovas_add_break, name="vadovas_add_break"),
    path("vadovas/break/<int:break_id>/delete/", views_vadovas.vadovas_delete_break, name="vadovas_delete_break"),
]
