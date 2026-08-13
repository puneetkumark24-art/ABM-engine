"""test_inbound.py — bounce parsing, reply detection, and the ACC-001 cascade.

Runs on SQLite and PostgreSQL like the other suites. No network, no Gmail
credentials: `poll_once()` takes an injectable fetcher, so the full path is
exercised against RFC-822 fixtures.

The load-bearing test here is `test_email_reply_triggers_acc001_cascade` —
before this module, an email reply never reached `pause_on_reply`, so the
platform would keep auto-touching a bank that had already replied.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime

# Must precede the database import — same convention as the other suites.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Base, SessionLocal, engine  # noqa: E402
import models as core_models  # noqa: E402
import models_ext as mx  # noqa: E402
from abm_platform.services import inbound  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────
HARD_BOUNCE = b"""From: MAILER-DAEMON@bank.com.sa
To: puneet@outreach.example.com
Subject: Undelivered Mail Returned to Sender
Content-Type: multipart/report; report-type=delivery-status; boundary="B1"

--B1
Content-Type: text/plain

Your message could not be delivered.

--B1
Content-Type: message/delivery-status

Final-Recipient: rfc822; cio@bank.com.sa
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 User unknown

--B1
Content-Type: message/rfc822

Message-ID: <msg-hard-001@outreach.example.com>
To: cio@bank.com.sa
Subject: Vahana

--B1--
"""

SOFT_BOUNCE = b"""From: MAILER-DAEMON@bank.com.sa
To: puneet@outreach.example.com
Subject: Delivery delayed
Content-Type: multipart/report; report-type=delivery-status; boundary="B2"

--B2
Content-Type: message/delivery-status

Final-Recipient: rfc822; cto@bank.com.sa
Action: delayed
Status: 4.2.2
Diagnostic-Code: smtp; 452 4.2.2 Mailbox full

--B2
Content-Type: message/rfc822

Message-ID: <msg-soft-001@outreach.example.com>
To: cto@bank.com.sa

--B2--
"""

# No Status: header at all — the heuristic path many real MTAs force.
UNSTRUCTURED_BOUNCE = b"""From: postmaster@bank.com.sa
To: puneet@outreach.example.com
Subject: Returned mail
Content-Type: text/plain

Delivery to the following recipient failed permanently:

     head.digital@bank.com.sa

Technical details: The email account that you tried to reach does not exist.
"""

REPLY = b"""From: Mazen Pharaon <mazen@bank.com.sa>
To: puneet@outreach.example.com
Subject: Re: Vahana for your origination stack
In-Reply-To: <msg-reply-001@outreach.example.com>
Content-Type: text/plain

Interesting - can you send over the integration details?
"""

OOO = b"""From: Mazen Pharaon <mazen@bank.com.sa>
To: puneet@outreach.example.com
Subject: Automatic reply: Vahana for your origination stack
Auto-Submitted: auto-replied
Content-Type: text/plain

