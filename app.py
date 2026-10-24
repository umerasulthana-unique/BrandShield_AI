import os, re, sqlite3, secrets, hashlib, hmac, json
from datetime import datetime, timezone
from urllib.parse import urlparse
from functools import wraps
from markupsafe import Markup, escape
from flask import Flask, request, session, redirect, url_for, render_template, flash, abort, jsonify, make_response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("BRANDSHIELD_DB", os.path.join(BASE_DIR, "brandshield.db"))
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-this-secret-before-deployment")
DEMO_MODE = os.environ.get("BRANDSHIELD_DEMO", "0") == "1"
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=1_000_000,
                  SESSION_COOKIE_SECURE=os.environ.get("BRANDSHIELD_SECURE_COOKIES", "0") == "1")
if app.secret_key.startswith("dev-only") and not DEMO_MODE:
    print("WARNING: set a strong SECRET_KEY environment variable before going live.")

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
    return salt + "$" + digest

def verify_password(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
        return hmac.compare_digest(actual, digest)
    except Exception:
        return False

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('creator','reviewer','admin'))
        );
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
            match_text TEXT NOT NULL, explanation TEXT NOT NULL, suggestion TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_by INTEGER, created_at TEXT NOT NULL,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, channel TEXT NOT NULL,
            body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
            created_by INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            last_checked_revision_id INTEGER,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY, draft_id INTEGER NOT NULL, version INTEGER NOT NULL,
            body TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL, FOREIGN KEY(draft_id) REFERENCES drafts(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS findings (
            id INTEGER PRIMARY KEY, draft_id INTEGER NOT NULL, revision_id INTEGER NOT NULL,
            rule_id INTEGER NOT NULL, flagged_text TEXT NOT NULL, category TEXT NOT NULL,
            explanation TEXT NOT NULL, suggestion TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(draft_id) REFERENCES drafts(id), FOREIGN KEY(revision_id) REFERENCES revisions(id),
            FOREIGN KEY(rule_id) REFERENCES rules(id)
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY, draft_id INTEGER NOT NULL, reviewer_id INTEGER NOT NULL,
            decision TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            FOREIGN KEY(draft_id) REFERENCES drafts(id), FOREIGN KEY(reviewer_id) REFERENCES users(id)
        );
        """)
        # Lightweight schema migration for databases created by earlier builds.
        draft_columns = {row[1] for row in db.execute("PRAGMA table_info(drafts)").fetchall()}
        if "last_checked_revision_id" not in draft_columns:
            db.execute("ALTER TABLE drafts ADD COLUMN last_checked_revision_id INTEGER")
        finding_columns = {row[1] for row in db.execute("PRAGMA table_info(findings)").fetchall()}
        if "occurrences" not in finding_columns:
            db.execute("ALTER TABLE findings ADD COLUMN occurrences INTEGER NOT NULL DEFAULT 1")
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            if DEMO_MODE:
                for name, email, pw, role in [("Demo Creator", "creator@brandshield.demo", "Creator123!", "creator"),
                                              ("Demo Reviewer", "reviewer@brandshield.demo", "Reviewer123!", "reviewer"),
                                              ("Demo Admin", "admin@brandshield.demo", "Admin123!", "admin")]:
                    db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)", (name, email, hash_password(pw), role))
            elif os.environ.get("ADMIN_EMAIL") and os.environ.get("ADMIN_PASSWORD"):
                db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,'admin')",
                           (os.environ.get("ADMIN_NAME", "Admin"), os.environ["ADMIN_EMAIL"].strip().lower(), hash_password(os.environ["ADMIN_PASSWORD"])))
            else:
                print("NOTE: no users exist. Set ADMIN_EMAIL and ADMIN_PASSWORD, then restart, to create the first admin.")
        first_user = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if first_user and db.execute("SELECT COUNT(*) FROM rules").fetchone()[0] == 0:
            owner_id = first_user[0]
            seeds = [
                ("No guaranteed outcomes", "Claims", "guarantee", "Avoid promising guaranteed outcomes unless the approved guide explicitly permits it.", "Describe the supported benefit without promising a guaranteed result."),
                ("No unsupported product claim", "Product facts", "clinically proven", "This phrase can imply evidence that may not be present in the approved product record.", "Confirm the approved evidence before keeping this claim."),
                ("Calm, helpful tone", "Tone", "!!!", "Multiple exclamation marks may conflict with the calm, helpful tone guideline.", "Use a clear, friendly call to action."),
                ("Avoid absolute language", "Claims", "100% safe", "Absolute safety claims require substantiation and may be misleading.", "Use a precise, approved description and request human review."),
                ("Preferred term: customers", "Terminology", "consumers", "The brand guide prefers the term 'customers'.", "Replace 'consumers' with 'customers' where appropriate.")
            ]
            for title,cat,match,why,suggest in seeds:
                db.execute("INSERT INTO rules(title,category,match_text,explanation,suggestion,active,created_by,created_at) VALUES(?,?,?,?,?,1,?,?)",
                           (title,cat,match,why,suggest,owner_id,now()))
        if DEMO_MODE and db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0:
            cid = db.execute("SELECT id FROM users WHERE email='creator@brandshield.demo'").fetchone()[0]
            sample = "Our serum guarantees perfect skin in 3 days!!! Consumers will love this 100% safe formula."
            cur = db.execute("INSERT INTO drafts(title,channel,body,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                             ("Serum launch post", "Social media", sample, "draft", cid, now(), now()))
            db.execute("INSERT INTO revisions(draft_id,version,body,note,created_by,created_at) VALUES(?,?,?,?,?,?)",
                       (cur.lastrowid,1,sample,"Sample draft",cid,now()))

init_db()

def current_user():
    if not session.get("user_id"):
        return None
    with connect() as db:
        return db.execute("SELECT id,name,email,role FROM users WHERE id=?", (session["user_id"],)).fetchone()

@app.context_processor
def inject_user():
    return {"current_user": current_user(), "year": datetime.now().year, "demo_mode": DEMO_MODE}

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]

app.jinja_env.globals["csrf_token"] = csrf_token

@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            abort(400)

def run_rules(db, body):
    """Transparent phrase matching. Returns one dict per active rule that matches."""
    results = []
    for rule in db.execute("SELECT * FROM rules WHERE active=1 ORDER BY id").fetchall():
        matches = list(re.finditer(re.escape(rule["match_text"]), body, re.IGNORECASE))
        if matches:
            results.append({"rule_id": rule["id"], "rule_title": rule["title"], "flagged_text": matches[0].group(0),
                            "match_text": rule["match_text"], "category": rule["category"],
                            "explanation": rule["explanation"], "suggestion": rule["suggestion"],
                            "occurrences": len(matches)})
    return results

def highlight(body, needles):
    """Escape the text and wrap every flagged phrase in <mark>."""
    needles = sorted({n for n in needles if n}, key=len, reverse=True)
    if not needles:
        return escape(body)
    def expand(n):
        # Highlight whole words: "guarantee" also covers "guarantees".
        return (r"\w*" if n[0].isalnum() or n[0] == "_" else "") + re.escape(n) + (r"\w*" if n[-1].isalnum() or n[-1] == "_" else "")
    pattern = re.compile("|".join(expand(n) for n in needles), re.IGNORECASE)
    out, last = [], 0
    for m in pattern.finditer(body):
        out.append(escape(body[last:m.start()]))
        out.append(Markup('<mark class="hl">') + escape(m.group(0)) + Markup("</mark>"))
        last = m.end()
    out.append(escape(body[last:]))
    return Markup("").join(out)

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped

def roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("login", next=request.path))
            if user["role"] not in allowed:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def get_draft(db, draft_id):
    row = db.execute("""SELECT d.*,u.name AS creator_name FROM drafts d
        JOIN users u ON u.id=d.created_by WHERE d.id=?""", (draft_id,)).fetchone()
    if not row: abort(404)
    return row

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; script-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response

@app.route("/")
def index():
    if current_user(): return redirect(url_for("dashboard"))
    return render_template("landing.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        with connect() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and verify_password(password, user["password_hash"]):
            session.clear()
            session["user_id"] = user["id"]
            flash("Welcome back. Your workspace is ready.", "success")
            next_url = request.args.get("next", "")
            parsed_next = urlparse(next_url)
            # Only allow a local path; never redirect to an attacker-controlled host.
            if next_url.startswith("/") and not next_url.startswith("//") and not parsed_next.netloc:
                return redirect(next_url)
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    with connect() as db:
        stats = {
            "drafts": db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0],
            "needs_review": db.execute("SELECT COUNT(*) FROM drafts WHERE status IN ('needs_review','changes_requested')").fetchone()[0],
            "approved": db.execute("SELECT COUNT(*) FROM drafts WHERE status='approved'").fetchone()[0],
            "rules": db.execute("SELECT COUNT(*) FROM rules WHERE active=1").fetchone()[0],
        }
        query = """SELECT d.*,u.name AS creator_name FROM drafts d JOIN users u ON u.id=d.created_by"""
        params = []
        if user["role"] == "creator":
            query += " WHERE d.created_by=?"; params.append(user["id"])
        query += " ORDER BY d.updated_at DESC LIMIT 12"
        drafts = db.execute(query, params).fetchall()
        activity = db.execute("""SELECT de.*,d.title,u.name AS reviewer_name FROM decisions de
            JOIN drafts d ON d.id=de.draft_id JOIN users u ON u.id=de.reviewer_id
            ORDER BY de.created_at DESC LIMIT 5""").fetchall()
    return render_template("dashboard.html", stats=stats, drafts=drafts, activity=activity)

@app.route("/rules", methods=["GET","POST"])
@login_required
def rules_page():
    if request.method == "POST":
        if current_user()["role"] not in ("admin","reviewer"):
            abort(403)
        title=request.form.get("title","").strip()
        category=request.form.get("category","").strip()
        match_text=request.form.get("match_text","").strip()
        explanation=request.form.get("explanation","").strip()
        suggestion=request.form.get("suggestion","").strip()
        if not all([title,category,match_text,explanation,suggestion]) or len(match_text)>120:
            flash("Complete every field. Match text must be 120 characters or fewer.", "error")
        else:
            with connect() as db:
                db.execute("INSERT INTO rules(title,category,match_text,explanation,suggestion,active,created_by,created_at) VALUES(?,?,?,?,?,1,?,?)",
                           (title,category,match_text,explanation,suggestion,current_user()["id"],now()))
            flash("Rule added to the shared rulebook.", "success")
        return redirect(url_for("rules_page"))
    with connect() as db:
        rules = db.execute("SELECT r.*,u.name AS author FROM rules r LEFT JOIN users u ON u.id=r.created_by ORDER BY r.active DESC,r.id DESC").fetchall()
    return render_template("rules.html", rules=rules)

@app.post("/rules/<int:rule_id>/toggle")
@roles("admin","reviewer")
def toggle_rule(rule_id):
    with connect() as db:
        rule=db.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
        if not rule: abort(404)
        db.execute("UPDATE rules SET active=? WHERE id=?", (0 if rule["active"] else 1, rule_id))
    flash("Rule status updated.", "success")
    return redirect(url_for("rules_page"))

@app.route("/drafts/new", methods=["GET","POST"])
@roles("creator","admin")
def new_draft():
    if request.method == "POST":
        title=request.form.get("title","").strip()
        channel=request.form.get("channel","Social media").strip()
        body=request.form.get("body","").strip()
        if not title or not body or len(title)>160 or len(body)>20000:
            flash("Add a title and draft text (maximum 20,000 characters).", "error")
        else:
            with connect() as db:
                cur=db.execute("INSERT INTO drafts(title,channel,body,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                               (title,channel,body,"draft",current_user()["id"],now(),now()))
                did=cur.lastrowid
                db.execute("INSERT INTO revisions(draft_id,version,body,note,created_by,created_at) VALUES(?,?,?,?,?,?)",
                           (did,1,body,"Initial draft",current_user()["id"],now()))
            flash("Draft created. Run a check to identify possible issues.", "success")
            return redirect(url_for("draft_detail", draft_id=did))
    return render_template("draft_form.html", draft=None)

@app.route("/drafts/<int:draft_id>")
@login_required
def draft_detail(draft_id):
    user=current_user()
    with connect() as db:
        draft=get_draft(db,draft_id)
        if user["role"]=="creator" and draft["created_by"]!=user["id"]: abort(403)
        latest_revision=db.execute("SELECT id FROM revisions WHERE draft_id=? ORDER BY version DESC LIMIT 1",(draft_id,)).fetchone()
        checked_current = bool(latest_revision and draft["last_checked_revision_id"] == latest_revision["id"])
        findings=[]
        if latest_revision:
            findings=db.execute("""SELECT f.*,r.title AS rule_title FROM findings f JOIN rules r ON r.id=f.rule_id
                WHERE f.draft_id=? AND f.revision_id=? ORDER BY f.id DESC""",(draft_id,latest_revision["id"])).fetchall()
        revisions=db.execute("""SELECT rv.*,u.name AS author FROM revisions rv JOIN users u ON u.id=rv.created_by
            WHERE rv.draft_id=? ORDER BY rv.version DESC""",(draft_id,)).fetchall()
        decisions=db.execute("""SELECT de.*,u.name AS reviewer_name FROM decisions de JOIN users u ON u.id=de.reviewer_id
            WHERE de.draft_id=? ORDER BY de.id DESC""",(draft_id,)).fetchall()
        active_rules=db.execute("SELECT COUNT(*) FROM rules WHERE active=1").fetchone()[0]
    shown = highlight(draft["body"], [f["flagged_text"] for f in findings]) if checked_current else escape(draft["body"])
    return render_template("draft_detail.html", draft=draft, findings=findings, revisions=revisions, decisions=decisions, active_rules=active_rules, checked_current=checked_current, shown_body=shown)

@app.post("/drafts/<int:draft_id>/check")
@login_required
def check_draft(draft_id):
    user=current_user()
    with connect() as db:
        draft=get_draft(db,draft_id)
        if user["role"]=="creator" and draft["created_by"]!=user["id"]: abort(403)
        revision=db.execute("SELECT * FROM revisions WHERE draft_id=? ORDER BY version DESC LIMIT 1",(draft_id,)).fetchone()
        body=revision["body"]
        db.execute("DELETE FROM findings WHERE draft_id=? AND revision_id=?",(draft_id,revision["id"]))
        found=run_rules(db, body)
        matches=len(found)
        for f in found:
            db.execute("""INSERT INTO findings(draft_id,revision_id,rule_id,flagged_text,category,explanation,suggestion,created_at,occurrences)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (draft_id,revision["id"],f["rule_id"],f["flagged_text"],f["category"],f["explanation"],f["suggestion"],now(),f["occurrences"]))
        status="needs_review" if matches else "ready_for_review"
        db.execute("UPDATE drafts SET status=?,updated_at=?,last_checked_revision_id=? WHERE id=?",(status,now(),revision["id"],draft_id))
    flash(f"Check complete: {matches} possible issue(s) found. This is a rule-based check, not proof of a factual or legal problem.", "success")
    return redirect(url_for("draft_detail",draft_id=draft_id))

