"""Сайт городской афиши «Время рядом»."""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vremya.db"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

CATEGORIES = ("Мастер-класс", "Досуг", "Экскурсия", "Спорт", "Концерт", "Выставка")

PLACEHOLDER_BY_CATEGORY = {
    "Мастер-класс": "img/placeholders/workshop.jpg",
    "Досуг": "img/placeholders/leisure.jpg",
    "Экскурсия": "img/placeholders/tour.jpg",
    "Спорт": "img/placeholders/sport.jpg",
    "Концерт": "img/placeholders/concert.jpg",
    "Выставка": "img/placeholders/exhibition.jpg",
}
DEFAULT_PLACEHOLDER = "img/placeholders/default.svg"

app = Flask(__name__)
app.secret_key = "vremya-ryadom-secret-key-otborochnyy"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def ensure_schema(db: sqlite3.Connection) -> None:
    cols = {row["name"] for row in db.execute("PRAGMA table_info(events)").fetchall()}
    if "image" not in cols:
        db.execute("ALTER TABLE events ADD COLUMN image TEXT")
    if "cancelled" not in cols:
        db.execute(
            "ALTER TABLE events ADD COLUMN cancelled INTEGER NOT NULL DEFAULT 0"
        )


def assign_placeholders(db: sqlite3.Connection) -> None:
    """Назначает/обновляет заглушки для событий без своего загруженного фото."""
    for category, path in PLACEHOLDER_BY_CATEGORY.items():
        db.execute(
            """
            UPDATE events
            SET image = ?
            WHERE category = ?
              AND (
                image IS NULL
                OR image = ''
                OR image LIKE 'img/placeholders/%'
              )
            """,
            (path, category),
        )
    db.execute(
        """
        UPDATE events
        SET image = ?
        WHERE image IS NULL OR image = ''
        """,
        (DEFAULT_PLACEHOLDER,),
    )


