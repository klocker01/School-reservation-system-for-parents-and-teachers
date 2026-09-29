from django.contrib import admin, messages
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import path
from datetime import datetime, timedelta

from .importas import importuoti_mokytojus, importuoti_tevu_emailus

from .models import (
    Subject, Cabinet, Klase, Teacher, WorkingHours, Break, Reservation, Profile, Child, LeistinasEmail,
    Vadovas, VadovoLaikas, VadovoPertrauka, VadovoRezervacija,
)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("pavadinimas",)
    search_fields = ("pavadinimas",)


@admin.register(Cabinet)
class CabinetAdmin(admin.ModelAdmin):
    list_display = ("pavadinimas",)
    search_fields = ("pavadinimas",)


# adminas tvarko klases čia
@admin.register(Klase)
class KlaseAdmin(admin.ModelAdmin):
    list_display = ("pavadinimas", "aukletojas")
    search_fields = ("pavadinimas",)
    fields = ("pavadinimas", "aukletojas")


# forma mokytoju sarasui ikelti
class MokytojuImportoForma(forms.Form):
    failas = forms.FileField(
        label="Failas",
    )


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    change_list_template = "admin/reservations/teacher/change_list.html"
    list_display = ("vardas", "pavarde", "dalykai_text", "klases_text", "kabinetas", "email")
    search_fields = ("vardas", "pavarde", "email")
    list_filter = ("kabinetas", "klases")
    fields = ("vardas", "pavarde", "kabinetas", "dalykai", "klases", "email")
    filter_horizontal = ("dalykai", "klases")

    # savas adresas mokytoju sarasui ikelti
    def get_urls(self):
        urls = super().get_urls()
        savi = [
            path(
                "importuoti/",
                self.admin_site.admin_view(self.importo_puslapis),
                name="reservations_teacher_importuoti",
            ),
        ]
        return savi + urls

    def importo_puslapis(self, request):
        if request.method == "POST":
            forma = MokytojuImportoForma(request.POST, request.FILES)
            if forma.is_valid():
                failas = request.FILES["failas"]
                ataskaita = importuoti_mokytojus(failas, failas.name)

                if ataskaita["sukurta"] or ataskaita["atnaujinta"]:
                    messages.success(
                        request,
                        f"Sukurta nauju: {ataskaita['sukurta']}, "
                        f"atnaujinta: {ataskaita['atnaujinta']}, "
                        f"praleista: {ataskaita['praleista']}"
                    )
                else:
                    messages.warning(
                        request,
                        f"Naujų mokytojų nepridėta. Praleista eilučių: {ataskaita['praleista']}"
                    )

                # klaidas rodome po viena, kad butu aisku kurioje eiluteje kas negerai
                for klaida in ataskaita["klaidos"][:15]:
                    messages.error(request, klaida)
                if len(ataskaita["klaidos"]) > 15:
                    messages.error(
                        request,
                        f"...ir dar {len(ataskaita['klaidos']) - 15} klaidos"
                    )

                return redirect("admin:reservations_teacher_changelist")
        else:
            forma = MokytojuImportoForma()

        return render(request, "admin/reservations/teacher/importuoti.html", {
            "forma": forma,
            "opts": self.model._meta,
            "title": "Įkelti mokytojų sąrašą",
        })

    # sudeti visus mokytojo dalykus i viena teksta
    def dalykai_text(self, obj):
        dal = obj.dalykai.all()
        if not dal:
            return "-"
        return ", ".join([d.pavadinimas for d in dal])

    dalykai_text.short_description = "Dalykai"

    # sudeti visas mokytojo klases i viena teksta
    def klases_text(self, obj):
        kl = obj.klases.all()
        if not kl:
            return "-"
        return ", ".join([k.pavadinimas for k in kl])

    klases_text.short_description = "Klasės"


class BreakInline(admin.TabularInline):
    model = Break
    extra = 1
    fields = ("start_time", "end_time", "description", "pasalintas_laikas")


