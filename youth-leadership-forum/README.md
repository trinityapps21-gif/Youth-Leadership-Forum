# Youth Leadership Forum

A social and messaging platform for young leaders: a feed (like Instagram), direct and group chats
(like WhatsApp), admin approval of new members, and moderation tools.

Built and powered by **Emtrixz Technology Company**.

**Stack:** Python (Flask) · HTML/CSS/JS templates · Turso (libSQL) database · Cloudinary media bucket

## What's inside

| Area | What it does |
|---|---|
| Sign up / sign in | New accounts wait for admin approval. Members see a clear message if they are pending, rejected or suspended. |
| Feed | Text and photo posts, likes, comments, delete your own posts, report a post. |
| Chats | One-to-one chats and group chats with unread counts. Messages refresh every few seconds. |
| Groups | Create a group, pick members, add or remove people (owner), leave a group. |
| People | Directory with search, profile pages, block and report. |
| Admin | Overview, approvals queue, all users (search, filter, warn, suspend temporarily or permanently, reinstate, change role), post moderation (take down with a reason, restore), reports queue, activity log. |

## 1. Run it on your computer

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # Windows: copy .env.example .env
```

Open `.env` and fill in:

| Key | Where to get it |
|---|---|
| `TURSO_DATABASE_URL` | `turso db show --url <your-database-name>` |
| `TURSO_AUTH_TOKEN` | `turso db tokens create <your-database-name>` |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Your first admin login. Created automatically on first start. |
| `CLOUDINARY_URL` | Cloudinary dashboard > Settings > API Keys. Or fill the three `CLOUDINARY_CLOUD_NAME` / `_API_KEY` / `_API_SECRET` values instead. |

Check the connection, then start the app:

```bash
python check_db.py
python app.py                     # http://localhost:5000
```

If you leave the Turso keys empty, the app uses a local file (`local.db`) so you can try it without a database.

## 2. Deploy

Works on any host that runs Python: Render, Railway, Fly.io, a VPS, or Docker.

- Start command: `gunicorn app:app --workers 2 --threads 4` (already in `Procfile` and `Dockerfile`).
- Set the same environment variables from `.env` on the host. Also set `SESSION_COOKIE_SECURE=1` once the site runs on HTTPS.
- **Photos:** all uploads (profile pictures, post photos, group pictures) go to the Cloudinary bucket, inside the `youth_leadership_forum` folder. Nothing is stored on the host's disk, so redeploys never lose photos. If the Cloudinary keys are empty, photos are saved locally in `UPLOAD_DIR` instead (fine for testing only).

## 3. First steps as admin

1. Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`, then open **Admin** in the side menu.
2. New sign-ups appear under **Approvals**. Approve or reject each one.
3. Reported posts show under **Posts** and **Reports**. Taking a post down hides it from the feed but keeps it in the database. Every admin action is recorded in the **Activity log**.

## Safety notes

- Passwords are hashed. Forms are CSRF-protected. Uploads are re-encoded as JPEG, so a file that only pretends to be an image is rejected.
- Suspensions take effect on the next page load, even for people who are already signed in.
- Messages are stored as plain text so admins can investigate reports. Tell members this in your community rules.
- Login attempts are limited per IP and email. The limiter is in memory, so it resets on restart.
- For an audience of minors, check the data-protection and child-safeguarding rules in your country, and agree a moderation process before you launch.

## Project layout

```
app.py            app setup
config.py         settings read from .env
db.py             Turso connection and table creation
helpers.py        sign-in checks, CSRF, image processing, date formatting
storage.py        saves and deletes photos in the Cloudinary bucket
routes/           auth, feed, people, chat (+groups), admin
templates/        HTML pages
static/           CSS, JavaScript, logo and photos
check_db.py       tests the database connection
```

## Media bucket notes

- The app only deletes files inside its own folder (`CLOUDINARY_FOLDER`). It will never remove files that belong to another project on the same Cloudinary account.
- Using the same Cloudinary account as MFL Mentorship is fine. The separate folder keeps the files apart, and both projects' photos count toward the one storage and bandwidth quota.
- A post an admin takes down keeps its photo in the bucket, so there is evidence for the report. Deleting your own post removes the photo.