def init_db() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL UNIQUE,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            datetime TEXT NOT NULL,
            place TEXT NOT NULL,
            description TEXT NOT NULL,
            seats_total INTEGER NOT NULL,
            author_id INTEGER,
            image TEXT,
            cancelled INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, event_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            UNIQUE(user_id, event_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        );
        """
    )
    ensure_schema(db)

    count = db.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
    if count == 0:
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        seed = [
            (
                "Керамика для начинающих",
                "Мастер-класс",
                (now + timedelta(days=1, hours=3)).strftime("%Y-%m-%dT%H:%M"),
                "Молодёжный центр",
                "Познакомитесь с основами работы с глиной: лепка, сушка и роспись. "
                "Все материалы предоставляются. Подходит для новичков от 14 лет.",
                12,
                PLACEHOLDER_BY_CATEGORY["Мастер-класс"],
            ),
            (
                "Вечер настольных игр",
                "Досуг",
                (now + timedelta(days=2, hours=5)).strftime("%Y-%m-%dT%H:%M"),
                "Библиотека № 1",
                "Тёплый вечер за любимыми настольными играми. Можно прийти компанией "
                "или присоединиться к уже собранным столам. Чай и печенье включены.",
                8,
                PLACEHOLDER_BY_CATEGORY["Досуг"],
            ),
            (
                "Прогулка по старому городу",
                "Экскурсия",
                (now + timedelta(days=4, hours=2)).strftime("%Y-%m-%dT%H:%M"),
                "Центральная площадь",
                "Пешая экскурсия по историческому центру: дворики, легенды улиц "
                "и малоизвестные памятники архитектуры. Длительность около 2 часов.",
                20,
                PLACEHOLDER_BY_CATEGORY["Экскурсия"],
            ),
            (
                "Открытая тренировка",
                "Спорт",
                (now + timedelta(days=5, hours=4)).strftime("%Y-%m-%dT%H:%M"),
                "Городской парк",
                "Функциональная тренировка на свежем воздухе для любого уровня подготовки. "
                "Возьмите удобную одежду и воду.",
                15,
                PLACEHOLDER_BY_CATEGORY["Спорт"],
            ),
            (
                "Акустический вечер",
                "Концерт",
                (now + timedelta(days=10, hours=6)).strftime("%Y-%m-%dT%H:%M"),
                "Кафе «Север»",
                "Живая акустическая музыка местных исполнителей. Уютная атмосфера, "
                "мягкий свет и возможность познакомиться с новыми артистами города.",
                40,
                PLACEHOLDER_BY_CATEGORY["Концерт"],
            ),
            (
                "Выставка городского фото",
                "Выставка",
                (now + timedelta(days=14, hours=1)).strftime("%Y-%m-%dT%H:%M"),
                "Городская галерея",
                "Работы фотографов-любителей и профессионалов о повседневной жизни города. "
                "Вход свободный, экскурсия от куратора в начале вечера.",
                50,
                PLACEHOLDER_BY_CATEGORY["Выставка"],
            ),
        ]
        db.executemany(
            """
            INSERT INTO events
            (title, category, datetime, place, description, seats_total, author_id, image, cancelled)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 0)
            """,
            seed,
        )
        # демо-пользователь: телефон 9001112233, пароль demo12345
        db.execute(
            """
            INSERT INTO users (phone, first_name, last_name, password_hash)
            VALUES (?, ?, ?, ?)
            """,
            (
                "9001112233",
                "Анна",
                "Иванова",
                generate_password_hash("demo12345"),
            ),
        )
    else:
        assign_placeholders(db)

    db.commit()
    db.close()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Войдите в аккаунт, чтобы продолжить.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if digits.startswith("7") and len(digits) == 11:
        digits = digits[1:]
    return digits


def validate_phone(phone: str) -> str | None:
    if not phone:
        return "Укажите телефон."
    if not re.fullmatch(r"\d{10}", phone):
        return "Телефон должен содержать 10 цифр (без кода страны)."
    return None


def format_datetime(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    months = (
        "",
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    )
    return f"{dt.day} {months[dt.month]} {dt.year}, {dt.strftime('%H:%M')}"


def seats_left(event_id: int, seats_total: int) -> int:
    taken = get_db().execute(
        "SELECT COUNT(*) AS c FROM registrations WHERE event_id = ?",
        (event_id,),
    ).fetchone()["c"]
    return max(seats_total - taken, 0)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_event_image(file_storage) -> tuple[str | None, str | None]:
    """Сохраняет изображение. Возвращает (relative_path, error)."""
    if not file_storage or not file_storage.filename:
        return None, None
    if not allowed_file(file_storage.filename):
        return None, "Допустимы только изображения: PNG, JPG, WEBP, GIF."
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_storage.save(UPLOAD_DIR / filename)
    return f"uploads/{filename}", None


def enrich_event(row) -> dict:
    event = dict(row)
    event["cancelled"] = bool(event.get("cancelled"))
    event["seats_left"] = seats_left(event["id"], event["seats_total"])
    event["datetime_display"] = format_datetime(event["datetime"])
    event["short_description"] = (
        event["description"][:120] + "…"
        if len(event["description"]) > 120
        else event["description"]
    )
    image = (event.get("image") or "").strip()
    if not image:
        image = PLACEHOLDER_BY_CATEGORY.get(event["category"], DEFAULT_PLACEHOLDER)
    event["image"] = image
    event["image_url"] = url_for("static", filename=image)
    return event


def is_registered(user_id: int, event_id: int) -> bool:
    row = get_db().execute(
        "SELECT 1 FROM registrations WHERE user_id = ? AND event_id = ?",
        (user_id, event_id),
    ).fetchone()
    return row is not None


def is_favorite(user_id: int, event_id: int) -> bool:
    row = get_db().execute(
        "SELECT 1 FROM favorites WHERE user_id = ? AND event_id = ?",
        (user_id, event_id),
    ).fetchone()
    return row is not None


@app.context_processor
def inject_globals():
    return {
        "user": current_user(),
        "categories": CATEGORIES,
        "now_year": datetime.now().year,
    }


@app.route("/")
def index():
    rows = get_db().execute(
        """
        SELECT * FROM events
        WHERE cancelled = 0
          AND datetime >= datetime('now', 'localtime')
        ORDER BY datetime ASC
        LIMIT 3
        """
    ).fetchall()
    events = [enrich_event(r) for r in rows]
    return render_template("index.html", events=events)


@app.route("/afisha")
def afisha():
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    sort = request.args.get("sort") or "date_asc"

    sql = "SELECT * FROM events WHERE cancelled = 0"
    params: list = []

    if q:
        sql += " AND title LIKE ?"
        params.append(f"%{q}%")
    if category:
        sql += " AND category = ?"
        params.append(category)
    if date_from:
        sql += " AND date(datetime) >= date(?)"
        params.append(date_from)
    if date_to:
        sql += " AND date(datetime) <= date(?)"
        params.append(date_to)

    if sort == "date_desc":
        sql += " ORDER BY datetime DESC"
    else:
        sql += " ORDER BY datetime ASC"
        sort = "date_asc"

    rows = get_db().execute(sql, params).fetchall()
    events = [enrich_event(r) for r in rows]
    return render_template(
        "afisha.html",
        events=events,
        q=q,
        category=category,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
    )


@app.route("/event/<int:event_id>")
def event_detail(event_id: int):
    row = get_db().execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        flash("Мероприятие не найдено.", "error")
        return redirect(url_for("afisha"))

    event = enrich_event(row)
    user = current_user()
    registered = is_registered(user["id"], event_id) if user else False
    favorite = is_favorite(user["id"], event_id) if user else False
    is_author = bool(user and event.get("author_id") == user["id"])
    return render_template(
        "event.html",
        event=event,
        registered=registered,
        favorite=favorite,
        is_author=is_author,
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("cabinet"))

    errors: dict[str, str] = {}
    form = {
        "phone": "",
        "first_name": "",
        "last_name": "",
    }

    if request.method == "POST":
        form["phone"] = (request.form.get("phone") or "").strip()
        form["first_name"] = (request.form.get("first_name") or "").strip()
        form["last_name"] = (request.form.get("last_name") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        phone = normalize_phone(form["phone"])
        phone_err = validate_phone(phone)
        if phone_err:
            errors["phone"] = phone_err

        if not form["first_name"]:
            errors["first_name"] = "Укажите имя."
        if not form["last_name"]:
            errors["last_name"] = "Укажите фамилию."

        if not password:
            errors["password"] = "Укажите пароль."
        elif not (8 <= len(password) <= 10):
            errors["password"] = "Пароль должен быть от 8 до 10 символов."

        if password != password2:
            errors["password2"] = "Пароли не совпадают."

        if not errors:
            exists = get_db().execute(
                "SELECT 1 FROM users WHERE phone = ?", (phone,)
            ).fetchone()
            if exists:
                errors["phone"] = "Пользователь с таким телефоном уже зарегистрирован."
            else:
                cur = get_db().execute(
                    """
                    INSERT INTO users (phone, first_name, last_name, password_hash)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        phone,
                        form["first_name"],
                        form["last_name"],
                        generate_password_hash(password),
                    ),
                )
                get_db().commit()
                session["user_id"] = cur.lastrowid
                flash("Регистрация прошла успешно. Добро пожаловать!", "success")
                return redirect(url_for("cabinet"))

        form["phone"] = phone or form["phone"]

    return render_template("register.html", form=form, errors=errors)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("cabinet"))

    error = None
    phone_value = ""

    if request.method == "POST":
        phone_value = (request.form.get("phone") or "").strip()
        password = request.form.get("password") or ""
        phone = normalize_phone(phone_value)
        user = get_db().execute(
            "SELECT * FROM users WHERE phone = ?", (phone,)
        ).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "Неверный телефон или пароль"
        else:
            session["user_id"] = user["id"]
            flash("Вы успешно вошли.", "success")
            next_url = request.args.get("next") or url_for("cabinet")
            if not str(next_url).startswith("/"):
                next_url = url_for("cabinet")
            return redirect(next_url)
        phone_value = phone or phone_value

    return render_template("login.html", error=error, phone=phone_value)


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из аккаунта.", "success")
    return redirect(url_for("index"))