# Trinant laiko bloka per admin panele kartu trinamos ir jo rezervacijos - kaip
# ir trinant is mokytojo/vadovo grafiko. Rezervacijos su bloku tiesiogiai
# nesusietos (tik per data ir laika), tai tikrinam, kad laiko nedengtu kitas
# to paties mokytojo/vadovo blokas - tokios rezervacijos turi likti
def _istrinti_nepadengtas(rezervacijos, kiti_blokai):
    kiti = list(kiti_blokai)
    for r in rezervacijos:
        if not any(k.start_time <= r.time < k.end_time for k in kiti):
            r.delete()


def istrinti_darbo_laiko_rezervacijas(wh):
    for mokytojas in wh.mokytojai.all():
        _istrinti_nepadengtas(
            Reservation.objects.filter(
                teacher=mokytojas, date=wh.date, tipas=wh.tipas,
                time__gte=wh.start_time, time__lt=wh.end_time,
            ),
            WorkingHours.objects.filter(mokytojai=mokytojas, date=wh.date, tipas=wh.tipas).exclude(id=wh.id),
        )


def istrinti_vadovo_laiko_rezervacijas(blokas):
    _istrinti_nepadengtas(
        VadovoRezervacija.objects.filter(
            vadovas_id=blokas.vadovas_id, date=blokas.date,
            time__gte=blokas.start_time, time__lt=blokas.end_time,
        ),
        VadovoLaikas.objects.filter(vadovas_id=blokas.vadovas_id, date=blokas.date).exclude(id=blokas.id),
    )


@admin.register(WorkingHours)
class WorkingHoursAdmin(admin.ModelAdmin):
    list_display = ("date", "start_time", "end_time", "tipas", "cabinet", "mokytojai_list")
    list_filter = ("date", "tipas", "cabinet")
    filter_horizontal = ("mokytojai",)
    inlines = [BreakInline]

    def mokytojai_list(self, obj):
        visi = obj.mokytojai.all()
        if not visi:
            return "-"
        return ", ".join([f"{m.vardas} {m.pavarde}" for m in visi])

    mokytojai_list.short_description = "Mokytojai"

    def delete_model(self, request, obj):
        with transaction.atomic():
            istrinti_darbo_laiko_rezervacijas(obj)
            super().delete_model(request, obj)

    # trinant kelis is saraso (veiksmas "Ištrinti pasirinktus")
    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for wh in queryset:
                istrinti_darbo_laiko_rezervacijas(wh)
            super().delete_queryset(request, queryset)


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "klase", "user")
    search_fields = ("first_name", "last_name", "user__email")
    list_filter = ("klase",)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "active_child")
    search_fields = ("user__email",)


# tikrina ar laikas telpa i darbo laikus ir ne per pertrauka
def ar_admin_laikas_leistinas(mokytojas, data, laikas):
    darbo_laikai = (
        WorkingHours.objects
        .filter(mokytojai=mokytojas, date=data)
        .prefetch_related("breaks")
    )

    if not darbo_laikai.exists():
        return False

    telpa = False
    for d in darbo_laikai:
        if d.start_time <= laikas < d.end_time:
            telpa = True
            break

    if not telpa:
        return False

    for d in darbo_laikai:
        for p in d.breaks.all():
            if p.start_time <= laikas < p.end_time:
                return False

    return True


class ReservationAdminForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = (
            "teacher",
            "date",
            "time",
            "reserved_first_name",
            "reserved_last_name",
            "reserved_class",
            "user",
            "child",
            "cabinet",
        )

    # kai adminas kuria rezervacija – tikrinam laika
    def clean(self):
        duom = super().clean()

        teacher = duom.get("teacher")
        data = duom.get("date")
        time = duom.get("time")

        if not teacher or not data or not time:
            return duom

        if not ar_admin_laikas_leistinas(teacher, data, time):
            raise ValidationError("Laikas turi būti mokytojo darbo laiko ribose ir ne per pertrauką")

        return duom


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    form = ReservationAdminForm
    list_display = (
        "id",
        "teacher",
        "date",
        "time",
        "reserved_first_name",
        "reserved_last_name",
        "reserved_class",
        "user",
        "child",
        "cabinet",
    )
    list_filter = ("teacher", "date", "cabinet")
    search_fields = (
        "reserved_first_name",
        "reserved_last_name",
        "reserved_class",
        "user__email",
        "teacher__vardas",
        "teacher__pavarde",
    )
    ordering = ("-date", "-time")


