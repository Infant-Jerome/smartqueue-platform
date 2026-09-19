"""Phase 5A WS queue tests (WS3-Tests scope, tests only).

Real contract (WS1-Infra, server-push model, no WS mutation API):
  WS: ``/api/v1/ws/queue/{salon_id}?token=<JWT>[&barber_id=<int>][&date=YYYY-MM-DD]``
  Mutations happen via REST only:
    POST /api/v1/appointments (create -> queue join broadcast)
    POST /api/v1/queue/serve-next {barber_id, salon_id?}
    POST /api/v1/queue/{id}/complete
    POST /api/v1/queue/{id}/skip
    DELETE /api/v1/appointments/{id} (cancel -> queue cancelled broadcast)
  WS only receives: initial ``queue.updated`` snapshot on connect + broadcast
  events for the above mutations (positions / estimated_wait_minutes forwarded
  verbatim from the committed queue rows).

Close codes: auth failures -> 4401 + close; RBAC failures -> 4403 + close.
Security: payloads carry ONLY allowlisted operational fields (ids, positions,
statuses, waits, scope) -- never password_hash / JWT secrets / PII.

Isolated in-memory SQLite only; TestClient.websocket_connect with ?token=.

Gating: ``require_ws()`` walks the mounted routers for the websocket route.
If the WS route is absent it raises
``pytest.skip("BLOCKER: WS infra not landed ...")`` -- nothing is faked or
mocked to pass. Event tests additionally diagnose the publish->manager
bridge via the ``queue_events`` outbox so failures pinpoint the owning layer.
"""

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import (
    ws_make_expired_token,
    ws_make_invalid_token,
    ws_make_unknown_user_token,
    ws_queue_url,
    ws_raw_token_from_headers,
)

WS_AUTH_CLOSE = 4401
WS_FORBID_CLOSE = 4403

APPT_BASE = "/api/v1/appointments"
QUEUE_BASE = "/api/v1/queue"


# ---------------------------------------------------------------------------
# Infra discovery / gating (do not fake: skip when WS route is absent).
# ---------------------------------------------------------------------------


def _mounted_ws_paths():
    """Find mounted websocket routes, descending into _IncludedRouter nests."""
    from app.api.v1.router import api_router

    found = []

    def walk(router, prefix=""):
        for route in getattr(router, "routes", []):
            nested = getattr(route, "original_router", None)
            if nested is not None:
                walk(nested, prefix)
                continue
            if type(route).__name__ == "APIWebSocketRoute":
                found.append(prefix + str(getattr(route, "path", "")))

    walk(api_router, "/api/v1")
    return found


def _ws_base_for_salon(salon_id):
    """Full WS path for a salon, or skip when the infra has not landed."""
    paths = _mounted_ws_paths()
    if not paths:
        pytest.skip(
            "BLOCKER: WS infra not landed - no websocket route mounted "
            "(walked api_router incl. nested routers; found none). "
            "Scaffolded 26 tests present; 0 faked."
        )
    for path in paths:
        if "queue" in path:
            return path.replace("{salon_id}", str(salon_id))
    pytest.skip(f"BLOCKER: no queue WS route among mounted WS paths {paths}")


def _token(headers):
    return ws_raw_token_from_headers(headers)


def _manager():
    from app.ws.manager import manager

    return manager


# ---------------------------------------------------------------------------
# Shared REST + WS helpers (mutations via REST; WS asserts receive).
# ---------------------------------------------------------------------------


