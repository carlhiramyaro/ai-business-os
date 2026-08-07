"""v0.6 slice 2: app/insight_delivery.py. deliver_immediate/
collect_and_queue_digests both end by enqueueing app.tasks.
send_outbound_message_task -- its `.delay` is monkeypatched to a spy so
these tests verify the QUEUEING/bundling/windowing logic in isolation
from actual delivery (already covered by tests/test_outbound.py), using
the ordinary SAVEPOINT-rollback db_session fixture rather than a real-
commit one, since nothing here needs the task to actually run."""

import uuid
from datetime import date, datetime, timedelta, timezone

import app.tasks as tasks
from app.insight_delivery import collect_and_queue_digests, compose_digest_message, deliver_immediate
from app.models import Business, ChannelIdentity, Insight, OutboundMessage, User
from app.security import hash_password

TODAY = date(2026, 3, 1)


def _create_user_business(db):
    user = User(full_name="Owner", email=f"{uuid.uuid4()}@example.com", password_hash=hash_password("pw"))
    db.add(user)
    db.flush()
    business = Business(owner_id=user.id, business_name="Insight Delivery Co")
    db.add(business)
    db.flush()
    return user, business


def _identity(db, user, business, frequency, **kwargs):
    identity = ChannelIdentity(
        user_id=user.id,
        business_id=business.id,
        channel="whatsapp",
        external_id=kwargs.pop("external_id", f"2332412345{uuid.uuid4().hex[:2]}"),
        notification_frequency=frequency,
        **kwargs,
    )
    db.add(identity)
    db.flush()
    return identity


def _insight(db, business, title="Revenue up", body="Revenue rose 20% this week.", created_at=None):
    insight = Insight(
        business_id=business.id,
        insight_type="revenue_trend",
        severity="info",
        title=title,
        body=body,
        metrics={},
        fingerprint=uuid.uuid4().hex,
        period_start=TODAY - timedelta(days=6),
        period_end=TODAY,
    )
    db.add(insight)
    db.flush()
    if created_at is not None:
        db.query(Insight).filter(Insight.id == insight.id).update({"created_at": created_at})
        db.flush()
        db.refresh(insight)
    return insight


class _DelaySpy:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, outbound_message_id):
        self.calls.append(outbound_message_id)


# --- compose_digest_message: pure, deterministic ----------------------------


def test_compose_digest_message_lists_every_insight():
    insights = [
        Insight(title="A", body="Body A"),
        Insight(title="B", body="Body B"),
    ]
    text = compose_digest_message("Acme Co", insights)
    assert "Acme Co" in text
    assert "1. A" in text
    assert "Body A" in text
    assert "2. B" in text
    assert "Body B" in text


# --- deliver_immediate -------------------------------------------------------


def test_deliver_immediate_queues_one_bundled_message_per_immediate_identity(monkeypatch, db_session):
    spy = _DelaySpy()
    monkeypatch.setattr(tasks.send_outbound_message_task, "delay", spy)

    user, business = _create_user_business(db_session)
    immediate_identity = _identity(db_session, user, business, "immediate")
    _identity(db_session, user, business, "off", external_id="233240000001")
    insights = [_insight(db_session, business, title="A"), _insight(db_session, business, title="B")]

    deliver_immediate(db_session, business, insights)

    messages = db_session.query(OutboundMessage).filter(OutboundMessage.channel_identity_id == immediate_identity.id).all()
    assert len(messages) == 1
    assert messages[0].kind == "insight_immediate"
    assert "A" in messages[0].body and "B" in messages[0].body
    assert len(spy.calls) == 1


def test_deliver_immediate_skips_off_and_digest_identities(monkeypatch, db_session):
    spy = _DelaySpy()
    monkeypatch.setattr(tasks.send_outbound_message_task, "delay", spy)

    user, business = _create_user_business(db_session)
    _identity(db_session, user, business, "off")
    _identity(db_session, user, business, "daily_digest", external_id="233240000002")
    insights = [_insight(db_session, business)]

    deliver_immediate(db_session, business, insights)

    assert db_session.query(OutboundMessage).count() == 0
    assert spy.calls == []


def test_deliver_immediate_no_op_when_no_new_insights(monkeypatch, db_session):
    spy = _DelaySpy()
    monkeypatch.setattr(tasks.send_outbound_message_task, "delay", spy)

    user, business = _create_user_business(db_session)
    _identity(db_session, user, business, "immediate")

    deliver_immediate(db_session, business, [])

    assert db_session.query(OutboundMessage).count() == 0
    assert spy.calls == []


# --- collect_and_queue_digests -----------------------------------------------


def test_digest_queues_insights_since_last_digest(monkeypatch, db_session):
    spy = _DelaySpy()
    monkeypatch.setattr(tasks.send_outbound_message_task, "delay", spy)

    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    user, business = _create_user_business(db_session)
    identity = _identity(db_session, user, business, "daily_digest", last_digest_sent_at=now - timedelta(hours=25))
    _insight(db_session, business, title="Old, before last digest", created_at=now - timedelta(hours=30))
    _insight(db_session, business, title="New, since last digest", created_at=now - timedelta(hours=10))

    queued = collect_and_queue_digests(db_session, now=now)

    assert queued == 1
    [message] = db_session.query(OutboundMessage).filter(OutboundMessage.channel_identity_id == identity.id).all()
    assert "New, since last digest" in message.body
    assert "Old, before last digest" not in message.body
    db_session.refresh(identity)
    assert identity.last_digest_sent_at == now


def test_digest_skips_identity_not_yet_due(monkeypatch, db_session):
    spy = _DelaySpy()
    monkeypatch.setattr(tasks.send_outbound_message_task, "delay", spy)

    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    user, business = _create_user_business(db_session)
    _identity(db_session, user, business, "daily_digest", last_digest_sent_at=now - timedelta(hours=2))
    _insight(db_session, business)

    queued = collect_and_queue_digests(db_session, now=now)

    assert queued == 0
    assert db_session.query(OutboundMessage).count() == 0


def test_digest_marks_checked_even_with_no_new_insights(monkeypatch, db_session):
    monkeypatch.setattr(tasks.send_outbound_message_task, "delay", _DelaySpy())

    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    user, business = _create_user_business(db_session)
    identity = _identity(db_session, user, business, "daily_digest")  # last_digest_sent_at is None -- due now

    queued = collect_and_queue_digests(db_session, now=now)

    assert queued == 0
    db_session.refresh(identity)
    assert identity.last_digest_sent_at == now


def test_digest_ignores_non_digest_identities(monkeypatch, db_session):
    spy = _DelaySpy()
    monkeypatch.setattr(tasks.send_outbound_message_task, "delay", spy)

    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    user, business = _create_user_business(db_session)
    _identity(db_session, user, business, "immediate")
    _identity(db_session, user, business, "off", external_id="233240000003")
    _insight(db_session, business)

    queued = collect_and_queue_digests(db_session, now=now)

    assert queued == 0
    assert spy.calls == []
