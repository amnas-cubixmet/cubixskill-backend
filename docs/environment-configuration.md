# CubixSkill backend: environment configuration

Use an untracked `.env` file in the **backend repository root**. Run `python manage.py check` after changing settings. Never commit `.env` or copy actual passwords into issues.

## Local development

The following configuration supports public Next.js on **5175**, instructor Vite on **5173**, student Vite on **5174**, and Django on **8000**.

```dotenv
SECRET_KEY=dev-only-change-for-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
USE_POSTGRES=False
USE_REDIS_CHANNELS=False
STORAGE_BACKEND=local
AUTH_COOKIE_SECURE=False
AUTH_COOKIE_SAMESITE=Lax
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:5174,http://localhost:5175,http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5175
CSRF_TRUSTED_ORIGINS=http://localhost:5173,http://localhost:5174,http://localhost:5175,http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5175
FRONTEND_ACADEMY_URL=http://localhost:5173
STUDENT_PUBLIC_URL=http://localhost:5174
REDIS_URL=redis://127.0.0.1:6379/0
```

Do **not** add backslashes before the colons in `http://`. The parser can tolerate Markdown-escaped colons and stray trailing backslashes, but clean URLs are preferred. Never include `/login`, a trailing `/api/v1`, or a page path in an allowed origin.

If `CORS_ALLOWED_ORIGINS` or `CSRF_TRUSTED_ORIGINS` is set in `.env`, the value **replaces** the development defaults. Put every origin you use in the list. Port numbers are part of the origin.

### Test registration and session

1. Run `python manage.py migrate` and `python manage.py runserver` in the backend; restart it after changing the environment.
2. Run the public site on `http://localhost:5175` and set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` in its own `.env.local`.
3. Open the browser Network tab and submit `/instructor-register`. A successful preflight OPTIONS is **not** evidence that the subsequent registration POST succeeded.
4. Check for POST `/api/v1/auth/register/academy/` with status **201**. If no POST appears, check `Access-Control-Allow-Origin` and browser console errors.
5. If the instructor is logged out, GET `/api/v1/auth/instructor/me/` and POST `/api/v1/auth/instructor/refresh/` legitimately return **401**. Log in to the instructor site; a successful login sets `instructor_access_token` and `instructor_refresh_token` HttpOnly cookies.

Use **localhost** consistently for frontend and backend to avoid cookie-host differences with `127.0.0.1`. Ensure the frontend sends `withCredentials: true` / `credentials: 'include'` on authenticated requests.

## Production

- Set `DEBUG=False`, a random `SECRET_KEY`, explicit `ALLOWED_HOSTS`, HTTPS origins in CORS/CSRF lists, HTTPS redirects, and `AUTH_COOKIE_SECURE=True`.
- `AUTH_COOKIE_SAMESITE=Lax` is appropriate when the UI and API are same-site. Cross-site hosts may require `None` plus `Secure=True`; browsers may still block third-party cookies, so prefer a same-site API.
- Do not use `CORS_ALLOW_ALL_ORIGINS=True` with credentialed sessions. This project uses exact CORS origin allowlists.
- Set `DATABASE_URL` **or** `USE_POSTGRES=True` with `DB_NAME` and other DB variables. `DATABASE_URL` takes precedence. Invalid database URLs now fail instead of silently choosing SQLite.
- Set `REDIS_URL` to a reachable Redis service; this config feeds Channels (when enabled) and Celery broker/result backend by default. Override `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` only if they differ.
- Use separate web, worker, and beat processes:
  - Web: `gunicorn -k uvicorn.workers.UvicornWorker config.asgi:application --bind 0.0.0.0:$PORT`
  - Worker: `celery -A config worker -Q celery,default,email,video_processing --loglevel=info`
  - Beat: `celery -A config beat --loglevel=info`
- After deploying schema changes, run `python manage.py migrate`. Enable storage metering at intervals of 60 seconds or greater in production.
- Do not copy example MinIO, Razorpay, SMTP, or PostgreSQL credentials into a real deployment.

## Optional environment knobs

`TIME_ZONE`, `LANGUAGE_CODE`, `JWT_ACCESS_TOKEN_MINUTES`, `JWT_REFRESH_TOKEN_DAYS`, `CELERY_TASK_TIME_LIMIT_SECONDS`, `CELERY_WORKER_PREFETCH_MULTIPLIER`, `CELERY_BROKER_CONNECTION_MAX_RETRIES`, `CELERY_RESULT_BACKEND_MAX_RETRIES`, `CELERY_RESULT_EXPIRES_SECONDS`, and `STORAGE_BILLING_BEAT_INTERVAL_SECONDS` all support environment overrides; see `.env.example`.

Run `python manage.py test core.test_environment leads.test_platform_demo --noinput` for targeted smoke checks.
