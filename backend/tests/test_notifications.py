"""Phase 5B notification tests (N3-Tests scope, tests only).

Ownership: this file + notif fixtures in conftest.py ONLY. No app code,
docs, or migrations touched. Isolated in-memory SQLite; never touches
smartqueue.db or the network. Real providers default to Mocks
(record + success, never real); real stubs stay disabled without creds.

Coverage vs the real implementation (N1-Core + N2-Persist):
  PROVIDERS: Mock email/push/sms success + recording, disabled-stub
    failure Results (never raise), raising-provider isolation (no crash,
    FAILED record), secrets never in logs/bodies, no real sends.
  TRIGGERS: booked/joined/cancelled/serving/completed/approaching via
    real REST mutations -> queue_events emit + notification OUTBOX/DB
    record; queue.skipped stays silent; failed txn emits nothing.
  IDEMPOTENCY: same queue event twice -> one record (in-process keys +
    DB UNIQUE); key-builder determinism.
  PREFS: real defaults (email/push ON, sms OFF), disabled suppression,
    enabled delivery, TURN_NOW security bypass, unknown channel error.
  RBAC: GET /api/v1/notifications history -- own 200 (filtered), other
    customer 200 (isolated), admin 200 (all), barber/receptionist 403,
    unauth 401. Envelope + exact codes everywhere.
  TXN: failed booking -> no appointment/queue/history/queue-event/
    notification; success -> all created.

Isolation: autouse fixture clears queue_events outbox, notification
OUTBOX/_SEEN_KEYS, Mock sends and prefs per test; notif_test_session
points the service at the test DB (never prod).

KNOWN BLOCKER (N1): app/notifications/service.py references
``NotificationStatus`` but never imports/defines it -> NameError per
channel -> handle() silently delivers nothing. Tests apply a test-only
shim (notif_status_shim) so the rest of the pipeline is verified, and
test_blocker_service_defines_notification_status pins the defect
(xfail until N1 fixes the import).
"""
import enum
import logging

import pytest

APPT_BASE = "/api/v1/appointments"
QUEUE_BASE = "/api/v1/queue"
NOTIF_BASE = "/api/v1/notifications"


def _envelope(body):
    assert set(body.keys()) >= {"success", "data", "message"}, body
    assert isinstance(body["success"], bool), body
    assert isinstance(body["message"], str), body


@pytest.fixture(autouse=True)
def _notif_isolation():
    """Per-test isolation for all process-global notification state."""
    from app.notifications import preferences as _prefs
    from app.notifications import providers as _providers
    from app.notifications import service as _svc
    from app.services import queue_events as _qe

    _qe.clear_outbox()
    _svc.OUTBOX.clear()
    try:
        _svc._SEEN_KEYS.clear()
    except Exception:
        pass
    _providers.clear_mock_sends()
    _prefs.clear_preferences()
    yield
    _qe.clear_outbox()
    _svc.OUTBOX.clear()
    try:
        _svc._SEEN_KEYS.clear()
    except Exception:
        pass
    _providers.clear_mock_sends()
    _prefs.clear_preferences()


@pytest.fixture()
def notif_status_shim(monkeypatch):
    """Test-only shim for the missing NotificationStatus (see BLOCKER).

    Returns {"shimmed": bool}. Never edits app files.
    """
    import app.notifications.service as _svc

    needed = not hasattr(_svc, "NotificationStatus")
    if needed:
        class _NS(str, enum.Enum):
            PENDING = "PENDING"
            SENT = "SENT"
            FAILED = "FAILED"

        monkeypatch.setattr(_svc, "NotificationStatus", _NS, raising=False)
    return {"shimmed": needed}


