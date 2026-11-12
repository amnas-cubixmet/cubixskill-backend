#!/usr/bin/env python3
"""Live-stack functional smoke: register → setup → login → course/module/lesson → enroll → student access."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import django
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from authentication.models import AuthToken, AuthTokenService, TokenType  # noqa: E402
from users_roles.models import User  # noqa: E402

BASE = os.environ.get("SMOKE_API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
S = requests.Session()
PASS = "SmokeTestPass123!"
suffix = uuid.uuid4().hex[:8]
ADMIN_EMAIL = f"smoke.admin.{suffix}@cubixskill.test"
STUDENT_EMAIL = f"smoke.student.{suffix}@cubixskill.test"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def req(method: str, path: str, *, expect=200, session=None, **kwargs):
    sess = session or S
    url = path if path.startswith("http") else f"{BASE}{path}"
    r = sess.request(method, url, timeout=30, **kwargs)
    return r


def main():
    # 1) Health
    r = req("GET", "/health/")
    check("API health", r.status_code == 200 and r.json().get("status") == "healthy", r.text[:120])

    # 2) Invalid academy register
    r = req(
        "POST",
        "/auth/register/academy/",
        json={"academy_name": "", "full_name": "", "email": "bad"},
    )
    check("Academy register rejects invalid payload", r.status_code == 400, str(r.status_code))

    # 3) Academy register
    r = req(
        "POST",
        "/auth/register/academy/",
        json={
            "academy_name": f"Smoke Academy {suffix}",
            "full_name": "Smoke Admin",
            "email": ADMIN_EMAIL,
            "phone": "+919876543210",
        },
    )
    check("Academy register creates account", r.status_code == 201, r.text[:200])
    if r.status_code != 201:
        return finish()

    admin = User.objects.get(email__iexact=ADMIN_EMAIL)
    token_row = AuthToken.objects.filter(user=admin, token_type=TokenType.PASSWORD_SETUP).order_by("-created_at").first()
    check("Password setup token created", token_row is not None)
    if not token_row:
        return finish()

    # Raw token is hashed in DB — use AuthTokenService path from email metadata if present
    from authentication.models import AuthTokenService

    # Regenerate a usable raw token for setup (consume existing pattern via generate)
    # Prefer metadata on EmailJob
    from emails.models import EmailJob

    job = EmailJob.objects.filter(template_name="academy_activation", academy_uuid=admin.academy_id).order_by("-created_at").first()
    raw = None
    if job and isinstance(job.metadata, dict):
        raw = job.metadata.get("raw_token") or job.metadata.get("token") or job.metadata.get("setup_token")
    if not raw:
        # generate fresh usable token for the live smoke (revokes old ones typically)
        raw = AuthTokenService.generate_token(admin, TokenType.PASSWORD_SETUP)
    check("Have usable password-setup token", bool(raw))

    r = req(
        "POST",
        "/auth/password/setup/",
        json={"token": raw, "new_password": PASS, "confirm_password": PASS},
    )
    # some serializers use password / password_confirm
    if r.status_code >= 400:
        r = req(
            "POST",
            "/auth/password/setup/",
            json={"token": raw, "password": PASS, "password_confirm": PASS},
        )
    if r.status_code >= 400:
        r = req(
            "POST",
            "/auth/password/setup/",
            json={"token": raw, "new_password": PASS},
        )
    check("Password setup succeeds", r.status_code in (200, 201), r.text[:250])

    # 4) Instructor login
    login_sess = requests.Session()
    r = req(
        "POST",
        "/auth/instructor/login/",
        session=login_sess,
        json={"email": ADMIN_EMAIL, "password": PASS},
    )
    check("Instructor login", r.status_code == 200, r.text[:200])
    me = req("GET", "/auth/instructor/me/", session=login_sess)
    check("Instructor me authenticated", me.status_code == 200, me.text[:200])

    # 5) Unauthenticated protected route
    r = req("GET", "/auth/instructor/me/", session=requests.Session())
    check("Instructor me rejects anonymous", r.status_code in (401, 403), str(r.status_code))

    # 6) Create course
    r = req(
        "POST",
        "/courses/",
        session=login_sess,
        json={
            "title": f"Smoke Course {suffix}",
            "short_description": "Functional smoke course",
            "status": "PUBLISHED",
            "is_free": True,
        },
    )
    # alternate nested create paths used by some viewsets
    if r.status_code >= 400:
        r = req(
            "POST",
            "/courses/courses/",
            session=login_sess,
            json={
                "title": f"Smoke Course {suffix}",
                "short_description": "Functional smoke course",
                "status": "PUBLISHED",
                "is_free": True,
            },
        )
    check("Create course", r.status_code in (200, 201), f"{r.status_code} {r.text[:220]}")
    course_id = None
    if r.status_code in (200, 201):
        body = r.json()
        data = body.get("data") or body
        course_id = data.get("id") or data.get("uuid") or (data.get("course") or {}).get("id")

    # list courses
    r = req("GET", "/courses/", session=login_sess)
    if r.status_code >= 400:
        r = req("GET", "/courses/courses/", session=login_sess)
    check("List courses", r.status_code == 200, str(r.status_code))
    if not course_id and r.status_code == 200:
        payload = r.json()
        items = payload.get("results") or payload.get("data") or payload
        if isinstance(items, dict):
            items = items.get("results") or []
        if isinstance(items, list) and items:
            course_id = items[0].get("id")

    check("Have course id", bool(course_id), str(course_id))

    # 7) Module + lesson
    module_id = None
    if course_id:
        r = req(
            "POST",
            f"/modules/courses/{course_id}/modules/",
            session=login_sess,
            json={"title": "Intro Module", "description": "Smoke module"},
        )
        check("Create module", r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}")
        if r.status_code in (200, 201):
            data = r.json().get("data") or r.json()
            module_id = data.get("id")

        r = req("GET", f"/modules/courses/{course_id}/modules/", session=login_sess)
        check("List modules", r.status_code == 200, str(r.status_code))

        if module_id:
            r = req(
                "POST",
                f"/modules/{module_id}/lessons/",
                session=login_sess,
                json={"title": "Welcome Lesson", "lesson_type": "RICH_TEXT", "description": "Hello"},
            )
            check("Create lesson", r.status_code in (200, 201), f"{r.status_code} {r.text[:220]}")

    # 8) Student register requires academy context (slug/uuid)
    academy = admin.academy
    r = req(
        "POST",
        "/auth/register/student/",
        json={
            "full_name": "Smoke Student",
            "email": STUDENT_EMAIL,
            "academy_slug": academy.slug,
            "phone": "+919999999999",
        },
    )
    check("Student register with academy_slug", r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}")

    student_sess = requests.Session()
    student = User.objects.get(email__iexact=STUDENT_EMAIL)
    student_raw = AuthTokenService.generate_token(student, TokenType.PASSWORD_SETUP)
    r = req(
        "POST",
        "/auth/password/setup/",
        json={"token": student_raw, "new_password": PASS, "confirm_password": PASS},
    )
    check("Student password setup", r.status_code == 200, r.text[:200])
    r = req(
        "POST",
        "/auth/student/login/",
        session=student_sess,
        json={"email": STUDENT_EMAIL, "password": PASS},
    )
    check("Student login", r.status_code == 200, r.text[:200])

    if course_id:
        from enrollments.models import Enrollment, EnrollmentStatus

        Enrollment.objects.get_or_create(
            student=student,
            course_id=course_id,
            defaults={"status": EnrollmentStatus.ACTIVE},
        )
        r = req("GET", "/enrollments/student/enrollments/", session=student_sess)
        check("Student enrollments list", r.status_code == 200, r.text[:200])
        if r.status_code == 200:
            body = r.json()
            items = body.get("results") or body.get("data") or body
            if isinstance(items, dict):
                items = items.get("results") or []
            check(
                "Student sees enrolled course",
                isinstance(items, list) and len(items) >= 1,
                str(len(items) if isinstance(items, list) else items)[:80],
            )

    # 9) Instructor logout / me
    r = req("POST", "/auth/instructor/logout/", session=login_sess)
    check("Instructor logout", r.status_code in (200, 204), str(r.status_code))
    r = req("GET", "/auth/instructor/me/", session=login_sess)
    check("Instructor me after logout is unauthorized", r.status_code in (401, 403), str(r.status_code))

    # 10) Duplicate academy email rejected
    r = req(
        "POST",
        "/auth/register/academy/",
        json={
            "academy_name": f"Dup Academy {suffix}",
            "full_name": "Dup Admin",
            "email": ADMIN_EMAIL,
            "phone": "+919876543210",
        },
    )
    check("Duplicate academy email rejected", r.status_code == 400, str(r.status_code))

    finish()


def finish():
    failed = [r for r in results if not r[1]]
    print("\n==== SUMMARY ====")
    print(f"Passed: {sum(1 for r in results if r[1])}/{len(results)}")
    if failed:
        print("Failures:")
        for name, _, detail in failed:
            print(f" - {name}: {detail}")
        sys.exit(1)
    print("All functional smoke checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