I am out of the office until Sunday.
"""


def fetcher_for(*items):
    def _f():
        return list(items)
    return _f


class InboundTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        self.org = core_models.Organization(canonical_name="Test Bank KSA")
        self.db.add(self.org)
        self.db.flush()
        self.person = core_models.Person(
            full_name="Mazen Pharaon", primary_email="mazen@bank.com.sa",
            current_org_id=self.org.id)
        self.db.add(self.person)
        self.db.add(mx.SendRequest(
            message_id="msg-reply-001", to_email="mazen@bank.com.sa",
            subject="Vahana", body="hello", status="sent",
            created_at=datetime.utcnow()))
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        # `DELETE FROM persons` fails outright on PostgreSQL if ANY row in a
        # referencing table still points at a person -- including rows another
        # suite left behind in the same shared database. Running the
        # email-lifecycle suite first turned all 18 tests here red with
        # ForeignKeyViolation (first on drafts, then on touches), while this
        # suite passed perfectly on a fresh database. SQLite never enforced the
        # constraint, so it stayed invisible until CI moved to PostgreSQL.
        #
        # purge_all() deletes in reverse dependency order derived from the
        # schema itself, so it does not need updating when a new table gains a
        # person_id.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _dbclean import purge_all
        purge_all(self.db)
        self.db.close()

    # ── classification ────────────────────────────────────────
    def test_hard_bounce_is_permanent(self):
        im = inbound.classify(HARD_BOUNCE, "u1")
        self.assertEqual(im.kind, "bounce")
        self.assertTrue(im.bounce_permanent)
        self.assertEqual(im.bounce_status, "5.1.1")

    def test_soft_bounce_is_transient(self):
        im = inbound.classify(SOFT_BOUNCE, "u2")
        self.assertEqual(im.kind, "bounce")
        self.assertFalse(im.bounce_permanent)

    def test_unstructured_bounce_caught_by_heuristic(self):
        """No Status: header. A structured-only parser misses this and keeps
        mailing a dead address forever."""
        im = inbound.classify(UNSTRUCTURED_BOUNCE, "u3")
        self.assertEqual(im.kind, "bounce")
        self.assertTrue(im.bounce_permanent)

    def test_auto_reply_not_classified_as_reply(self):
        im = inbound.classify(OOO, "u4")
        self.assertEqual(im.kind, "auto_reply")

    def test_reply_classified_as_reply(self):
        im = inbound.classify(REPLY, "u5")
        self.assertEqual(im.kind, "reply")

    # ── suppression ───────────────────────────────────────────
    def test_hard_bounce_suppresses_immediately(self):
        inbound.poll_once(self.db, fetcher_for(("u1", HARD_BOUNCE)))
        s = self.db.query(mx.Suppression).filter_by(email="cio@bank.com.sa").first()
        self.assertIsNotNone(s, "hard bounce must suppress (DEL-003)")

    def test_soft_bounce_does_not_suppress_on_first_hit(self):
        inbound.poll_once(self.db, fetcher_for(("u2", SOFT_BOUNCE)))
        s = self.db.query(mx.Suppression).filter_by(email="cto@bank.com.sa").first()
        self.assertIsNone(s, "one full mailbox is not a dead address")

    # ── the gap this module closes ────────────────────────────
    def test_email_reply_triggers_acc001_cascade(self):
        """Before inbound.py this never happened for email: pause_on_reply was
        reachable from LinkedIn and manual logging only."""
        self.assertFalse(self.person.replied)
        counts = inbound.poll_once(self.db, fetcher_for(("u5", REPLY)))
        self.assertEqual(counts["reply"], 1)
        self.db.refresh(self.person)
        self.assertTrue(self.person.replied,
                        "email reply must flip person.replied and pause the account")

    def test_auto_reply_does_not_trigger_cascade(self):
        """An out-of-office is not interest. Treating it as a reply would both
        corrupt engagement scoring and wrongly halt the sequence."""
        inbound.poll_once(self.db, fetcher_for(("u4", OOO)))
        self.db.refresh(self.person)
        self.assertFalse(self.person.replied)

    def test_reply_matched_to_send_via_in_reply_to(self):
        inbound.poll_once(self.db, fetcher_for(("u5", REPLY)))
        ev = self.db.query(mx.DeliveryEvent).filter_by(event_type="reply").first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.message_id, "msg-reply-001")

    # ── idempotency ───────────────────────────────────────────
    def test_same_message_polled_twice_is_deduped(self):
        f = fetcher_for(("u1", HARD_BOUNCE))
        inbound.poll_once(self.db, f)
        second = inbound.poll_once(self.db, f)
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(
            self.db.query(mx.DeliveryEvent).filter_by(
                provider_event_id="inbound:u1").count(), 1)

    def test_malformed_message_does_not_stop_batch(self):
        counts = inbound.poll_once(self.db, fetcher_for(
            ("bad", b"\xff\xfe not a message at all"),
            ("u5", REPLY)))
        self.assertEqual(counts["reply"], 1, "good message after a bad one still processes")
        self.assertEqual(counts["unknown"], 1)

    def test_garbage_is_not_counted_as_a_reply(self):
        """Python's email parser accepts arbitrary bytes, so without an explicit
        guard corrupt mail lands in the reply branch and halts outreach to a
        whole bank via ACC-001. A false reply is far more costly than a missed
        one."""
        counts = inbound.poll_once(self.db, fetcher_for(
            ("junk", b"\x00\x01\x02 no headers here")))
        self.assertEqual(counts["reply"], 0)
        self.assertEqual(counts["unknown"], 1)
        self.db.refresh(self.person)
        self.assertFalse(self.person.replied)


class TransportRegistrationTests(unittest.TestCase):
    """Fail-closed: no transport registers without explicit opt-in."""

    def test_gmail_stays_dry_run_without_env_flag(self):
        from abm_platform.services import delivery_gmail
        os.environ.pop("ENABLE_GMAIL_TRANSPORT", None)
        ok, detail = delivery_gmail.try_register_gmail()
        self.assertFalse(ok)
        self.assertIn("dry-run", detail)

    def test_m365_stays_dry_run_without_env_flag(self):
        from abm_platform.services import delivery_gmail
        os.environ.pop("ENABLE_M365_TRANSPORT", None)
        ok, detail = delivery_gmail.try_register_m365()
        self.assertFalse(ok)
        self.assertIn("dry-run", detail)

    def test_register_all_is_safe_to_call(self):
        from abm_platform.services import delivery_gmail
        results = delivery_gmail.register_all()
        self.assertEqual(set(results), {"gmail", "microsoft_365"})
        for v in results.values():
            self.assertTrue(v.startswith("skipped:"))

    def test_mime_has_plain_text_part(self):
        """HTML-only bodies are a spam signal."""
        from abm_platform.services import delivery_gmail
        req = mx.SendRequest(message_id="m1", to_email="a@b.com",
                             subject="Hi", body="<p>Hello <b>there</b></p>")
        mime = delivery_gmail._build_mime(req, "me@outreach.example.com")
        types = [p.get_content_type() for p in mime.walk()]
        self.assertIn("text/plain", types)
        self.assertIn("text/html", types)

    def test_mime_has_no_tracking_pixel(self):
        from abm_platform.services import delivery_gmail
        req = mx.SendRequest(message_id="m2", to_email="a@b.com",
                             subject="Hi", body="Plain body")
        raw = delivery_gmail._build_mime(req, "me@outreach.example.com").as_string()
        self.assertNotIn("/t/o/", raw, "transport must not inject tracking by default")


if __name__ == "__main__":
    unittest.main(verbosity=2)