def _book(client, headers, barber_id, service_id, date_str, start, salon_id):
    res = client.post(
        APPT_BASE,
        json={
            "barber_id": barber_id,
            "service_id": service_id,
            "appointment_date": date_str,
            "start_time": start,
            "salon_id": salon_id,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    _envelope(res.json())
    assert res.json()["success"] is True
    return res.json()["data"]


def _find_queue_id(client, admin_headers, appointment_id):
    res = client.get(QUEUE_BASE, headers=admin_headers)
    assert res.status_code == 200, res.text
    for entry in res.json()["data"]:
        if entry.get("appointment_id") == appointment_id:
            return entry["queue_id"]
    raise AssertionError(f"no queue entry for appointment {appointment_id}")


def _qe_types():
    from app.services import queue_events as _qe

    return [e.get("type", "") for e in _qe.peek_outbox()]


def _notif_outbox():
    from app.notifications import service as _svc

    return list(_svc.OUTBOX)


def _notif_types():
    return [r.get("type", "") for r in _notif_outbox()]


# ---------------------------------------------------------------------------
# BLOCKER pin (xfail until N1 imports/defines NotificationStatus).
# ---------------------------------------------------------------------------


def test_blocker_service_defines_notification_status():
    import app.notifications.service as _svc

    assert hasattr(_svc, "NotificationStatus"), (
        "service.py references NotificationStatus (3 uses) but never "
        "imports/defines it -> NameError per channel, silent zero-delivery"
    )


# ---------------------------------------------------------------------------
# PROVIDERS (8): real Mock/disabled-stub contract, no real sends.
# ---------------------------------------------------------------------------


def test_provider_mock_email_success_and_recorded():
    from app.notifications.providers import MockEmailProvider

    MockEmailProvider.clear()
    p = MockEmailProvider()
    res = p.send(to="a@test.com", subject="s", body="b",
                 metadata={"user_id": 1})
    assert res.success is True
    assert len(MockEmailProvider.SENT) == 1
    assert MockEmailProvider.SENT[0]["to"] == "a@test.com"


def test_provider_mock_push_success_and_recorded():
    from app.notifications.providers import MockPushProvider

    MockPushProvider.clear()
    assert MockPushProvider().send(to="42", subject="s", body="b").success is True
    assert len(MockPushProvider.SENT) == 1


def test_provider_mock_sms_success_and_recorded():
    from app.notifications.providers import MockSmsProvider

    MockSmsProvider.clear()
    assert MockSmsProvider().send(to="999", subject="s", body="b").success is True
    assert len(MockSmsProvider.SENT) == 1


def test_provider_disabled_stubs_fail_without_raise_or_send():
    from app.notifications.providers import (
        HttpPushProvider,
        HttpSmsProvider,
        SmtpEmailProvider,
    )

    email = SmtpEmailProvider().send(to="a@test.com", subject="s", body="b")
    assert email.success is False  # EMAIL_ENABLED=False by default
    assert "disabled" in (email.error or "").lower()
    push = HttpPushProvider().send(to="1", subject="s", body="b")
    assert push.success is False
    sms = HttpSmsProvider().send(to="1", subject="s", body="b")
    assert sms.success is False


def test_provider_get_provider_defaults_to_mock_no_real():
    from app.notifications.providers import (
        MockEmailProvider,
        MockPushProvider,
        MockSmsProvider,
        get_provider,
    )

    assert isinstance(get_provider("email"), MockEmailProvider)
    assert isinstance(get_provider("push"), MockPushProvider)
    assert isinstance(get_provider("sms"), MockSmsProvider)


def test_provider_no_real_sends_even_with_network_blocked(monkeypatch):
    import smtplib
    import socket

    def _boom(*a, **k):
        raise AssertionError("real network send attempted")

    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(smtplib, "SMTP", _boom)
    from app.notifications.providers import get_provider

    # Default path (Mocks) never touches smtplib/socket.
    assert get_provider("email").send(to="a@t.com", body="b").success is True
    assert get_provider("push").send(to="1", body="b").success is True
    assert get_provider("sms").send(to="1", body="b").success is True


def test_provider_exception_isolated_no_crash(
    notif_status_shim, notif_test_session, customer_user,
    monkeypatch, caplog,
):
    """A raising provider must not break handle(): FAILED, never raise."""
    from app.notifications import service as _svc

    class _Boom:
        name = "boom"

        def send(self, **kw):
            raise RuntimeError("sk-secret-gateway-down")

    monkeypatch.setattr(_svc, "get_provider", lambda channel: _Boom())
    evt = {
        "type": "queue.created",
        "email": "t@test.com",
        "phone": "9000000001",
        "data": {
            "appointment_id": None,
            "user_id": customer_user.user_id,
            "queue_position": 1,
            "estimated_wait_minutes": 0,
        },
    }
    with caplog.at_level(logging.WARNING, logger="app.notifications.service"):
        results = _svc.service.handle(evt)  # must not raise
    assert isinstance(results, list) and len(results) >= 1
    assert all(r["status"] == "FAILED" for r in results)
    assert all(r["attempts"] == _svc.MAX_ATTEMPTS for r in results)
    assert "sk-secret-gateway-down" not in caplog.text  # type only, never secret


def test_provider_no_secrets_in_logs_or_bodies(
    notif_status_shim, notif_test_session, customer_user, caplog,
):
    from app.notifications import service as _svc

    evt = {
        "type": "queue.serving",
        "data": {
            "appointment_id": None,
            "user_id": customer_user.user_id,
            "queue_position": 1,
            "estimated_wait_minutes": 5,
        },
    }
    with caplog.at_level(logging.DEBUG, logger="app.notifications"):
        results = _svc.service.handle(evt)
    assert len(results) >= 1
    blob = caplog.text
    for banned in ("password_hash", "jwt_secret", "secret_key", "access_token",
                   "$2b$", "customer@test.com", "1234567890"):
        assert banned not in blob, f"secret/PII in logs: {banned}"
    for r in results:
        body = (r.get("subject", "") or "") + (r.get("body", "") or "")
        assert "password" not in body.lower()
        assert "customer@test.com" not in body
        assert "1234567890" not in body


# ---------------------------------------------------------------------------
# TRIGGERS via real REST (booked/joined/cancelled/serving/completed/
# approaching + silent skip + failed-txn silence).
# ---------------------------------------------------------------------------


def test_trigger_booked_creates_notification(
    client, customer_headers, customer_user, salon_barber, salon_service,
    salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    assert data["status"] == "booked"
    assert "queue.created" in _qe_types()  # post-commit queue emit
    recs = [r for r in _notif_outbox()
            if r.get("appointment_id") == data["appointment_id"]]
    assert recs, "booked must create a notification record"
    assert {r["type"] for r in recs} == {"queue_joined"}
    assert {r["user_id"] for r in recs} == {customer_user.user_id}
    assert {r["channel"] for r in recs} == {"email", "push"}  # sms OFF default


def test_trigger_joined_queue_row_and_event(
    client, customer_headers, customer_user, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    from app.models.queue import Queue as _Q

    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    row = db_session.query(_Q).filter(
        _Q.appointment_id == data["appointment_id"]).one()
    assert row.status == "waiting"
    assert "queue.created" in _qe_types()
    assert "queue_joined" in _notif_types()


def test_trigger_cancelled_creates_notification(
    client, customer_headers, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    res = client.delete(f"{APPT_BASE}/{data['appointment_id']}",
                        headers=customer_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert "queue.cancelled" in _qe_types()
    recs = [r for r in _notif_outbox()
            if r.get("appointment_id") == data["appointment_id"]
            and r.get("type") == "appointment_cancelled"]
    assert recs, "cancel must create appointment_cancelled notification"


def test_trigger_serving_creates_turn_now(
    client, customer_headers, admin_headers, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    qid = _find_queue_id(client, admin_headers, data["appointment_id"])
    res = client.post(f"{QUEUE_BASE}/{qid}/serve", headers=admin_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert "queue.serving" in _qe_types()
    recs = [r for r in _notif_outbox()
            if r.get("appointment_id") == data["appointment_id"]
            and r.get("type") == "turn_now"]
    assert recs, "serve must create turn_now notification"


def test_trigger_completed_creates_notification(
    client, customer_headers, admin_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    qid = _find_queue_id(client, admin_headers, data["appointment_id"])
    assert client.post(f"{QUEUE_BASE}/{qid}/serve",
                       headers=admin_headers).status_code == 200
    res = client.post(f"{QUEUE_BASE}/{qid}/complete", headers=admin_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert "queue.completed" in _qe_types()
    recs = [r for r in _notif_outbox()
            if r.get("appointment_id") == data["appointment_id"]
            and r.get("type") == "appointment_completed"]
    assert recs, "complete must create appointment_completed notification"


def test_trigger_approaching_via_reschedule(
    client, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    """queue.updated at position 1 (<= threshold 2) -> queue_approaching."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    before = len(_notif_outbox())
    res = client.put(f"{APPT_BASE}/{data['appointment_id']}",
                     json={"appointment_date": slot_date.isoformat(),
                           "start_time": "11:00"},
                     headers=customer_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert "queue.updated" in _qe_types()
    new_types = [r.get("type") for r in _notif_outbox()[before:]]
    assert "queue_approaching" in new_types, (
        f"approaching (pos<=2) must notify, got {new_types}")


def test_trigger_far_position_stays_silent(
    notif_status_shim, notif_test_session, customer_user,
):
    """queue.updated beyond the threshold is a silent position refresh."""
    from app.notifications import service as _svc

    evt = {"type": "queue.updated",
           "data": {"appointment_id": None,
                    "user_id": customer_user.user_id,
                    "queue_position": 99, "estimated_wait_minutes": 200}}
    assert _svc.service.handle(evt) == []
    assert _notif_outbox() == []


def test_trigger_skip_stays_silent(
    client, customer_headers, admin_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    """no_show carries no customer message by default."""
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    qid = _find_queue_id(client, admin_headers, data["appointment_id"])
    before = len(_notif_outbox())
    res = client.post(f"{QUEUE_BASE}/{qid}/skip", headers=admin_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert len(_notif_outbox()) == before


def test_trigger_failed_txn_emits_none(
    client, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00",
          salon.salon_id)
    qe_before = len(_qe_types())
    notif_before = len(_notif_outbox())
    clash = client.post(
        APPT_BASE,
        json={"barber_id": salon_barber.barber_id,
              "service_id": salon_service.service_id,
              "appointment_date": slot_date.isoformat(),
              "start_time": "10:15",
              "salon_id": salon.salon_id},
        headers=customer_headers,
    )
    assert clash.status_code == 409, clash.text
    _envelope(clash.json())
    assert clash.json()["success"] is False
    assert len(_qe_types()) == qe_before  # rolled back -> silent
    assert len(_notif_outbox()) == notif_before


# ---------------------------------------------------------------------------
# IDEMPOTENCY (3): same event twice -> one logical record.
# ---------------------------------------------------------------------------


def test_idempotency_same_event_twice_one_record(
    client, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    from app.notifications import service as _svc

    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00",
          salon.salon_id)
    first_count = len(_notif_outbox())
    assert first_count >= 1
    # Re-deliver the exact committed envelope for the same appointment.
    from app.services import queue_events as _qe

    created = [e for e in _qe.peek_outbox() if e.get("type") == "queue.created"]
    assert created
    _svc.service.handle(created[0])
    assert len(_notif_outbox()) == first_count  # no duplicate record
    assert len({r.get("idempotency_key") for r in _notif_outbox()}) == first_count


def test_idempotency_key_builder_deterministic():
    from app.notifications.models import build_idempotency_key

    k1 = build_idempotency_key(notification_type="queue_joined",
                               channel="email", appointment_id=7)
    k2 = build_idempotency_key(notification_type="queue_joined",
                               channel="email", appointment_id=7)
    assert k1 == k2 == "queue_joined:7:email"
    assert build_idempotency_key(notification_type="queue_joined",
                                 channel="sms",
                                 appointment_id=7) != k1
    assert build_idempotency_key(notification_type="queue_joined",
                                 channel="email", appointment_id=8) != k1


def test_idempotency_db_unique_guard(notif_test_session):
    """Concurrent duplicate persists collapse to one row (UNIQUE key)."""
    from app.notifications import service as _svc

    record = {"user_id": 1, "appointment_id": 4242, "queue_id": None,
              "channel": "email", "type": "queue_joined",
              "subject": "s", "body": "b", "status": "PENDING",
              "idempotency_key": "queue_joined:4242:email",
              "attempts": 0, "last_error": None,
              "created_at": "2026-01-01T00:00:00"}
    first = _svc._persist_record(dict(record))
    second = _svc._persist_record(dict(record))
    assert first is not None
    assert second == first  # already-queued, no blind retry
    from app.notifications.models import Notification

    rows = (notif_test_session.query(Notification)
            .filter(Notification.idempotency_key == record["idempotency_key"])
            .all())
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# PREFS (5): real defaults, suppression, enablement, security bypass.
# ---------------------------------------------------------------------------


def test_prefs_defaults_email_push_on_sms_off():
    from app.notifications.preferences import get_preferences

    assert get_preferences(12345) == {"email": True, "push": True, "sms": False}


def test_prefs_disabled_channel_suppressed(
    client, customer_headers, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    from app.notifications.preferences import set_preference

    set_preference(customer_user.user_id, "email", False)
    set_preference(customer_user.user_id, "push", False)
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    recs = [r for r in _notif_outbox()
            if r.get("appointment_id") == data["appointment_id"]]
    assert recs == []  # all default-ON channels disabled -> nothing


def test_prefs_enabled_sms_sent(
    client, customer_headers, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    from app.notifications.preferences import set_preference

    set_preference(customer_user.user_id, "sms", True)
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    channels = {r["channel"] for r in _notif_outbox()
                if r.get("appointment_id") == data["appointment_id"]}
    assert channels == {"email", "push", "sms"}


def test_prefs_turn_now_bypasses_disabled(
    client, customer_headers, admin_headers, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    """Security/time-critical TURN_NOW is never blocked by preferences."""
    from app.notifications.preferences import set_preference

    for ch in ("email", "push", "sms"):
        set_preference(customer_user.user_id, ch, False)
    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    assert [r for r in _notif_outbox()
            if r.get("appointment_id") == data["appointment_id"]] == []
    qid = _find_queue_id(client, admin_headers, data["appointment_id"])
    assert client.post(f"{QUEUE_BASE}/{qid}/serve",
                       headers=admin_headers).status_code == 200
    recs = [r for r in _notif_outbox()
            if r.get("appointment_id") == data["appointment_id"]
            and r.get("type") == "turn_now"]
    assert len(recs) == 3  # delivered despite all prefs off


def test_prefs_unknown_channel_rejected():
    from app.notifications.preferences import set_preference

    with pytest.raises(ValueError):
        set_preference(1, "carrier_pigeon", True)


# ---------------------------------------------------------------------------
# RBAC history (5): real GET /api/v1/notifications matrix.
# ---------------------------------------------------------------------------


def _seed_notifications(client, customer_headers, customer2_headers,
                        salon_barber, salon_service, salon,
                        slot_date, slot_availability):
    a = _book(client, customer_headers, salon_barber.barber_id,
              salon_service.service_id, slot_date.isoformat(), "10:00",
              salon.salon_id)
    b = _book(client, customer2_headers, salon_barber.barber_id,
              salon_service.service_id, slot_date.isoformat(), "10:30",
              salon.salon_id)
    return a, b


def test_rbac_own_history_200(
    client, customer_headers, customer2_headers, customer_user,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    _seed_notifications(client, customer_headers, customer2_headers,
                        salon_barber, salon_service, salon,
                        slot_date, slot_availability)
    res = client.get(NOTIF_BASE, headers=customer_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert res.json()["success"] is True
    items = res.json()["data"]
    assert items, "own booking must yield own history rows"
    assert {i["user_id"] for i in items} == {customer_user.user_id}


def test_rbac_other_history_isolated(
    client, customer_headers, customer2_headers, customer_user,
    customer2_user, salon_barber, salon_service, salon,
    slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    """Other customers get 200 but only their own rows (no cross-read)."""
    _seed_notifications(client, customer_headers, customer2_headers,
                        salon_barber, salon_service, salon,
                        slot_date, slot_availability)
    res = client.get(NOTIF_BASE, headers=customer2_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    items = res.json()["data"]
    assert items
    assert {i["user_id"] for i in items} == {customer2_user.user_id}
    assert customer_user.user_id not in {i["user_id"] for i in items}


def test_rbac_admin_sees_all(
    client, customer_headers, customer2_headers, admin_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    _seed_notifications(client, customer_headers, customer2_headers,
                        salon_barber, salon_service, salon,
                        slot_date, slot_availability)
    res = client.get(NOTIF_BASE, headers=admin_headers)
    assert res.status_code == 200, res.text
    _envelope(res.json())
    assert len(res.json()["data"]) >= 4  # 2 bookings x (email+push)


def test_rbac_non_customer_roles_403(
    client, barber_headers, receptionist_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    for headers in (barber_headers, receptionist_headers):
        res = client.get(NOTIF_BASE, headers=headers)
        assert res.status_code == 403, res.text
        _envelope(res.json())
        assert res.json()["success"] is False


def test_rbac_unauth_401(client):
    res = client.get(NOTIF_BASE)
    assert res.status_code == 401, res.text
    _envelope(res.json())
    assert res.json()["success"] is False


# ---------------------------------------------------------------------------
# TXN isolation (2): failed -> nothing; success -> all rows + emits.
# ---------------------------------------------------------------------------


def test_txn_failed_booking_no_partials(
    client, customer_headers, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    from app.models.appointment import Appointment as _A
    from app.models.queue import Queue as _Q
    from app.models.status_history import AppointmentStatusHistory as _H

    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00",
          salon.salon_id)

    def counts():
        return (db_session.query(_A).count(), db_session.query(_Q).count(),
                db_session.query(_H).count())

    before, qe_before, notif_before = counts(), len(_qe_types()), len(_notif_outbox())
    assert before[0] >= 1 and before[1] >= 1
    clash = client.post(
        APPT_BASE,
        json={"barber_id": salon_barber.barber_id,
              "service_id": salon_service.service_id,
              "appointment_date": slot_date.isoformat(),
              "start_time": "10:00",
              "salon_id": salon.salon_id},
        headers=customer_headers,
    )
    assert clash.status_code == 409, clash.text
    _envelope(clash.json())
    db_session.expire_all()
    assert counts() == before
    assert len(_qe_types()) == qe_before
    assert len(_notif_outbox()) == notif_before


def test_txn_success_booking_all_created(
    client, customer_headers, customer_user, db_session,
    salon_barber, salon_service, salon, slot_date, slot_availability,
    notif_status_shim, notif_test_session,
):
    from app.models.appointment import Appointment as _A
    from app.models.queue import Queue as _Q
    from app.models.status_history import AppointmentStatusHistory as _H
    from app.notifications.models import Notification as _N

    data = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon.salon_id)
    db_session.expire_all()
    assert db_session.query(_A).filter(
        _A.appointment_id == data["appointment_id"]).count() == 1
    assert db_session.query(_Q).filter(
        _Q.appointment_id == data["appointment_id"]).count() == 1
    assert db_session.query(_H).filter(
        _H.appointment_id == data["appointment_id"]).count() >= 1
    assert "queue.created" in _qe_types()
    assert [r for r in _notif_outbox()
            if r.get("appointment_id") == data["appointment_id"]]
    assert db_session.query(_N).filter(
        _N.appointment_id == data["appointment_id"]).count() >= 1