# adminas cia deda tevu adresus, kuriems leidziama prisijungti
@admin.register(LeistinasEmail)
class LeistinasEmailAdmin(admin.ModelAdmin):
    change_list_template = "admin/reservations/leistinasemail/change_list.html"
    list_display = ("email", "pastaba", "pridetas")
    search_fields = ("email", "pastaba")
    ordering = ("email",)

    # savas adresas tevu el. pastu sarasui ikelti
    def get_urls(self):
        urls = super().get_urls()
        savi = [
            path(
                "importuoti/",
                self.admin_site.admin_view(self.importo_puslapis),
                name="reservations_leistinasemail_importuoti",
            ),
        ]
        return savi + urls

    def importo_puslapis(self, request):
        if request.method == "POST":
            forma = MokytojuImportoForma(request.POST, request.FILES)
            if forma.is_valid():
                failas = request.FILES["failas"]
                ataskaita = importuoti_tevu_emailus(failas, failas.name)

                santrauka = (
                    f"Pridėta naujų: {ataskaita['prideta']}, "
                    f"jau buvo sąraše: {ataskaita['jau_buvo']}, "
                    f"pasikartojo faile: {ataskaita['pasikartojo']}"
                )
                if ataskaita["prideta"]:
                    messages.success(request, santrauka)
                else:
                    messages.warning(request, santrauka)

                for klaida in ataskaita["klaidos"][:15]:
                    messages.error(request, klaida)
                if len(ataskaita["klaidos"]) > 15:
                    messages.error(
                        request,
                        f"...ir dar {len(ataskaita['klaidos']) - 15} klaidos"
                    )

                return redirect("admin:reservations_leistinasemail_changelist")
        else:
            forma = MokytojuImportoForma()

        return render(request, "admin/reservations/leistinasemail/importuoti.html", {
            "forma": forma,
            "opts": self.model._meta,
            "title": "Įkelti tėvų el. paštų sąrašą",
        })


# adminas priskiria vadovo el. pasta - pagal ji sistema atpazista vadova
@admin.register(Vadovas)
class VadovasAdmin(admin.ModelAdmin):
    list_display = ("vardas", "pavarde", "email")
    search_fields = ("vardas", "pavarde", "email")
    fields = ("vardas", "pavarde", "email")


class VadovoPertraukaInline(admin.TabularInline):
    model = VadovoPertrauka
    extra = 0
    fields = ("start_time", "end_time", "description", "pasalintas_laikas")


@admin.register(VadovoLaikas)
class VadovoLaikasAdmin(admin.ModelAdmin):
    list_display = ("vadovas", "date", "start_time", "end_time", "interval", "cabinet")
    list_filter = ("vadovas", "date")
    inlines = [VadovoPertraukaInline]

    def delete_model(self, request, obj):
        with transaction.atomic():
            istrinti_vadovo_laiko_rezervacijas(obj)
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for blokas in queryset:
                istrinti_vadovo_laiko_rezervacijas(blokas)
            super().delete_queryset(request, queryset)


@admin.register(VadovoRezervacija)
class VadovoRezervacijaAdmin(admin.ModelAdmin):
    list_display = ("vadovas", "mokytojas", "date", "time", "cabinet")
    list_filter = ("vadovas", "date")
    search_fields = ("mokytojas__vardas", "mokytojas__pavarde", "vadovas__pavarde")
    ordering = ("-date", "-time")
    
