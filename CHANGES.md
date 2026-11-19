# Mobile fix: what changed and why

Apply with `patch -p1 < mobile-fix.patch` (run inside the project folder), or copy the changes by hand using the list below.

## 1. Keyboard opened by itself
- **Cause:** `autofocus` on the login username and the chat box, plus `input.focus()` after every answer.
- **Fix:** `templates/index.html` (autofocus removed), `static/js/common.js` (new `U.focusDesktop()`, only focuses on mouse devices), `static/js/home.js`, `lesson.js`, `tools.js` (use it).

## 2. Login asked again on every open
- **Cause:** a phone/app can drop the session cookie; the server then had no way to recognise you.
- **Fix:** `app.py` now keeps a second signed "remember" cookie (90 days, refreshed on every visit) and a `/api/resume` endpoint. `common.js` also keeps a signed token in the phone's storage and restores the login silently (also returns you to the page you opened). Logout clears all of it.
- **Important on Render:** set a fixed `SECRET_KEY` and a `DATABASE_URL` (Supabase). Without a database, the free plan wipes accounts when it restarts, and nobody can stay logged in.

## 3. Layout hidden / cut off on phones
- **Cause:** header height was a guessed number (`106px`), so the chat area was the wrong height.
- **Fix:** `templates/base.html` measures the real header height (`--head-h`) and the real visible height; hides menu and buttons while the keyboard is open so the chat input stays visible.
- **Fix:** `static/css/style.css`, new "PHONE FIT" block at the end: chat screen is exactly one screen (only the message list scrolls), bottom-sheet pop-ups, bigger touch targets, menu fades at the edge to show it scrolls.

## 4. Theme
- Dark mode and the theme button removed (`base.html`, `common.js`, `style.css`). Light only.

## 5. Database check (new)
- `/health` page: writes a test value to the database and reads it back (`"storage": "database"`, `"saved_and_read_back": true`).
- Profile menu shows "All your data is saved in the database" (or a warning if `DATABASE_URL` is missing).
- `check_db.py`: run `python check_db.py` to test the connection.
- `app.py`, `services/db.py`, `templates/base.html`, `static/css/style.css`, `README.md` (deploy steps added).

## 6. No login flash + compact phone layout
- **Login page no longer flashes:** if the phone has a saved login, the form is hidden and a short "Signing you in…" screen shows until the home page opens (`templates/index.html`, `static/js/home.js`, CSS `html.resuming`).
- **Header is one slim row** on phones; the menu moved to a **bottom bar** (Home, My Study, Notes, Books, More) (`templates/base.html`, `static/js/common.js`).
- Smaller text, buttons and cards on phones so nothing looks oversized (`static/css/style.css`, last block).

## 7. Phone errors, small screens, Books upload, speed (this update)
- **Error pages on phone:** `services/_cache.dat` (the built-in course library) was never on GitHub because `.gitignore` blocked `*.dat`, so the home page crashed with a server error. Now the app starts without it (`services/knowledge.py`) and `.gitignore` allows it. **Copy your `services/_cache.dat` from your PC into the project and push it** to get the built-in subjects back.
- **Slow start / slow server:** LangChain and LangGraph were loaded at start-up for every page. They now load only when an AI feature is used (`services/agentic/__init__.py`, `services/lab_service.py`).
- **Slow section changes:** CSS and JS were downloaded again on every page and sent uncompressed. Now files are cached on the phone for a year (the `?v=` address changes when a file changes) and pages, CSS, JS and JSON are gzip compressed (`app.py`). Books page: 17.8 KB to 5.3 KB; style.css: 66 KB to 14 KB.
- **PDF upload in Books:** uploaded books were saved to a local file that Render erases on restart. They now go through `storage.py` (Supabase when `DATABASE_URL` is set). The list and the book text are stored separately so the Books page stays fast. Old local books are moved over automatically. The upload no longer sends the whole book text back to the phone (777 bytes instead of megabytes). File type and the 25 MB limit are checked on the phone before uploading; the title is optional; the file picker accepts PDF, TXT and MD on Android and iPhone (`services/book_teacher.py`, `static/js/books.js`, `templates/books.html`).
- **Small / non-fullscreen screens:** tested at 320 x 480 with no sideways scroll. Book cards, buttons and tabs adapt, test answer boxes use 16px text (no zoom on iPhone), the upload pop-up keeps its buttons pinned at the bottom, and a page-locking `touch-action: none` was removed (`templates/books.html`, `static/css/style.css`).
- **Messages:** "check the terminal" errors replaced with phone-friendly wording; Copy works inside app browsers (`static/js/common.js`).

## 8. E-mail verification (sign up, forgot password, code login), free
- **Sign up** asks for Full name, Email and Password (no username: the app makes a hidden internal id from the email and shows the full name everywhere). A 6-digit code is e-mailed; the account is created only after the code is entered. Emails are unique.
- **Log in** uses email + password (the old default accounts can still type their username in the same box). **Log in with email code** (no password) and **Forgot password** (code, then new password) are on the login screen.
- Codes: stored only as a keyed hash, valid 10 minutes, 5 wrong tries then a new code is needed, resend after 60 seconds, max 5 codes per hour per email and 20 requests per hour per device. Forgot/code-login answer the same for unknown emails, so nobody can find out who is registered.
- **Free sending with Brevo** (300 e-mails a day, no card, no domain): set `BREVO_API_KEY` and `MAIL_FROM` (an e-mail you verified in Brevo) on Render. It sends over HTTPS because Render free blocks SMTP ports. Without keys on your own PC the code is printed in the terminal; on Render the screen says e-mail is not set up.
- Existing accounts (bijay, ayush ...) have no email yet, so they log in with username + password as before; forgot password / code login need an email on the account.
- Files: `services/emailer.py`, `services/otp.py`, `services/storage.py`, `services/db.py`, `app.py`, `templates/index.html`, `static/js/home.js`, `static/css/style.css`.

