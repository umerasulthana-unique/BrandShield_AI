"""Automated integration tests for BrandShield AI's core workflow.

Run with: python -m unittest discover -s tests -v
The test database is isolated from the developer's normal database.
"""
import os
import tempfile
import unittest

_DB_HANDLE = tempfile.NamedTemporaryFile(prefix="brandshield-test-", suffix=".db", delete=False)
_DB_HANDLE.close()
os.environ["BRANDSHIELD_DB"] = _DB_HANDLE.name
os.environ["BRANDSHIELD_DEMO"] = "1"
os.environ["SECRET_KEY"] = "automated-test-secret-not-for-production"

import app as brandshield  # noqa: E402


class BrandShieldWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(prefix="brandshield-case-", suffix=".db", delete=False)
        self.temp_db.close()
        brandshield.DB_PATH = self.temp_db.name
        brandshield.init_db()
        self.client = brandshield.app.test_client()
        self.client.testing = True
        with brandshield.connect() as db:
            # Use the seeded sample draft for each test; tests do not assume its ID.
            self.draft_id = db.execute("SELECT id FROM drafts ORDER BY id LIMIT 1").fetchone()[0]

    def token(self):
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            return sess["csrf"]

    def post(self, path, data=None, **kw):
        data = dict(data or {})
        data["csrf_token"] = self.token()
        return self.client.post(path, data=data, **kw)

    def login(self, email, password):
        return self.post("/login", {"email": email, "password": password}, follow_redirects=True)

    def test_health_and_landing(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")
        self.assertEqual(response.get_json()["database"], "connected")

    def test_invalid_login_rejected(self):
        response = self.post("/login", {"email": "creator@brandshield.demo", "password": "wrong"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"incorrect", response.data.lower())

    def test_login_does_not_allow_external_redirect(self):
        response = self.post("/login?next=https://evil.example", {"email": "creator@brandshield.demo", "password": "Creator123!"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")

    def test_creator_check_revision_and_latest_findings(self):
        self.login("creator@brandshield.demo", "Creator123!")
        response = self.post(f"/drafts/{self.draft_id}/check", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Flagged wording", response.data)
        response = self.post(f"/drafts/{self.draft_id}/revise", {"body": "A gentle daily serum for customers.", "note": "Removed risky claims"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        response = self.post(f"/drafts/{self.draft_id}/check", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No matches found in the latest check", response.data)
        self.assertIn(b"Version 2", response.data)

    def test_creator_cannot_manage_rules_or_make_review_decision(self):
        self.login("creator@brandshield.demo", "Creator123!")
        self.assertEqual(self.post("/rules", {"title":"x"}).status_code, 403)
        self.assertEqual(self.post(f"/drafts/{self.draft_id}/decision", {"decision":"approved"}).status_code, 403)

    def test_reviewer_can_record_decision(self):
        self.login("reviewer@brandshield.demo", "Reviewer123!")
        # A reviewer must check the current revision before deciding.
        self.post(f"/drafts/{self.draft_id}/check", follow_redirects=True)
        response = self.post(f"/drafts/{self.draft_id}/decision", {"decision":"approved", "comment":"Reviewed for demo"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with brandshield.connect() as db:
            status = db.execute("SELECT status FROM drafts WHERE id=?", (self.draft_id,)).fetchone()[0]
            decision = db.execute("SELECT decision FROM decisions WHERE draft_id=? ORDER BY id DESC LIMIT 1", (self.draft_id,)).fetchone()[0]
        self.assertEqual(status, "approved")
        self.assertEqual(decision, "approved")

    def test_reviewer_cannot_edit_creator_draft(self):
        self.login("reviewer@brandshield.demo", "Reviewer123!")
        response = self.post(f"/drafts/{self.draft_id}/revise", {"body":"Unauthorized edit"})
        self.assertEqual(response.status_code, 403)

    def test_rule_can_be_added_and_disabled(self):
        self.login("admin@brandshield.demo", "Admin123!")
        response = self.post("/rules", {"title":"Test rule", "category":"Custom", "match_text":"test phrase", "explanation":"Test reason", "suggestion":"Test suggestion"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with brandshield.connect() as db:
            rule_id = db.execute("SELECT id FROM rules WHERE title='Test rule'").fetchone()[0]
        response = self.post(f"/rules/{rule_id}/toggle", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with brandshield.connect() as db:
            active = db.execute("SELECT active FROM rules WHERE id=?", (rule_id,)).fetchone()[0]
        self.assertEqual(active, 0)

    def test_review_decision_requires_latest_version_check(self):
        self.login("reviewer@brandshield.demo", "Reviewer123!")
        response = self.post(f"/drafts/{self.draft_id}/decision", {"decision":"approved"}, follow_redirects=True)
        self.assertIn(b"run a rule check", response.data.lower())
        with brandshield.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM decisions WHERE draft_id=?", (self.draft_id,)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_invalid_decision_rejected(self):
        self.login("reviewer@brandshield.demo", "Reviewer123!")
        response = self.post(f"/drafts/{self.draft_id}/decision", {"decision":"maybe"})
        self.assertEqual(response.status_code, 400)

    def test_post_without_csrf_token_is_rejected(self):
        response = self.client.post("/login", data={"email": "creator@brandshield.demo", "password": "Creator123!"})
        self.assertEqual(response.status_code, 400)

    def test_quick_check_flags_all_occurrences_and_saves_nothing(self):
        self.login("creator@brandshield.demo", "Creator123!")
        with brandshield.connect() as db:
            before = db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
        response = self.post("/quick-check", {"body": "We guarantee it. Yes, we GUARANTEE it. Consumers agree!!!"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"3 possible issues", response.data)
        self.assertIn(b"\xc3\x972", response.data)  # x2 occurrences badge for 'guarantee'
        self.assertIn(b'<mark class="hl">', response.data)
        with brandshield.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0], before)

    def test_quick_check_escapes_html(self):
        self.login("creator@brandshield.demo", "Creator123!")
        response = self.post("/quick-check", {"body": "<script>alert(1)</script> guarantee"})
        self.assertNotIn(b"<script>alert(1)</script>", response.data)

    def test_draft_body_highlights_flagged_words_after_check(self):
        self.login("creator@brandshield.demo", "Creator123!")
        self.post(f"/drafts/{self.draft_id}/check")
        page = self.client.get(f"/drafts/{self.draft_id}").data
        self.assertIn(b'<mark class="hl">guarantees</mark>', page)

    def test_every_page_loads_for_every_role(self):
        for email, pw in [("creator@brandshield.demo","Creator123!"),("reviewer@brandshield.demo","Reviewer123!"),("admin@brandshield.demo","Admin123!")]:
            self.client = brandshield.app.test_client()
            self.login(email, pw)
            for path in ["/dashboard", "/rules", "/quick-check", f"/drafts/{self.draft_id}"]:
                self.assertEqual(self.client.get(path).status_code, 200, (email, path))

    def test_anonymous_users_are_sent_to_login(self):
        for path in ["/dashboard", "/rules", "/quick-check", "/drafts/new", f"/drafts/{self.draft_id}"]:
            self.assertEqual(self.client.get(path).status_code, 302, path)

    def test_admin_can_add_user_who_can_sign_in(self):
        self.login("admin@brandshield.demo", "Admin123!")
        response = self.post("/team", {"name": "New Person", "email": "new@example.com", "role": "reviewer", "password": "longenough1"}, follow_redirects=True)
        self.assertIn(b"can now sign in", response.data)
        self.client = brandshield.app.test_client()
        response = self.login("new@example.com", "longenough1")
        self.assertIn(b"Good to see you", response.data)

    def test_team_page_is_admin_only_and_validates(self):
        self.login("creator@brandshield.demo", "Creator123!")
        self.assertEqual(self.client.get("/team").status_code, 403)
        self.assertEqual(self.post("/team", {"name": "x", "email": "x@x.com", "role": "admin", "password": "longenough1"}).status_code, 403)
        self.client = brandshield.app.test_client()
        self.login("admin@brandshield.demo", "Admin123!")
        short = self.post("/team", {"name": "A", "email": "a@example.com", "role": "creator", "password": "short"}, follow_redirects=True)
        self.assertIn(b"at least 8", short.data)
        dup = self.post("/team", {"name": "Dup", "email": "creator@brandshield.demo", "role": "creator", "password": "longenough1"}, follow_redirects=True)
        self.assertIn(b"already exists", dup.data)

    def test_production_mode_has_no_demo_accounts_and_bootstraps_admin(self):
        import subprocess, sys, tempfile, textwrap
        db = tempfile.NamedTemporaryFile(suffix=".db", delete=False); db.close()
        code = textwrap.dedent("""
            import app as b
            c = b.app.test_client()
            page = c.get('/login').data
            assert b'Use creator' not in page and b'brandshield.demo' not in page
            with b.connect() as d:
                users = [r[0] for r in d.execute('SELECT email FROM users')]
                assert users == ['owner@example.com'], users
                assert d.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 0
                assert d.execute('SELECT COUNT(*) FROM rules').fetchone()[0] == 5
            print('OK')
        """)
        env = dict(os.environ, BRANDSHIELD_DB=db.name, BRANDSHIELD_DEMO="0", ADMIN_EMAIL="owner@example.com", ADMIN_PASSWORD="OwnerPass123!", SECRET_KEY="x" * 40)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-c", code], env=env, cwd=root, capture_output=True, text=True)
        os.unlink(db.name)
        self.assertIn("OK", out.stdout, out.stderr)

    def tearDown(self):
        try:
            os.unlink(self.temp_db.name)
        except OSError:
            pass

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_DB_HANDLE.name)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