@app.post("/drafts/<int:draft_id>/revise")
@roles("creator","admin")
def revise_draft(draft_id):
    user=current_user()
    body=request.form.get("body","").strip()
    note=request.form.get("note","").strip() or "Creator revision"
    if not body or len(body)>20000:
        flash("Draft text is required and must be under 20,000 characters.", "error")
        return redirect(url_for("draft_detail",draft_id=draft_id))
    with connect() as db:
        draft=get_draft(db,draft_id)
        if user["role"]=="creator" and draft["created_by"]!=user["id"]: abort(403)
        version=db.execute("SELECT COALESCE(MAX(version),0)+1 FROM revisions WHERE draft_id=?",(draft_id,)).fetchone()[0]
        db.execute("INSERT INTO revisions(draft_id,version,body,note,created_by,created_at) VALUES(?,?,?,?,?,?)",
                   (draft_id,version,body,note,user["id"],now()))
        db.execute("UPDATE drafts SET body=?,status='draft',updated_at=?,last_checked_revision_id=NULL WHERE id=?",(body,now(),draft_id))
    flash(f"Revision {version} saved. Run the checker again before review.", "success")
    return redirect(url_for("draft_detail",draft_id=draft_id))

@app.post("/drafts/<int:draft_id>/decision")
@roles("reviewer","admin")
def decision(draft_id):
    choice=request.form.get("decision","")
    comment=request.form.get("comment","").strip()
    if choice not in ("approved","rejected","changes_requested"): abort(400)
    with connect() as db:
        draft=get_draft(db,draft_id)
        latest_revision=db.execute("SELECT id FROM revisions WHERE draft_id=? ORDER BY version DESC LIMIT 1",(draft_id,)).fetchone()
        if not latest_revision or draft["last_checked_revision_id"] != latest_revision["id"]:
            flash("Please run a rule check on the latest version before recording a review decision.", "error")
            return redirect(url_for("draft_detail",draft_id=draft_id))
        db.execute("INSERT INTO decisions(draft_id,reviewer_id,decision,comment,created_at) VALUES(?,?,?,?,?)",
                   (draft_id,current_user()["id"],choice,comment,now()))
        db.execute("UPDATE drafts SET status=?,updated_at=? WHERE id=?",(choice,now(),draft_id))
    flash("Human review decision recorded.", "success")
    return redirect(url_for("draft_detail",draft_id=draft_id))

