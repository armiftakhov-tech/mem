import threading
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app import timeutil
from app.db import session_for
from app.models import Account, Assignment, AssignmentReview, Child, Family, Notification, Parent, Reminder
from app.security import hash_password
from app.services import generate_today, process_due_reminders
from tests.conftest import key, setup_family


def today():
    return timeutil.today("Europe/Moscow").isoformat()


def new_assignment(api, check="23:58", due="23:50", **kw):
    body = {
        "idempotency_key": key(),
        "child_id": api.child_id,
        "text": "Математика: стр. 42",
        "date": today(),
        "due_time": due,
        "check_time": check,
        **kw,
    }
    r = api.post("/assignments", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def count(engine, model, *where):
    with session_for(engine) as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


# 1
def test_check_before_due_rejected(papa):
    r = papa.post(
        "/assignments",
        json={"idempotency_key": key(), "child_id": papa.child_id, "text": "x", "date": today(), "due_time": "19:00", "check_time": "17:00"},
    )
    assert r.status_code == 422


# 2
def test_other_family_gets_404(papa, make_api, engine):
    a = new_assignment(papa)
    # Вторая семья в той же БД — напрямую, открытой регистрации нет.
    other = make_api()
    with session_for(engine) as db:
        acc = Account(login="x@x", kind="parent", password_hash=hash_password("password9"))
        fam = Family(timezone="UTC")
        db.add_all([acc, fam])
        db.flush()
        db.add(Parent(family_id=fam.id, account_id=acc.id, name="X"))
        db.commit()
    assert other.post("/auth/login", json={"login": "x@x", "password": "password9"}).status_code == 200
    assert other.get(f"/assignments/{a['id']}").status_code == 404
    assert other.post(f"/assignments/{a['id']}/reviews", json={"idempotency_key": key(), "outcome": "done"}).status_code == 404
    assert other.get("/assignments/today").json() == []


# 3
def test_double_create_is_one_record(papa, engine):
    body = {"idempotency_key": key(), "child_id": papa.child_id, "text": "x", "date": today(), "check_time": "23:59"}
    r1, r2 = papa.post("/assignments", json=body), papa.post("/assignments", json=body)
    assert r1.json()["id"] == r2.json()["id"]
    assert count(engine, Assignment) == 1


# 4
def test_concurrent_reviews_one_current(papa, mama, engine):
    a = new_assignment(papa)
    results = []

    def go(api, outcome):
        results.append(api.post(f"/assignments/{a['id']}/reviews", json={"idempotency_key": key(), "outcome": outcome}).status_code)

    ts = [threading.Thread(target=go, args=(papa, "done")), threading.Thread(target=go, args=(mama, "not_done"))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == [200, 409]
    assert count(engine, AssignmentReview, AssignmentReview.is_current.is_(True)) == 1


# 5
def test_correction_keeps_previous_review(papa, mama, engine):
    a = new_assignment(papa)
    r = papa.post(f"/assignments/{a['id']}/reviews", json={"idempotency_key": key(), "outcome": "partial"}).json()
    first = r["current_review"]["id"]
    r = mama.post(f"/assignments/{a['id']}/reviews", json={"idempotency_key": key(), "outcome": "done", "supersedes_review_id": first}).json()
    assert r["current_review"]["outcome"] == "done"
    assert [x["outcome"] for x in r["reviews"]] == ["partial", "done"]
    # Устаревшее исправление получает конфликт.
    stale = papa.post(f"/assignments/{a['id']}/reviews", json={"idempotency_key": key(), "outcome": "not_done", "supersedes_review_id": first})
    assert stale.status_code == 409
    assert count(engine, AssignmentReview) == 2


# 6
def test_time_change_recreates_reminder(papa, engine):
    a = new_assignment(papa, check="23:58")
    r = papa.patch(
        f"/assignments/{a['id']}",
        json={"command_id": key(), "version": a["version"], "text": a["text"], "date": today(), "due_time": "23:50", "check_time": "23:59"},
    )
    assert r.status_code == 200
    with session_for(engine) as db:
        rs = db.scalars(select(Reminder).where(Reminder.assignment_id == a["id"])).all()
    assert sorted(x.status for x in rs) == ["cancelled", "scheduled"]
    # Старая версия — конфликт, а не тихая перезапись.
    stale = papa.patch(
        f"/assignments/{a['id']}",
        json={"command_id": key(), "version": a["version"], "text": "y", "date": today(), "check_time": "23:59"},
    )
    assert stale.status_code == 409


# 7
def test_cancel_keeps_in_history(papa):
    a = new_assignment(papa)
    r = papa.post(f"/assignments/{a['id']}/cancel", json={"command_id": key(), "version": a["version"]})
    assert r.json()["state"] == "cancelled"
    h = papa.get("/history").json()
    assert [i["id"] for i in h["items"]] == [a["id"]]
    assert h["summary"]["cancelled"] == 1


# 8
def test_new_parent_equal_rights(papa, mama, engine):
    a = new_assignment(papa)
    assert mama.get(f"/assignments/{a['id']}").status_code == 200
    r = mama.post(f"/assignments/{a['id']}/cancel", json={"command_id": key(), "version": a["version"]})
    assert r.status_code == 200
    with session_for(engine) as db:
        assert db.scalar(select(func.count()).select_from(Parent)) == 2
    assert {c["id"] for c in mama.me["children"]} == {papa.child_id}
    # Повторное принятие тем же аккаунтом — no-op.
    assert count(engine, Parent) == 2


# 9
def test_notification_settings_are_per_parent(papa, mama):
    papa.put("/settings/notifications", json={"reminders_enabled": False, "changes_enabled": False, "browser_notifications_enabled": True})
    assert mama.get("/settings/notifications").json()["reminders_enabled"] is True


# 10, 12
def test_reminder_processed_once(papa, mama, engine):
    a = new_assignment(papa)
    later = datetime.now(UTC) + timedelta(days=1)
    with session_for(engine) as db:
        assert process_due_reminders(db, later) == 1
        db.commit()
        assert process_due_reminders(db, later) == 0
        db.commit()
    assert count(engine, Notification, Notification.type == "reminder") == 2  # два родителя
    assert mama.get("/notifications/unread").json()["unread"] >= 1
    assert a["id"]


def test_change_notifies_other_parent_only(papa, mama, engine):
    new_assignment(papa)
    assert count(engine, Notification, Notification.parent_id == mama.me["parent"]["id"]) == 1
    assert count(engine, Notification, Notification.parent_id == papa.me["parent"]["id"]) == 0


def recurrence(api, **kw):
    body = {
        "idempotency_key": key(),
        "child_id": api.child_id,
        "text": "Собрать портфель",
        "weekdays": 127,
        "due_time": "23:00",
        "check_time": "23:30",
        "starts_on": today(),
        **kw,
    }
    r = api.post("/recurrences", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# 19
def test_recurrence_generates_once_per_day(papa, engine):
    rec = recurrence(papa)
    with session_for(engine) as db:
        assert generate_today(db) == 0
        db.commit()
    assert count(engine, Assignment, Assignment.recurrence_id == rec["id"]) == 1


def test_recurrence_no_backfill(papa, engine):
    past = (date.fromisoformat(today()) - timedelta(days=5)).isoformat()
    rec = recurrence(papa, starts_on=past)
    assert count(engine, Assignment, Assignment.recurrence_id == rec["id"]) == 1


# 20
def test_recurrence_change_keeps_existing(papa, engine):
    rec = recurrence(papa)
    r = papa.patch(f"/recurrences/{rec['id']}", json={"command_id": key(), "version": rec["version"], "status": "paused"})
    assert r.json()["status"] == "paused"
    with session_for(engine) as db:
        a = db.scalar(select(Assignment).where(Assignment.recurrence_id == rec["id"]))
    assert a.state == "active"


# 21
def test_delete_child_rules(papa, engine):
    kid = papa.post("/children", json={"name": "Петя"}).json()
    assert papa.delete(f"/children/{kid['id']}").status_code == 200
    assert count(engine, Child) == 1
    new_assignment(papa)
    assert papa.delete(f"/children/{papa.child_id}").status_code == 409


# 22, 23
def child_api(papa, make_api, login="masha"):
    papa.put(f"/children/{papa.child_id}/account", json={"login": login, "password": "secret1"})
    kid = make_api()
    assert kid.post("/auth/login", json={"login": login, "password": "secret1"}).status_code == 200
    return kid


def test_child_sees_only_own_and_cannot_parent(papa, make_api):
    mine = new_assignment(papa)
    petya = papa.post("/children", json={"name": "Петя"}).json()
    other = new_assignment(papa, child_id=petya["id"])
    kid = child_api(papa, make_api)
    assert [a["id"] for a in kid.get("/assignments/today").json()] == [mine["id"]]
    assert kid.get(f"/assignments/{other['id']}").status_code == 404
    assert kid.post("/assignments", json={"idempotency_key": key(), "child_id": papa.child_id, "text": "x", "date": today(), "check_time": "23:59"}).status_code == 403
    assert kid.post(f"/assignments/{mine['id']}/reviews", json={"idempotency_key": key(), "outcome": "done"}).status_code == 403
    assert kid.get("/children").status_code == 403


def test_child_mark_does_not_close_and_is_idempotent(papa, make_api, engine):
    a = new_assignment(papa)
    kid = child_api(papa, make_api)
    r1 = kid.post(f"/assignments/{a['id']}/mark", json={"comment": "сделала"})
    r2 = kid.post(f"/assignments/{a['id']}/mark", json={})
    assert r1.status_code == r2.status_code == 200
    assert r2.json()["state"] == "active"
    assert r2.json()["child_marked_at"]
    assert count(engine, Notification, Notification.type == "child_marked") == 1


def test_csrf_required(papa):
    r = papa.c.post("/children", json={"name": "Без CSRF"})
    assert r.status_code == 403


def test_login_rate_limit(papa, make_api):
    anon = make_api()
    for _ in range(5):
        assert anon.post("/auth/login", json={"login": "papa@home", "password": "wrong"}).status_code == 401
    assert anon.post("/auth/login", json={"login": "papa@home", "password": "password1"}).status_code == 429


def test_setup_only_once(papa, make_api):
    other = make_api()
    try:
        setup_family(other, email="b@b")
    except AssertionError:
        return
    raise AssertionError("second setup must fail")


def test_invitation_single_use(papa, mama, make_api):
    code = papa.post("/invitations").json()["code"]
    r = make_api().post("/auth/accept-invitation", json={"code": code, "email": "c@c", "password": "password3", "name": "C"})
    assert r.status_code == 200
    r = make_api().post("/auth/accept-invitation", json={"code": code, "email": "d@d", "password": "password3", "name": "D"})
    assert r.status_code == 400


def test_today_groups_and_history_summary(papa):
    a = new_assignment(papa)
    papa.post(f"/assignments/{a['id']}/reviews", json={"idempotency_key": key(), "outcome": "done", "comment": "Молодец"})
    t = papa.get("/assignments/today").json()
    assert t[0]["state"] == "closed" and t[0]["comments_count"] == 1
    assert papa.get("/history").json()["summary"]["done"] == 1