def _book(client, headers, barber_id, service_id, date_str, start, salon_id=None):
    body = {
        "barber_id": barber_id,
        "service_id": service_id,
        "appointment_date": date_str,
        "start_time": start,
    }
    if salon_id is not None:
        body["salon_id"] = salon_id
    res = client.post(APPT_BASE, json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["data"]


def _queue_id(entry):
    return entry.get("queue_id", entry.get("id"))


def _find_queue_id(client, admin_headers, appointment_id):
    res = client.get(QUEUE_BASE, headers=admin_headers)
    assert res.status_code == 200, res.text
    for entry in res.json()["data"]:
        if entry.get("appointment_id") == appointment_id:
            return _queue_id(entry)
    raise AssertionError(f"no queue entry for appointment {appointment_id}")


def try_receive(ws, timeout=3.0):
    """Non-blocking receive: parsed JSON, or None on timeout/close.

    Runs the blocking TestClient receive on a daemon worker and waits on a
    queue. Never joins the worker: on timeout the worker stays parked until
    the session closes (which releases it); a joining shutdown would hang
    forever when no message ever arrives (e.g. bridge-down event tests).
    """
    import queue as _queue
    import threading

    box: _queue.Queue = _queue.Queue(maxsize=1)

    def _run():
        try:
            box.put(("ok", ws.receive_json()))
        except Exception as exc:  # disconnect / closed session
            try:
                box.put(("err", exc))
            except Exception:
                pass

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    try:
        kind, val = box.get(timeout=timeout)
    except _queue.Empty:
        return None
    if kind == "err":
        return None
    return val


def _recv_event(ws, timeout=5.0, what="a WS message"):
    msg = try_receive(ws, timeout=timeout)
    assert msg is not None, f"expected {what}, got none"
    return msg


def _payload_text(msg):
    import json

    try:
        return json.dumps(msg, default=str).lower()
    except Exception:
        return str(msg).lower()


def _expect_close(client, url, expected_code):
    """Connect and expect the server to close with expected_code."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(url) as ws:
            # If the server accepts instead of closing, fail loudly.
            ws.receive_text()
            pytest.fail(f"expected WS close {expected_code}, connection stayed open")
    assert exc_info.value.code == expected_code, (
        f"expected close {expected_code}, got {exc_info.value.code}"
    )


def _outbox_size():
    from app.services import queue_events as qe

    return len(qe.peek_outbox())


def _expect_broadcast(ws, markers, what):
    """Assert a WS broadcast arrives; diagnose publish-vs-delivery on failure."""
    before_diag = _payload_text(f"outbox-size={_outbox_size()}")
    msg = try_receive(ws, timeout=5.0)
    assert msg is not None, (
        f"{what}: no WS broadcast received. Diagnostics: REST publish outbox "
        f"size now={_outbox_size()} (grew => REST published post-commit but the "
        f"publish->manager bridge did not deliver to this socket {before_diag}). "
        "BLOCKER owner: WS1/WS2 publish->manager interop (tests do not fake it)."
    )
    text = _payload_text(msg)
    assert any(m in text for m in markers), f"{what}: broadcast missing {markers}: {msg}"
    return msg


def _assert_safe_payload(msg):
    """Security: no hash/secret/token/PII anywhere in the WS message."""
    text = _payload_text(msg)
    for banned in ("password_hash", "passwordhash", "$2b$", "$2a$"):
        assert banned not in text, f"WS payload leaks credential material {banned!r}: {msg}"
    for banned in ("jwt_secret", "secret_key", "access_token"):
        assert banned not in text, f"WS payload leaks secret material {banned!r}: {msg}"
    for banned in ("password", "email", "phone"):
        assert banned not in text, f"WS payload leaks PII field {banned!r}: {msg}"
    assert "customer@test.com" not in text and "1234567890" not in text, (
        f"WS payload leaks customer PII values: {msg}"
    )


def _wait_for(predicate, timeout=5.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ===========================================================================
# AUTH 1-5: ?token= JWT handling (4401 + close on failure).
# ===========================================================================


def test_ws01_valid_token_connects(client, customer_headers, salon):
    """1: valid JWT connects and receives the initial snapshot."""
    url = _ws_base_for_salon(salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(customer_headers))
    assert full.startswith("/api/v1/ws/queue/"), full
    assert url.replace("{salon_id}", str(salon.salon_id)) in full, (url, full)
    with client.websocket_connect(full) as ws:
        msg = _recv_event(ws, what="initial snapshot for valid token")
        assert isinstance(msg, dict), msg
        assert _payload_text(msg).count("queue") >= 1, msg


def test_ws02_missing_token_rejected_4401(client, salon):
    """2: missing ?token= -> 4401 + close."""
    _ws_base_for_salon(salon.salon_id)
    _expect_close(client, ws_queue_url(salon.salon_id), WS_AUTH_CLOSE)


def test_ws03_invalid_token_rejected_4401(client, salon):
    """3: tampered/garbage token -> 4401 + close."""
    _ws_base_for_salon(salon.salon_id)
    _expect_close(
        client,
        ws_queue_url(salon.salon_id, token=ws_make_invalid_token()),
        WS_AUTH_CLOSE,
    )


def test_ws04_expired_token_rejected_4401(client, customer_user, salon):
    """4: signed-but-expired JWT -> 4401 + close."""
    _ws_base_for_salon(salon.salon_id)
    expired = ws_make_expired_token(customer_user.user_id)
    _expect_close(client, ws_queue_url(salon.salon_id, token=expired), WS_AUTH_CLOSE)


def test_ws05_nonexistent_user_rejected_4401(client, salon):
    """5: valid signature for unknown sub -> 4401 + close."""
    _ws_base_for_salon(salon.salon_id)
    _expect_close(
        client,
        ws_queue_url(salon.salon_id, token=ws_make_unknown_user_token()),
        WS_AUTH_CLOSE,
    )


# ===========================================================================
# RBAC 6-10: scope enforcement.
# ===========================================================================


def test_ws06_customer_own_scope_ok(
    client, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """6: customer subscribing to own salon scope gets own position only."""
    _ws_base_for_salon(salon.salon_id)
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00",
          salon_id=salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(customer_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        msg = _recv_event(ws, what="customer own-scope snapshot")
        text = _payload_text(msg)
        assert "has_queue" in text and "true" in text, f"expected own queue in snapshot: {msg}"
        _assert_safe_payload(msg)


def test_ws07_barber_other_scope_rejected_4403(
    client, barber_headers, barber_profile, other_barber_profile, salon,
    slot_date,
):
    """7: barber requesting another barber_id -> 4403 + close."""
    _ws_base_for_salon(salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(barber_headers),
                        barber_id=other_barber_profile.barber_id,
                        date_str=slot_date.isoformat())
    _expect_close(client, full, WS_FORBID_CLOSE)


def test_ws08_staff_ok(client, receptionist_headers, salon, slot_date):
    """8: staff/receptionist gets the full salon snapshot."""
    _ws_base_for_salon(salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(receptionist_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        msg = _recv_event(ws, what="staff salon snapshot")
        assert "entries" in _payload_text(msg), f"staff snapshot missing entries: {msg}"


def test_ws09_admin_ok(client, admin_headers, salon, slot_date):
    """9: admin gets the full salon snapshot."""
    _ws_base_for_salon(salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        msg = _recv_event(ws, what="admin salon snapshot")
        assert "entries" in _payload_text(msg), f"admin snapshot missing entries: {msg}"


def test_ws10_unauthorized_salon_isolated(
    client, customer_headers, customer_user,
    salon_barber, salon_service, salon, salon2, slot_date, slot_availability,
):
    """10: a salon scope with no own queue leaks no foreign data.

    Deviation note: the endpoint does not close unknown/foreign salon scopes;
    it returns an authorized empty scope. The security property asserted here
    is scope isolation: salon2's snapshot for this customer shows has_queue
    False and contains none of salon1's queue ids/positions.
    """
    _ws_base_for_salon(salon.salon_id)
    appt = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon_id=salon.salon_id)
    full = ws_queue_url(salon2.salon_id, token=_token(customer_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        msg = _recv_event(ws, what="foreign-salon snapshot")
        text = _payload_text(msg)
        assert "has_queue" in text and "false" in text, f"foreign scope must be empty: {msg}"
        assert str(appt["appointment_id"]) not in text, f"foreign scope leaks salon1 data: {msg}"
        _assert_safe_payload(msg)


# ===========================================================================
# CONN 11-14: lifecycle management.
# ===========================================================================


def test_ws11_connect_receives_initial_state(client, admin_headers, salon, slot_date):
    """11: connect delivers an initial queue.updated snapshot."""
    _ws_base_for_salon(salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        msg = _recv_event(ws, what="initial state")
        text = _payload_text(msg)
        assert "queue.updated" in text, f"initial message must be queue.updated: {msg}"
        assert "scope" in text, f"initial state missing scope: {msg}"


def test_ws12_disconnect_cleanup(client, admin_headers, salon, slot_date):
    """12: disconnect unregisters the socket; reconnect works (no leak)."""
    _ws_base_for_salon(salon.salon_id)
    mgr = _manager()
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        _recv_event(ws, what="initial state")
        assert mgr.connection_count >= 1
    assert _wait_for(lambda: mgr.connection_count == 0), (
        f"disconnect did not clean up; count={mgr.connection_count}"
    )
    with client.websocket_connect(full) as ws2:
        msg = _recv_event(ws2, what="snapshot after clean reconnect")
        assert isinstance(msg, dict), msg


def test_ws13_multiple_connections_all_receive(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """13: two concurrent subscribers both receive the serve-next broadcast."""
    _ws_base_for_salon(salon.salon_id)
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00",
          salon_id=salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws_a:
        with client.websocket_connect(full) as ws_b:
            _recv_event(ws_a, what="snapshot A")
            _recv_event(ws_b, what="snapshot B")
            res = client.post(QUEUE_BASE + "/serve-next",
                              json={"barber_id": salon_barber.barber_id,
                                    "salon_id": salon.salon_id},
                              headers=admin_headers)
            assert res.status_code == 200, res.text
            evt_a = _expect_broadcast(ws_a, ("serving", "queue.serving"), "serve-next to conn A")
            evt_b = _expect_broadcast(ws_b, ("serving", "queue.serving"), "serve-next to conn B")
            assert isinstance(evt_a, dict) and isinstance(evt_b, dict)


def test_ws14_dead_connection_removed(client, admin_headers, salon, slot_date):
    """14: closing one socket prunes only it; the live socket stays registered."""
    _ws_base_for_salon(salon.salon_id)
    mgr = _manager()
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws_live:
        _recv_event(ws_live, what="live snapshot")
        assert mgr.connection_count >= 1
        dead = client.websocket_connect(full)
        ws_dead = dead.__enter__()
        try:
            _recv_event(ws_dead, what="dead-socket snapshot")
            assert mgr.connection_count >= 2
        finally:
            dead.__exit__(None, None, None)
        # Live socket must still be registered and receive its scope snapshot.
        assert mgr.connection_count >= 1, "live socket was wrongly pruned"
        assert _wait_for(lambda: mgr.connection_count == 1, timeout=5.0), (
            f"dead socket was not pruned; count={mgr.connection_count}"
        )


# ===========================================================================
# INITIAL STATE 15.
# ===========================================================================


def test_ws15_initial_state_shape(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """15: snapshot carries entries with positions + forwarded wait estimates."""
    _ws_base_for_salon(salon.salon_id)
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00",
          salon_id=salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        msg = _recv_event(ws, what="populated snapshot")
        text = _payload_text(msg)
        assert "queue_position" in text, f"snapshot missing queue_position: {msg}"
        assert "estimated_wait" in text, f"snapshot missing estimated wait: {msg}"
        assert "status" in text and "waiting" in text, f"snapshot missing waiting entry: {msg}"
        _assert_safe_payload(msg)


# ===========================================================================
# EVENTS 16-21: REST mutations -> WS broadcasts (server-push only).
# ===========================================================================


def _book_two(client, customer_headers, customer2_headers, salon_barber,
              salon_service, salon, slot_date):
    a = _book(client, customer_headers, salon_barber.barber_id,
              salon_service.service_id, slot_date.isoformat(), "10:00",
              salon_id=salon.salon_id)
    b = _book(client, customer2_headers, salon_barber.barber_id,
              salon_service.service_id, slot_date.isoformat(), "10:30",
              salon_id=salon.salon_id)
    return a, b


def test_ws16_serve_next_broadcast(
    client, admin_headers, customer_headers, customer2_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """16: POST /queue/serve-next -> serving broadcast on the WS."""
    _ws_base_for_salon(salon.salon_id)
    _book_two(client, customer_headers, customer2_headers, salon_barber,
              salon_service, salon, slot_date)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        _recv_event(ws, what="snapshot")
        res = client.post(QUEUE_BASE + "/serve-next",
                          json={"barber_id": salon_barber.barber_id,
                                "salon_id": salon.salon_id},
                          headers=admin_headers)
        assert res.status_code == 200, res.text
        _expect_broadcast(ws, ("serving", "queue.serving"), "serve-next")


def test_ws17_complete_broadcast(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """17: POST /queue/{id}/complete -> completed broadcast on the WS."""
    _ws_base_for_salon(salon.salon_id)
    appt = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon_id=salon.salon_id)
    qid = _find_queue_id(client, admin_headers, appt["appointment_id"])
    res = client.post(QUEUE_BASE + "/serve-next",
                      json={"barber_id": salon_barber.barber_id,
                            "salon_id": salon.salon_id},
                      headers=admin_headers)
    assert res.status_code == 200, res.text
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        _recv_event(ws, what="snapshot")
        res = client.post(f"{QUEUE_BASE}/{qid}/complete", headers=admin_headers)
        assert res.status_code == 200, res.text
        _expect_broadcast(ws, ("completed", "queue.completed"), "complete")


def test_ws18_skip_broadcast(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """18: POST /queue/{id}/skip -> skipped/no_show broadcast on the WS."""
    _ws_base_for_salon(salon.salon_id)
    appt = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon_id=salon.salon_id)
    qid = _find_queue_id(client, admin_headers, appt["appointment_id"])
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        _recv_event(ws, what="snapshot")
        res = client.post(f"{QUEUE_BASE}/{qid}/skip", headers=admin_headers)
        assert res.status_code == 200, res.text
        _expect_broadcast(ws, ("no_show", "skipped", "queue.skipped"), "skip")


def test_ws19_cancel_broadcast(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """19: DELETE /appointments/{id} (cancel) -> cancelled broadcast."""
    _ws_base_for_salon(salon.salon_id)
    appt = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                 salon_id=salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        _recv_event(ws, what="snapshot")
        res = client.delete(f"{APPT_BASE}/{appt['appointment_id']}", headers=customer_headers)
        assert res.status_code == 200, res.text
        _expect_broadcast(ws, ("cancelled", "queue.cancelled"), "cancel")


def test_ws20_create_broadcast(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """20: POST /appointments (create) -> created/waiting broadcast."""
    _ws_base_for_salon(salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        _recv_event(ws, what="snapshot")
        _book(client, customer_headers, salon_barber.barber_id,
              salon_service.service_id, slot_date.isoformat(), "10:00",
              salon_id=salon.salon_id)
        _expect_broadcast(
            ws,
            ("queue.created", "created", "waiting", "queue.updated", "queue_position"),
            "create",
        )


def test_ws21_wait_estimates_reflected(
    client, admin_headers, customer_headers, customer2_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """21: broadcasts carry updated estimated_wait_minutes after mutations."""
    _ws_base_for_salon(salon.salon_id)
    _book_two(client, customer_headers, customer2_headers, salon_barber,
              salon_service, salon, slot_date)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        snap = _recv_event(ws, what="populated snapshot")
        assert "estimated_wait" in _payload_text(snap), f"snapshot missing waits: {snap}"
        res = client.post(QUEUE_BASE + "/serve-next",
                          json={"barber_id": salon_barber.barber_id,
                                "salon_id": salon.salon_id},
                          headers=admin_headers)
        assert res.status_code == 200, res.text
        evt = _expect_broadcast(ws, ("serving", "queue.serving"), "serve-next")
        assert "estimated_wait" in _payload_text(evt), f"event missing updated waits: {evt}"


# ===========================================================================
# TXN 22-23: broadcast atomicity (post-commit only).
# ===========================================================================


def test_ws22_failed_mutation_emits_no_event(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """22: failed REST mutation (4xx, rolled back) -> no WS event.

    Guarded against vacuous passes: first proves the bridge delivers (a
    successful serve-next IS received), then proves the failed complete is
    silent. If the bridge itself is down the test fails at the guard with a
    bridge diagnostic instead of passing vacuously.
    """
    _ws_base_for_salon(salon.salon_id)
    appt = _book(client, customer_headers, salon_barber.barber_id,
                 salon_service.service_id, slot_date.isoformat(), "10:00",
                  salon_id=salon.salon_id)
    _ = _find_queue_id(client, admin_headers, appt["appointment_id"])
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        _recv_event(ws, what="snapshot")
        outbox_before = _outbox_size()
        res = client.post(QUEUE_BASE + "/serve-next",
                          json={"barber_id": salon_barber.barber_id,
                                "salon_id": salon.salon_id},
                          headers=admin_headers)
        assert res.status_code == 200, res.text
        # Bridge guard: the successful mutation MUST be received; otherwise
        # a later 'no event' assertion would pass vacuously.
        guard = try_receive(ws, timeout=5.0)
        assert guard is not None, (
            "bridge guard failed: successful serve-next produced no WS event "
            f"(outbox grew {outbox_before}->{_outbox_size()}). Cannot prove "
            "the failed-mutation silence honestly; BLOCKER owner: WS1/WS2 bridge."
        )
        # waiting -> completed directly is illegal (400/409): must stay silent.
        # NOTE: qid was just served (serving), so completing it is legal 200.
        # Book a second still-waiting entry and attempt direct complete on it.
        appt2 = _book(client, customer_headers, salon_barber.barber_id,
                      salon_service.service_id, slot_date.isoformat(), "11:00",
                      salon_id=salon.salon_id)
        qid2 = _find_queue_id(client, admin_headers, appt2["appointment_id"])
        while try_receive(ws, timeout=0.5) is not None:
            pass
        res = client.post(f"{QUEUE_BASE}/{qid2}/complete", headers=admin_headers)
        assert res.status_code in (400, 409, 422), res.text
        assert try_receive(ws, timeout=1.5) is None, "failed mutation emitted an event"


def test_ws23_success_emits_single_post_commit_event(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """23: successful mutation -> exactly one post-commit broadcast."""
    _ws_base_for_salon(salon.salon_id)
    _book(client, customer_headers, salon_barber.barber_id,
          salon_service.service_id, slot_date.isoformat(), "10:00",
          salon_id=salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        _recv_event(ws, what="snapshot")
        outbox_before = _outbox_size()
        res = client.post(QUEUE_BASE + "/serve-next",
                          json={"barber_id": salon_barber.barber_id,
                                "salon_id": salon.salon_id},
                          headers=admin_headers)
        assert res.status_code == 200, res.text
        first = try_receive(ws, timeout=5.0)
        assert first is not None, (
            f"successful serve-next produced no WS event (outbox "
            f"{outbox_before}->{_outbox_size()}). BLOCKER owner: WS1/WS2 bridge."
        )
        # Post-commit only: no duplicate second event for the same mutation.
        assert try_receive(ws, timeout=1.5) is None, "duplicate event for one mutation"


# ===========================================================================
# SECURITY 24-26: no hash / secret / PII in WS payloads.
# ===========================================================================


def test_ws24_no_password_hash_in_payloads(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """24: snapshot + event payloads never contain password hashes."""
    _ws_base_for_salon(salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        snap = _recv_event(ws, what="snapshot")
        assert "password_hash" not in _payload_text(snap), snap
        _book(client, customer_headers, salon_barber.barber_id,
              salon_service.service_id, slot_date.isoformat(), "10:00",
              salon_id=salon.salon_id)
        evt = _expect_broadcast(ws, ("waiting", "created", "queue"), "create")
        assert "password_hash" not in _payload_text(evt), evt
        _assert_safe_payload(snap)
        _assert_safe_payload(evt)


def test_ws25_no_secret_material_in_payloads(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """25: payloads never contain JWT secrets / tokens."""
    _ws_base_for_salon(salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        snap = _recv_event(ws, what="snapshot")
        text = _payload_text(snap)
        assert "jwt_secret" not in text and "secret_key" not in text, snap
        assert _token(admin_headers).lower() not in text, "snapshot echoes the JWT"
        _book(client, customer_headers, salon_barber.barber_id,
              salon_service.service_id, slot_date.isoformat(), "10:00",
              salon_id=salon.salon_id)
        evt = _expect_broadcast(ws, ("waiting", "created", "queue"), "create")
        etext = _payload_text(evt)
        assert "jwt_secret" not in etext and "secret_key" not in etext, evt
        assert _token(admin_headers).lower() not in etext, "event echoes the JWT"


def test_ws26_no_pii_in_payloads(
    client, admin_headers, customer_headers,
    salon_barber, salon_service, salon, slot_date, slot_availability,
):
    """26: snapshots + broadcasts carry operational ids only, no customer PII."""
    _ws_base_for_salon(salon.salon_id)
    full = ws_queue_url(salon.salon_id, token=_token(admin_headers),
                        date_str=slot_date.isoformat())
    with client.websocket_connect(full) as ws:
        snap = _recv_event(ws, what="snapshot")
        _assert_safe_payload(snap)
        _book(client, customer_headers, salon_barber.barber_id,
              salon_service.service_id, slot_date.isoformat(), "10:00",
              salon_id=salon.salon_id)
        evt = _expect_broadcast(ws, ("waiting", "created", "queue"), "create")
        _assert_safe_payload(evt)