## 9. English only + much faster on phones
- **English only:** the EN/Hindi button, the language choice on the profile screen and the language choice in Notes, Exam Paper and Books are removed. Old Hindi/bilingual profiles and courses are answered in English. The Coding Lab's Python/Java selector is unchanged.
- **Database speed (`services/db.py`, `services/storage.py`):** the pool no longer runs an extra check query before every request (this doubled every page's waiting time); connections are kept alive; the user record and profile are remembered for 30-60 seconds and forgotten the moment they change; "my courses" is filtered in the database (new index `courses_owner_idx`) instead of downloading everybody's courses; requests no longer wait in a queue behind each other's database calls (the global lock is only used for local files). A page now makes 1-4 database calls instead of 4-10 round trips.
- **Settings:** `.env` is read again only when it changes (it was re-read from disk many times per page) (`services/config.py`).
- **Phone screen:** blur effects removed on small screens, no tap delay, resize handling throttled, and a loading bar appears the instant a menu item is tapped (`static/css/style.css`, `static/js/common.js`, `templates/base.html`).
- **Keep awake:** new `/ping` address (no database). Free Render servers fall asleep after 15 minutes without visitors and the next visit then waits about a minute. A free monitor that opens `https://YOUR-APP.onrender.com/ping` every 10 minutes avoids that.
- Gunicorn: `--keep-alive 5 --worker-tmp-dir /dev/shm` (`Procfile`, `render.yaml`).

## 10. Exams section (GATE, JEE, NEET, CAT, any exam) + real exam hall
**Exams page (`/exams`, menu: 🎯 Exams)**
- Choose an exam and paper/branch (all GATE papers: DA, CS, EC, EE, ME, CE ... plus JEE Main, JEE Advanced, NEET UG, CAT, and "Other exam" where you type any name).
- The app reads the official syllabus (and the exam pattern when it is not built in) from the web with **Tavily**, structures it with **Groq**, and shows subjects, topics, marks, duration, negative marking and the sources used. Result is saved for 30 days (button "Refresh from the web").
- **Study plan:** one click builds a ready course: every subject is a module, every syllabus topic a lesson, scheduled day by day (you choose days and hours per day).
- **Subject test:** a short exam-style test on one subject, sized like that subject's share of the real paper, with time in the same proportion.
- **Full mock:** the complete paper.

**Exam Paper page (`/exam`)** has a new top option "🎯 Exam mock test": pick the exam, pick Full paper or one or more subjects, pick Easy / Medium / Hard. No marks or pattern questions: everything comes from the official pattern. The old custom paper maker is still there under "✏️ Custom paper".

**Official-style papers.** GATE: 65 questions, 100 marks, 3 hours: 10 General Aptitude (5 x 1 + 5 x 2 marks) + 55 technical (25 x 1 + 30 x 2), question types MCQ / MSQ / NAT, MCQ negative marking 1/3 and 2/3, no negative for MSQ and NAT, MSQ all-or-nothing, NAT accepted within a range. The technical questions are split over the syllabus subjects by their typical weightage (built-in for GATE DA and CS; approximate). JEE Main (75 questions, +4/-1, NAT without negative), NEET (180 questions, +4/-1) and CAT (66 questions, +3/-1, TITA without negative) are built in; other exams use the pattern read from the web.
Questions are written by Groq in small batches in a background job with a progress bar; every question is checked (4 options, valid answer key, numeric NAT range, topic from the syllabus), missing or broken ones are asked for again, and MCQ options are shuffled so the key letters are spread evenly.

**Exam hall (`/exam-hall/<paper>`)**: instructions screen, full screen, server-side countdown timer (a refresh or a lost connection cannot reset it), section tabs, question palette (not visited / not answered / answered / marked / answered and marked), MCQ, MSQ and NAT with an on-screen keypad, Mark for Review, Clear Response, Save & Next, scientific calculator, autosave, auto-submit at time end, answers never sent to the browser before submitting.

**Result (`/exam-result/<attempt>`)**: score with negative marking, attempted / correct / wrong / skipped, accuracy, time used, analysis by subject, section, topic (weakest first) and question type, advice, and a review of every question with the correct answer, explanation and time spent. Past papers and results are listed under "My exam papers".

Files: `services/exam_data.py` (catalog, built-in syllabus and patterns), `services/exams.py` (engine), `exam_routes.py`, `templates/exams.html`, `exam_hall.html`, `exam_result.html`, `_exam_picker.html`, `static/js/examtools.js`, `examhall.js`, `examresult.js`, edits to `paper.html`, `base.html`, `services/websearch.py` (longer pages for syllabus reading), `app.py`, `school_routes.py`.
Needs `GROQ_API_KEY` (writes the papers) and `TAVILY_API_KEY` (reads the official pages; without it the built-in syllabus or AI knowledge is used and the page says so).
