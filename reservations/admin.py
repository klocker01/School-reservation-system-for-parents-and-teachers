from django.contrib import admin, messages
from django import forms
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from django.urls import path
from datetime import datetime, timedelta

from .importas import importuoti_mokytojus

from .models import Subject, Cabinet, Klase, Teacher, WorkingHours, Break, Reservation, Profile, Child, LeistinasEmail


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

    dalykai_text.short_description = "subjects"

    # sudeti visas mokytojo klases i viena teksta
    def klases_text(self, obj):
        kl = obj.klases.all()
        if not kl:
            return "-"
        return ", ".join([k.pavadinimas for k in kl])

    klases_text.short_description = "klasės"


class BreakInline(admin.TabularInline):
    model = Break
    extra = 1
    fields = ("start_time", "end_time", "description")


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

    mokytojai_list.short_description = "teachers"


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
            raise ValidationError("time must be inside working hours and not in a break")

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
    list_display = ("email", "pastaba", "pridetas")
    search_fields = ("email", "pastaba")
    ordering = ("email",)
    
