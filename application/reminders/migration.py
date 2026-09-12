"""One-time import of the retired native bedtime preset into normal schedules."""

from datetime import date, datetime, time, timedelta


def migrate_bedtime(store, *, bedtime_time, last_delivered_date=None, title, message):
    if not isinstance(bedtime_time, str) or len(bedtime_time) != 5:
        raise ValueError("Invalid legacy bedtime")
    scheduled_time = time.fromisoformat(bedtime_time)
    last = date.fromisoformat(last_delivered_date) if last_delivered_date else None
    title = store.text(title, "title", 120)
    message = store.text(message, "message", 2000)
    now = store.clock()
    today = datetime.fromtimestamp(now).date()
    due = datetime.combine(today, scheduled_time)
    yesterday = due - timedelta(days=1)
    if 0 <= now - yesterday.timestamp() <= 1800:
        due = yesterday
    if last and last >= due.date():
        due = datetime.combine(last + timedelta(days=1), scheduled_time)
    if now - due.timestamp() > 1800:
        due = datetime.combine(today, scheduled_time)
        if now - due.timestamp() > 1800:
            due += timedelta(days=1)
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY)")
        if db.execute("SELECT 1 FROM migrations WHERE name='native-bedtime'").fetchone():
            return {"ok": True}
        db.execute("""INSERT INTO reminders
            (id,character_name,title,message,due_at,recurrence,created_at,updated_at)
            VALUES ('legacy-bedtime','*',?,?,?,'daily',?,?)""",
            (title, message, due.timestamp(), now, now))
        # Kept independently of the reminder: deleting it must not reimport it
        # after a crash between the database commit and the native settings save.
        db.execute("INSERT INTO migrations VALUES ('native-bedtime')")
    return {"ok": True}