@app.route("/team", methods=["GET","POST"])
@roles("admin")
def team_page():
    if request.method == "POST":
        name=request.form.get("name","").strip()
        email=request.form.get("email","").strip().lower()
        role=request.form.get("role","")
        password=request.form.get("password","")
        if not name or "@" not in email or role not in ("creator","reviewer","admin") or len(password) < 8 or len(name) > 100 or len(email) > 160:
            flash("Enter a name, a valid email, a role and a password of at least 8 characters.", "error")
        else:
            try:
                with connect() as db:
                    db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)", (name,email,hash_password(password),role))
                flash(f"{name} can now sign in as {role}.", "success")
            except sqlite3.IntegrityError:
                flash("A user with that email already exists.", "error")
        return redirect(url_for("team_page"))
    with connect() as db:
        users = db.execute("SELECT id,name,email,role FROM users ORDER BY id").fetchall()
    return render_template("team.html", users=users)

@app.route("/quick-check", methods=["GET","POST"])
@login_required
def quick_check():
    body = request.form.get("body", "").strip() if request.method == "POST" else ""
    findings, shown = None, None
    if request.method == "POST":
        if not body or len(body) > 20000:
            flash("Paste some text to check (maximum 20,000 characters).", "error")
            body = ""
        else:
            with connect() as db:
                findings = run_rules(db, body)
            shown = highlight(body, [f["flagged_text"] for f in findings])
    return render_template("quick_check.html", body=body, findings=findings, shown_body=shown)

@app.route("/api/health")
def health():
    with connect() as db:
        db.execute("SELECT 1")
    return jsonify({"status":"ok","service":"BrandShield AI","database":"connected","time":now()})

@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message="You do not have permission to perform this action."),403
@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, message="That page or record could not be found."),404

@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message="That request could not be verified. Go back, refresh the page and try again."),400
@app.errorhandler(405)
def bad_method(error):
    return render_template("error.html", code=405, message="That action is not available here."),405
@app.errorhandler(500)
def server_error(error):
    return render_template("error.html", code=500, message="Something went wrong on our side. Please try again."),500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if os.environ.get("BRANDSHIELD_OPEN") == "1":
        import threading, webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"\n  BrandShield AI is running ->  http://127.0.0.1:{port}\n  Press Ctrl+C to stop.\n")
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=port, debug=False)
