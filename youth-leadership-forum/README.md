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
| Forgot password | A member picks a new password and sends it for approval. Nothing changes until an admin approves. No email service needed. |
| Admin | Overview, approvals queue, password reset approvals, all users (search, filter, warn, suspend temporarily or permanently, reinstate, change role), post moderation (take down with a reason, restore), reports queue, activity log. |

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

Check that Turso and Cloudinary are both connected, then start the app:

```bash
python check_db.py
python app.py                     # http://localhost:5000
```

If you leave the Turso keys empty, the app uses a local file (`local.db`) so you can try it without a database.

## 2. Deploy on Render

1. Put the project on GitHub (a private repo is best). `.env` is in `.gitignore`, so your keys are never uploaded.
2. In Render: **New > Blueprint**, pick the repo. Render reads `render.yaml` and creates the web service.
3. Render asks for the values marked as secret. Paste in:
   `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `CLOUDINARY_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.
   (`SECRET_KEY` is generated for you.)
4. Wait for the first deploy. Open the Render URL and sign in with the admin email and password.
5. Optional: add your own domain under **Settings > Custom Domains**. HTTPS is automatic.

Good to know:
- **The app refuses to start on Render without Turso and Cloudinary keys.** This is deliberate: Render's disk is erased on every deploy, so a local database or local photos would silently disappear.
- **Free plan sleeps** after about 15 minutes with no visitors, and the next visitor waits roughly a minute while it wakes up. Use the Starter plan for a site that must always be instant.
- **Region:** create the Turso database and the Render service in nearby regions (for example both in Europe). Every page makes a few database calls, so distance adds up.
- After the first sign-in, you can delete `ADMIN_PASSWORD` from Render's environment settings.
- Other hosts work too: use the `Procfile` or `Dockerfile`.

## 3. First steps as admin

1. Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`, then open **Admin** in the side menu.
2. New sign-ups appear under **Approvals**. Approve or reject each one.
3. Reported posts show under **Posts** and **Reports**. Taking a post down hides it from the feed but keeps it in the database. Every admin action is recorded in the **Activity log**.

## Forgot password (admin approval)

1. On the sign-in page, the member presses **Forgot your password?**, enters their email, chooses a new password, and writes how the admin can confirm it's them (school, class, a leader who knows them).
2. The request appears under **Admin > Password resets** with a badge. The old password keeps working until an admin decides.
3. The admin confirms the person's identity outside the app (in person or through someone trusted), then presses **Approve reset** or **Reject** (with a reason the member sees when they try to sign in).
4. After approval the member signs in with the new password they chose. Every other device they were signed in on is signed out.

Details:
- The password is stored hashed from the moment it is submitted, so admins never see it.
- Only one request per person is open at a time. A newer request replaces the older one. Requests are limited to 3 per email per hour.
- The request page gives the same answer for any email, so it can't be used to check who has an account.
- Admins can't approve their own reset. Another admin must.
- Every approval and rejection is recorded in the activity log.
- **If the only admin forgets their password:** run `python reset_admin.py admin@yourforum.org` on a computer that has your `.env` file. It asks for a new password and updates the Turso database.

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
check_db.py       tests the Turso and Cloudinary connections
reset_admin.py    emergency password reset for an admin account
```

## Media bucket notes

- The app only deletes files inside its own folder (`CLOUDINARY_FOLDER`). It will never remove files that belong to another project on the same Cloudinary account.
- Using the same Cloudinary account as MFL Mentorship is fine. The separate folder keeps the files apart, and both projects' photos count toward the one storage and bandwidth quota.
- A post an admin takes down keeps its photo in the bucket, so there is evidence for the report. Deleting your own post removes the photo.
