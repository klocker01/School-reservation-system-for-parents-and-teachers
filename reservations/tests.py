from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import (
    Cabinet, Child, Profile, Reservation, Teacher, Vadovas, VadovoLaikas,
    VadovoRezervacija, WorkingHours,
)
from .views import sudaryti_laikus


class VadovoIrTevuSusikirtimai(TestCase):
    def setUp(self):
        self.diena = date.today() + timedelta(days=7)
        self.kab = Cabinet.objects.create(pavadinimas="101")

        self.mokytojas = Teacher.objects.create(vardas="Ona", pavarde="Onaitė", email="ona@test.lt")
        self.wh = WorkingHours.objects.create(
            date=self.diena, start_time=time(15, 0), end_time=time(16, 0),
            interval=10, tipas="individualus",
        )
        self.wh.mokytojai.add(self.mokytojas)

        self.vadovas = Vadovas.objects.create(vardas="Jonas", pavarde="Jonaitis", email="jonas@test.lt")
        self.vl = VadovoLaikas.objects.create(
            vadovas=self.vadovas, date=self.diena, start_time=time(15, 0),
            end_time=time(16, 0), interval=15, cabinet=self.kab,
        )

        self.tevas = User.objects.create_user("tevas", email="tevas@test.lt")
        vaikas = Child.objects.create(user=self.tevas, first_name="Petras", last_name="P")
        Profile.objects.create(user=self.tevas, active_child=vaikas)

    def rezervuoti_tevui(self, laikas):
        self.client.force_login(self.tevas)
        return self.client.post(reverse("reserve_timeslot", args=[self.mokytojas.id]), {
            "date": self.diena.isoformat(), "times": [laikas],
            "tipas": "individualus", "confirm": "yes",
        })

    def test_tevai_negali_rezervuoti_kai_mokytojas_pas_vadova(self):
        # pokalbis su vadovu 15:00-15:15 uzima tevu laikus 15:00 ir 15:10
        VadovoRezervacija.objects.create(
            vadovas=self.vadovas, mokytojas=self.mokytojas, date=self.diena, time=time(15, 0),
        )
        self.rezervuoti_tevui("15:10")
        self.assertFalse(Reservation.objects.exists())

        self.rezervuoti_tevui("15:20")
        self.assertTrue(Reservation.objects.filter(time=time(15, 20)).exists())

    def test_grafike_laikas_rodomas_uzimtu(self):
        VadovoRezervacija.objects.create(
            vadovas=self.vadovas, mokytojas=self.mokytojas, date=self.diena, time=time(15, 0),
        )
        laikai = {s["time"]: s["status"] for s in sudaryti_laikus(self.mokytojas, self.diena, [self.wh], show_names=False)}
        self.assertEqual(laikai["15:00"], "busy")
        self.assertEqual(laikai["15:10"], "busy")
        self.assertEqual(laikai["15:20"], "free")

    def test_mokytojas_negali_pas_vadova_kai_uzsiregistrave_tevai(self):
        Reservation.objects.create(
            user=self.tevas, teacher=self.mokytojas, date=self.diena, time=time(15, 10),
        )
        mokytojo_user = User.objects.create_user("ona", email="ona@test.lt")
        self.client.force_login(mokytojo_user)
        self.client.post(reverse("pokalbiai_vadovas_rezervuoti", args=[self.vadovas.id]), {
            "date": self.diena.isoformat(), "time": "15:00", "confirm": "yes",
        })
        self.assertFalse(VadovoRezervacija.objects.exists())