@app.route("/cabinet")
@login_required
def cabinet():
    user = current_user()
    db = get_db()

    registered_rows = db.execute(
        """
        SELECT e.* FROM events e
        JOIN registrations r ON r.event_id = e.id
        WHERE r.user_id = ? AND e.cancelled = 0
        ORDER BY e.datetime ASC
        """,
        (user["id"],),
    ).fetchall()

    favorite_rows = db.execute(
        """
        SELECT e.* FROM events e
        JOIN favorites f ON f.event_id = e.id
        WHERE f.user_id = ? AND e.cancelled = 0
        ORDER BY e.datetime ASC
        """,
        (user["id"],),
    ).fetchall()

    created_rows = db.execute(
        """
        SELECT * FROM events
        WHERE author_id = ?
        ORDER BY cancelled ASC, datetime ASC
        """,
        (user["id"],),
    ).fetchall()

    return render_template(
        "cabinet.html",
        registered_events=[enrich_event(r) for r in registered_rows],
        favorite_events=[enrich_event(r) for r in favorite_rows],
        created_events=[enrich_event(r) for r in created_rows],
    )


@app.route("/event/<int:event_id>/register", methods=["POST"])
@login_required
def register_event(event_id: int):
    user = current_user()
    db = get_db()
    event = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not event:
        flash("Мероприятие не найдено.", "error")
        return redirect(url_for("afisha"))

    if event["cancelled"]:
        flash("Мероприятие отменено, запись невозможна.", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    if is_registered(user["id"], event_id):
        flash("Вы уже записаны на это мероприятие.", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    if seats_left(event_id, event["seats_total"]) <= 0:
        flash("Свободных мест нет.", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    db.execute(
        """
        INSERT INTO registrations (user_id, event_id, created_at)
        VALUES (?, ?, ?)
        """,
        (user["id"], event_id, datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()
    flash("Вы записаны на мероприятие.", "success")
    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/event/<int:event_id>/unregister", methods=["POST"])
@login_required
def unregister_event(event_id: int):
    user = current_user()
    get_db().execute(
        "DELETE FROM registrations WHERE user_id = ? AND event_id = ?",
        (user["id"], event_id),
    )
    get_db().commit()
    flash("Запись отменена.", "success")
    next_url = request.form.get("next") or url_for("event_detail", event_id=event_id)
    if not str(next_url).startswith("/"):
        next_url = url_for("cabinet")
    return redirect(next_url)


@app.route("/event/<int:event_id>/cancel", methods=["POST"])
@login_required
def cancel_event(event_id: int):
    user = current_user()
    db = get_db()
    event = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not event:
        flash("Мероприятие не найдено.", "error")
        return redirect(url_for("cabinet"))

    if event["author_id"] != user["id"]:
        flash("Отменить можно только своё мероприятие.", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    if event["cancelled"]:
        flash("Мероприятие уже отменено.", "error")
        return redirect(url_for("event_detail", event_id=event_id))

    db.execute("UPDATE events SET cancelled = 1 WHERE id = ?", (event_id,))
    db.commit()
    flash("Мероприятие отменено и скрыто из афиши.", "success")

    next_url = request.form.get("next") or url_for("cabinet")
    if not str(next_url).startswith("/"):
        next_url = url_for("cabinet")
    return redirect(next_url)


@app.route("/event/<int:event_id>/favorite", methods=["POST"])
@login_required
def toggle_favorite(event_id: int):
    user = current_user()
    db = get_db()
    event = db.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone()
    if not event:
        flash("Мероприятие не найдено.", "error")
        return redirect(url_for("afisha"))

    if is_favorite(user["id"], event_id):
        db.execute(
            "DELETE FROM favorites WHERE user_id = ? AND event_id = ?",
            (user["id"], event_id),
        )
        db.commit()
        flash("Удалено из избранного.", "success")
    else:
        db.execute(
            "INSERT INTO favorites (user_id, event_id) VALUES (?, ?)",
            (user["id"], event_id),
        )
        db.commit()
        flash("Добавлено в избранное.", "success")

    next_url = request.form.get("next") or url_for("event_detail", event_id=event_id)
    if not str(next_url).startswith("/"):
        next_url = url_for("event_detail", event_id=event_id)
    return redirect(next_url)


@app.route("/create", methods=["GET", "POST"])
@login_required
def create_event():
    errors: dict[str, str] = {}
    form = {
        "title": "",
        "category": "",
        "datetime": "",
        "place": "",
        "description": "",
        "seats_total": "",
    }

    if request.method == "POST":
        for key in form:
            form[key] = (request.form.get(key) or "").strip()

        if not form["title"]:
            errors["title"] = "Укажите название."
        if form["category"] not in CATEGORIES:
            errors["category"] = "Выберите категорию."
        if not form["datetime"]:
            errors["datetime"] = "Укажите дату и время."
        else:
            try:
                datetime.fromisoformat(form["datetime"])
            except ValueError:
                errors["datetime"] = "Некорректные дата и время."
        if not form["place"]:
            errors["place"] = "Укажите место проведения."
        if not form["description"]:
            errors["description"] = "Добавьте описание."
        if not form["seats_total"]:
            errors["seats_total"] = "Укажите количество мест."
        else:
            try:
                seats = int(form["seats_total"])
                if seats < 1:
                    raise ValueError
                form["seats_total"] = str(seats)
            except ValueError:
                errors["seats_total"] = "Количество мест должно быть целым числом от 1."

        image_path, image_error = save_event_image(request.files.get("image"))
        if image_error:
            errors["image"] = image_error

        if not errors:
            if not image_path:
                image_path = PLACEHOLDER_BY_CATEGORY.get(
                    form["category"], DEFAULT_PLACEHOLDER
                )
            user = current_user()
            cur = get_db().execute(
                """
                INSERT INTO events
                (title, category, datetime, place, description, seats_total, author_id, image, cancelled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    form["title"],
                    form["category"],
                    form["datetime"],
                    form["place"],
                    form["description"],
                    int(form["seats_total"]),
                    user["id"],
                    image_path,
                ),
            )
            get_db().commit()
            flash("Мероприятие создано и появилось в афише.", "success")
            return redirect(url_for("event_detail", event_id=cur.lastrowid))

    return render_template("create_event.html", form=form, errors=errors)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="127.0.0.1", port=5000)
else:
    init_db()
