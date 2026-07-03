Parent–Teacher Conference Booking System

A Django web app for scheduling parent–teacher conference time slots. Parents log in with Google, pick a child, and book an open slot with a teacher. Teachers manage their own availability, breaks, and assigned cabinet. Admins manage everything else (subjects, classes, cabinets, teacher assignments) through the Django admin panel.

Features


Google login only — no password-based signup, via django-allauth.
Parent flow — add children, pick an active child, browse teacher schedules by date, reserve a slot, cancel a reservation (if ≥ 24h in advance).
Teacher flow — a dedicated dashboard to add/remove working-hour blocks (with configurable interval and slot type), add breaks within those blocks, and see bookings.
Admin flow — manage subjects, cabinets, classes (Klasė), teacher–class–subject assignments, and add "dalykininkų" (subject-specialist) conversation blocks that teachers can't create themselves.
Cabinet assignment — a working-hours block can specify a cabinet, falling back to the teacher's default cabinet if not set.
Static files served via WhiteNoise; containerized with Docker.


Tech stack

Python / Django 5.2
django-allauth (Google OAuth)
django-crispy-forms
SQLite (default, dev)
WhiteNoise for static files
Docker / docker-compose
