import os
import sqlite3
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "6957346235"))

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
PHOTO_DIR = DATA_DIR / "photos"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

# Esamos duomenų bazės pavadinimas nekeičiamas.
DB = DATA_DIR / "ledas.db"


PRODUCTS = {
    1: ("1 💎", "35 €"),
    2: ("2 💎", "60 €"),
    3: ("5 💎", "100 €"),
    4: ("0.5 ❄️", "55 €"),
    5: ("1 ❄️", "100 €"),
    6: ("1 🌲", "15 €"),
    7: ("2 🌲", "30 €"),
    8: ("5 🌲", "70 €"),
}

CATEGORIES = {
    "diamond": ("💎", [1, 2, 3]),
    "snow": ("❄️", [4, 5]),
    "tree": ("🌲", [6, 7, 8]),
}

LOCATIONS = {
    "parkas": "🌳 PARKAS",
    "mikras": "🏙️ MIKRAS",
}


def connect():
    db = sqlite3.connect(DB)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def add_column_if_missing(db, table, column, definition):
    columns = [
        row[1]
        for row in db.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    ]

    if column not in columns:
        db.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def setup_database():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category INTEGER NOT NULL,
                filename TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                user_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Nauji laukai vietų ir rezervacijų valdymui.
        add_column_if_missing(db, "orders", "location", "TEXT")
        add_column_if_missing(db, "orders", "stock_id", "INTEGER")

        add_column_if_missing(db, "stock", "location", "TEXT")
        add_column_if_missing(
            db, "stock", "reserved_order_id", "INTEGER"
        )

        # Esami klientai išsaugo savo prieigą.
        db.execute("""
            INSERT OR IGNORE INTO customers
                (user_id, status)
            SELECT DISTINCT user_id, 'approved'
            FROM orders
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_stock_location
            ON stock(location, category)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_stock_reservation
            ON stock(reserved_order_id)
        """)


def is_owner(user_id):
    return user_id == OWNER_ID


def customer_status(user_id):
    with connect() as db:
        result = db.execute(
            "SELECT status FROM customers WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return result[0] if result else None


def has_access(user_id):
    return is_owner(user_id) or customer_status(user_id) == "approved"


def get_stock_counts(location=None):
    with connect() as db:
        if location:
            counts = db.execute(
                """
                SELECT category, COUNT(*)
                FROM stock
                WHERE location=?
                AND reserved_order_id IS NULL
                GROUP BY category
                """,
                (location,)
            ).fetchall()
        else:
            counts = db.execute(
                """
                SELECT category, COUNT(*)
                FROM stock
                WHERE location IS NOT NULL
                AND reserved_order_id IS NULL
                GROUP BY category
                """
            ).fetchall()

    return dict(counts)


def location_keyboard(prefix, back_callback):
    buttons = [
        [
            InlineKeyboardButton(
                "🌳 PARKAS",
                callback_data=f"{prefix}_parkas"
            )
        ],
        [
            InlineKeyboardButton(
                "🏙️ MIKRAS",
                callback_data=f"{prefix}_mikras"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ GRĮŽTI",
                callback_data=back_callback
            )
        ],
    ]

    return InlineKeyboardMarkup(buttons)


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🛍️ PREKIŲ KATALOGAS",
            callback_data="catalog"
        )],
        [InlineKeyboardButton(
            "📦 MANO UŽSAKYMAI",
            callback_data="myorders"
        )],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📦 UŽSAKYMAI",
            callback_data="admin_orders"
        )],
        [InlineKeyboardButton(
            "📸 ĮKELTI PREKES",
            callback_data="upload_menu"
        )],
        [InlineKeyboardButton(
            "📊 PREKIŲ LIKUTIS",
            callback_data="stock"
        )],
        [InlineKeyboardButton(
            "📍 VIETŲ VALDYMAS",
            callback_data="location_management"
        )],
    ])


# KLIENTŲ PRIEIGOS PRAŠYMAI

async def request_access(update, context):
    user = update.effective_user
    status = customer_status(user.id)

    if status == "approved":
        await update.message.reply_text(
            "🔵🔴 PEPSI\n\n"
            "Sveiki sugrįžę!\n\n"
            "Pasirinkite, ką norite daryti:",
            reply_markup=main_keyboard()
        )
        return

    if status == "pending":
        await update.message.reply_text(
            "⏳ Jūsų prieigos prašymas jau išsiųstas.\n\n"
            "Prašome palaukti administratoriaus patvirtinimo."
        )
        return

    if status == "rejected":
        await update.message.reply_text(
            "❌ Jūsų prieigos prašymas buvo atmestas.\n\n"
            "Jeigu turite klausimų, susisiekite su administratoriumi."
        )
        return

    with connect() as db:
        db.execute("""
            INSERT INTO customers
                (user_id, status, username, first_name)
            VALUES (?, 'pending', ?, ?)
        """, (
            user.id,
            user.username,
            user.first_name
        ))

    await update.message.reply_text(
        "🔵🔴 PEPSI\n\n"
        "👋 Sveiki!\n\n"
        "Norėdami naudotis parduotuve, turite gauti "
        "administratoriaus patvirtinimą.\n\n"
        "⏳ Jūsų prašymas išsiųstas.\n"
        "Apie patvirtinimą informuosime automatiškai."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ PATVIRTINTI",
                callback_data=f"access_approve_{user.id}"
            ),
            InlineKeyboardButton(
                "❌ ATMESTI",
                callback_data=f"access_reject_{user.id}"
            )
        ]
    ])

    try:
        await context.bot.send_message(
            OWNER_ID,
            "🔔 NAUJAS PRIEIGOS PRAŠYMAS\n\n"
            f"Vardas: {user.first_name}\n"
            f"Telegram ID: {user.id}\n"
            f"Naudotojo vardas: "
            f"@{user.username if user.username else 'nenurodytas'}",
            reply_markup=keyboard
        )
    except Exception:
        pass


# PRADŽIA

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_owner(update.effective_user.id):
        await update.message.reply_text(
            "🔵🔴 PEPSI",
            reply_markup=admin_keyboard()
        )
        return

    await request_access(update, context)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return

    await update.message.reply_text(
        "🔵🔴 PEPSI",
        reply_markup=admin_keyboard()
    )


# KLIENTO KATALOGAS

async def show_catalog(query):
    await query.edit_message_text(
        "🔵🔴 PEPSI | PREKIŲ KATALOGAS\n\n"
        "Pasirinkite atsiėmimo vietą:",
        reply_markup=location_keyboard(
            "customerloc",
            "main_menu"
        )
    )


async def show_categories(query, location):
    if location not in LOCATIONS:
        return

    keyboard = [
        [InlineKeyboardButton("💎", callback_data=f"cat_{location}_diamond")],
        [InlineKeyboardButton("❄️", callback_data=f"cat_{location}_snow")],
        [InlineKeyboardButton("🌲", callback_data=f"cat_{location}_tree")],
        [InlineKeyboardButton("⬅️ VIETOS", callback_data="catalog")],
    ]

    await query.edit_message_text(
        f"🔵🔴 PEPSI | {LOCATIONS[location]}\n\n"
        "Pasirinkite kategoriją:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_category(query, category_key, location):
    if category_key not in CATEGORIES:
        return

    if location not in LOCATIONS:
        return

    emoji, product_ids = CATEGORIES[category_key]
    stock_counts = get_stock_counts(location)

    buttons = []

    for product_id in product_ids:
        name, price = PRODUCTS[product_id]

        if stock_counts.get(product_id, 0) > 0:
            label = f"✅ {name} – {price}"
            callback = f"buy_{location}_{product_id}"
        else:
            label = f"❌ {name} – {price}"
            callback = f"unavailable_{location}_{product_id}"

        buttons.append([
            InlineKeyboardButton(label, callback_data=callback)
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ KATEGORIJOS",
            callback_data=f"customerloc_{location}"
        )
    ])

    await query.edit_message_text(
        f"🔵🔴 PEPSI | {LOCATIONS[location]} | {emoji}\n\n"
        "Pasirinkite norimą prekę:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# KLIENTO UŽSAKYMAI

async def show_orders(query, user_id):
    with connect() as db:
        orders = db.execute(
            """
            SELECT id, product, status, location
            FROM orders
            WHERE user_id=?
            ORDER BY id DESC
            """,
            (user_id,)
        ).fetchall()

    if not orders:
        await query.edit_message_text(
            "📦 Jūs dar neturite užsakymų.",
            reply_markup=main_keyboard()
        )
        return

    text = "📦 MANO UŽSAKYMAI\n\n"
    buttons = []

    for order_id, product, status, location in orders:
        name, price = PRODUCTS.get(
            product, ("Nežinoma prekė", "")
        )

        location_name = LOCATIONS.get(location, "Nenurodyta")

        text += (
            f"Užsakymas #{order_id}\n"
            f"Prekė: {name} – {price}\n"
            f"Vieta: {location_name}\n"
            f"Būsena: {status}\n\n"
        )

        if status == "LAUKIA APMOKĖJIMO":
            buttons.append([
                InlineKeyboardButton(
                    f"❌ ATŠAUKTI #{order_id}",
                    callback_data=f"cancel_{order_id}"
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ GRĮŽTI",
            callback_data="main_menu"
        )
    ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ADMINISTRATORIAUS LIKUČIAI

async def show_location_stock(query, location):
    if location not in LOCATIONS:
        return

    stock_counts = get_stock_counts(location)

    text = (
        f"📊 PREKIŲ LIKUTIS\n"
        f"{LOCATIONS[location]}\n\n"
    )

    for product_id, (name, price) in PRODUCTS.items():
        count = stock_counts.get(product_id, 0)
        emoji = "✅" if count > 0 else "❌"

        text += f"{emoji} {name} – {count} vnt.\n"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ VIETOS",
                    callback_data="stock"
                )
            ]
        ])
    )


# MYGTUKŲ APDOROJIMAS

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # ADMINISTRATORIAUS PRIEIGOS PATVIRTINIMAS

    if data.startswith("access_approve_") or data.startswith("access_reject_"):

        if not is_owner(user_id):
            return

        parts = data.split("_")
        action = parts[1]
        customer_id = int(parts[2])

        status = "approved" if action == "approve" else "rejected"

        with connect() as db:
            customer = db.execute(
                "SELECT status FROM customers WHERE user_id=?",
                (customer_id,)
            ).fetchone()

            if not customer or customer[0] != "pending":
                await query.edit_message_text(
                    "Šis prašymas jau buvo apdorotas."
                )
                return

            db.execute(
                "UPDATE customers SET status=? WHERE user_id=?",
                (status, customer_id)
            )

        if status == "approved":
            await context.bot.send_message(
                customer_id,
                "🔵🔴 PEPSI\n\n"
                "✅ Jūsų prieiga patvirtinta!\n\n"
                "Sveiki atvykę į PEPSI parduotuvę.",
                reply_markup=main_keyboard()
            )

            await query.edit_message_text(
                f"✅ Klientui {customer_id} suteikta prieiga."
            )

        else:
            try:
                await context.bot.send_message(
                    customer_id,
                    "❌ Jūsų prieigos prašymas atmestas."
                )
            except Exception:
                pass

            await query.edit_message_text(
                f"❌ Klientui {customer_id} prieiga atmesta."
            )

        return

    # KLIENTŲ PRIEIGOS TIKRINIMAS

    if not has_access(user_id):
        await query.answer(
            "⏳ Pirmiausia reikia gauti administratoriaus patvirtinimą.",
            show_alert=True
        )
        return

    # PAGRINDINIS MENIU

    if data == "main_menu":
        await query.edit_message_text(
            "🔵🔴 PEPSI\n\nPasirinkite, ką norite daryti:",
            reply_markup=main_keyboard()
        )
        return

    # KLIENTO VIETOS PASIRINKIMAS

    if data.startswith("customerloc_"):
        location = data.replace("customerloc_", "", 1)
        await show_categories(query, location)
        return

    # KATALOGAS

    if data == "catalog":
        await show_catalog(query)
        return

    # KATEGORIJOS PASIRINKIMAS SU VIETA

    if data.startswith("cat_"):
        parts = data.split("_")

        if len(parts) != 3:
            return

        location = parts[1]
        category_key = parts[2]

        await show_category(query, category_key, location)
        return

    if data == "myorders":
        await show_orders(query, user_id)
        return

    # UŽSAKYMO ATŠAUKIMAS

    if data.startswith("cancel_"):
        order_id = int(data.split("_")[1])

        with connect() as db:
            order = db.execute(
                """
                SELECT user_id, status, stock_id
                FROM orders
                WHERE id=?
                """,
                (order_id,)
            ).fetchone()

            if not order:
                await query.edit_message_text(
                    "Užsakymas nerastas.",
                    reply_markup=main_keyboard()
                )
                return

            customer_id, status, stock_id = order

            if customer_id != user_id:
                return

            if status != "LAUKIA APMOKĖJIMO":
                await query.answer(
                    "Šio užsakymo atšaukti nebegalima.",
                    show_alert=True
                )
                return

            db.execute(
                "UPDATE orders SET status=? WHERE id=?",
                ("ATŠAUKTA", order_id)
            )

            if stock_id:
                db.execute(
                    """
                    UPDATE stock
                    SET reserved_order_id=NULL
                    WHERE id=? AND reserved_order_id=?
                    """,
                    (stock_id, order_id)
                )

        await query.edit_message_text(
            f"⚪ Užsakymas #{order_id} atšauktas.",
            reply_markup=main_keyboard()
        )

        try:
            await context.bot.send_message(
                OWNER_ID,
                f"⚪ Klientas atšaukė užsakymą #{order_id}."
            )
        except Exception:
            pass

        return

    # NEPRIEINAMA PREKĖ

    if data.startswith("unavailable_"):
        await query.answer(
            "❌ Šiuo metu šios prekės nėra pasirinktoje vietoje.",
            show_alert=True
        )
        return

    # PREKĖS PASIRINKIMAS

    if data.startswith("buy_"):
        parts = data.split("_")

        if len(parts) != 3:
            return

        location = parts[1]
        product_id = int(parts[2])

        if location not in LOCATIONS or product_id not in PRODUCTS:
            return

        with connect() as db:
            available = db.execute(
                """
                SELECT COUNT(*)
                FROM stock
                WHERE category=?
                AND location=?
                AND reserved_order_id IS NULL
                """,
                (product_id, location)
            ).fetchone()[0]

        if available <= 0:
            await query.answer(
                "❌ Šios prekės nebėra.",
                show_alert=True
            )
            return

        name, price = PRODUCTS[product_id]

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "💵 GRYNIEJI PINIGAI",
                callback_data=f"cash_{location}_{product_id}"
            )],
            [InlineKeyboardButton(
                "⬅️ GRĮŽTI",
                callback_data=f"back_{location}_{product_id}"
            )]
        ])

        await query.edit_message_text(
            "🔵🔴 PEPSI\n\n"
            f"Vieta: {LOCATIONS[location]}\n"
            f"Pasirinkta prekė: {name}\n"
            f"Kaina: {price}\n\n"
            "Pasirinkite mokėjimo būdą:",
            reply_markup=keyboard
        )
        return

    # GRĮŽIMAS Į KATEGORIJĄ

    if data.startswith("back_"):
        parts = data.split("_")

        if len(parts) != 3:
            return

        location = parts[1]
        product_id = int(parts[2])

        category_key = next(
            (
                key for key, (_, ids) in CATEGORIES.items()
                if product_id in ids
            ),
            None
        )

        if category_key:
            await show_category(query, category_key, location)
        return

    # GRYNIEJI PINIGAI IR PREKĖS REZERVACIJA

    if data.startswith("cash_"):
        parts = data.split("_")

        if len(parts) != 3:
            return

        location = parts[1]
        product_id = int(parts[2])

        if location not in LOCATIONS or product_id not in PRODUCTS:
            return

        name, price = PRODUCTS[product_id]

        with connect() as db:
            # Pasirenkama viena laisva prekė būtent šioje vietoje.
            stock_item = db.execute(
                """
                SELECT id
                FROM stock
                WHERE category=?
                AND location=?
                AND reserved_order_id IS NULL
                ORDER BY id
                LIMIT 1
                """,
                (product_id, location)
            ).fetchone()

            if not stock_item:
                await query.edit_message_text(
                    "❌ Šios prekės šiuo metu nebėra.",
                    reply_markup=main_keyboard()
                )
                return

            stock_id = stock_item[0]

            cursor = db.execute(
                """
                INSERT INTO orders
                    (user_id, product, status, location, stock_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    product_id,
                    "LAUKIA APMOKĖJIMO",
                    location,
                    stock_id
                )
            )

            order_id = cursor.lastrowid

            db.execute(
                """
                UPDATE stock
                SET reserved_order_id=?
                WHERE id=?
                AND reserved_order_id IS NULL
                """,
                (order_id, stock_id)
            )

        await query.edit_message_text(
            f"🔵🔴 PEPSI\n\n"
            f"✅ UŽSAKYMAS #{order_id}\n\n"
            f"Prekė: {name}\n"
            f"Kaina: {price}\n"
            f"Atsiėmimo vieta: {LOCATIONS[location]}\n"
            f"Mokėjimas: 💵 Grynieji pinigai\n\n"
            "Administratorius susisieks dėl apmokėjimo.\n"
            "Prekė rezervuota iki užsakymo patvirtinimo."
        )

        try:
            await context.bot.send_message(
                OWNER_ID,
                f"🛍️ NAUJAS UŽSAKYMAS #{order_id}\n"
                f"Kliento ID: {user_id}\n"
                f"Prekė: {name} – {price}\n"
                f"Atsiėmimo vieta: {LOCATIONS[location]}\n"
                f"Mokėjimas: Grynieji pinigai\n\n"
                f"Patvirtinimas: /admin"
            )
        except Exception:
            pass

        return

    # TOLIAU – TIK ADMINISTRATORIUI

    if not is_owner(user_id):
        return

    # UŽSAKYMAI

    if data == "admin_orders":
        with connect() as db:
            orders = db.execute(
                """
                SELECT id, user_id, product, status, location
                FROM orders
                ORDER BY id DESC
                LIMIT 20
                """
            ).fetchall()

        if not orders:
            await query.edit_message_text(
                "Užsakymų nėra.",
                reply_markup=admin_keyboard()
            )
            return

        for order_id, customer_id, product, status, location in orders:
            name, price = PRODUCTS.get(
                product, ("Nežinoma prekė", "")
            )

            location_name = LOCATIONS.get(location, "Nenurodyta")

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ PATVIRTINTI",
                        callback_data=f"approve{order_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ ATMESTI",
                        callback_data=f"reject_{order_id}"
                    )
                ]
            ])

            await context.bot.send_message(
                OWNER_ID,
                f"UŽSAKYMAS #{order_id}\n"
                f"Klientas: {customer_id}\n"
                f"Prekė: {name} – {price}\n"
                f"Vieta: {location_name}\n"
                f"Būsena: {status}",
                reply_markup=keyboard
            )

        await query.edit_message_text(
            "Užsakymai išsiųsti.",
            reply_markup=admin_keyboard()
        )
        return

    # NUOTRAUKŲ ĮKĖLIMO MENIU

    if data == "upload_menu":
        await query.edit_message_text(
            "📸 PASIRINKITE VIETĄ, Į KURIĄ KELSITE PREKES:",
            reply_markup=location_keyboard(
                "uploadloc",
                "admin_back"
            )
        )
        return

    # NUOTRAUKŲ ĮKĖLIMO VIETA

    if data.startswith("uploadloc_"):
        location = data.replace("uploadloc_", "", 1)

        if location not in LOCATIONS:
            return

        context.user_data["upload_location"] = location

        keyboard = [
            [InlineKeyboardButton(
                "💎",
                callback_data=f"uploadcat_{location}_diamond"
            )],
            [InlineKeyboardButton(
                "❄️",
                callback_data=f"uploadcat_{location}_snow"
            )],
            [InlineKeyboardButton(
                "🌲",
                callback_data=f"uploadcat_{location}_tree"
            )],
            [InlineKeyboardButton(
                "⬅️ VIETOS",
                callback_data="upload_menu"
            )],
        ]

        await query.edit_message_text(
            f"📸 {LOCATIONS[location]}\n\n"
            "Pasirinkite prekių kategoriją:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # NUOTRAUKŲ PREKĖS PASIRINKIMAS

    if data.startswith("uploadcat_"):
        parts = data.split("_")

        if len(parts) != 3:
            return

        location = parts[1]
        category_key = parts[2]

        if location not in LOCATIONS or category_key not in CATEGORIES:
            return

        emoji, product_ids = CATEGORIES[category_key]
        stock_counts = get_stock_counts(location)

        buttons = []

        for product_id in product_ids:
            name, price = PRODUCTS[product_id]
            count = stock_counts.get(product_id, 0)

            buttons.append([
                InlineKeyboardButton(
                    f"{name} – {price} ({count} vnt.)",
                    callback_data=f"upload_{location}_{product_id}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "⬅️ KATEGORIJOS",
                callback_data=f"uploadloc_{location}"
            )
        ])

        await query.edit_message_text(
            f"📸 {LOCATIONS[location]} | {emoji}\n\n"
            "Pasirinkite prekę nuotraukoms:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("upload_"):
        parts = data.split("_")

        if len(parts) != 3:
            return

        location = parts[1]
        category = int(parts[2])

        if location not in LOCATIONS or category not in PRODUCTS:
            return

        context.user_data["upload_location"] = location
        context.user_data["upload_category"] = category

        await query.edit_message_text(
            f"📸 {LOCATIONS[location]}\n"
            f"Pasirinkta prekė: {PRODUCTS[category][0]}\n\n"
            "Dabar siųskite šios prekės nuotraukas.\n"
            "Galite siųsti po vieną nuotrauką.\n"
            "Kiekviena nuotrauka bus pridėta prie pasirinktos vietos atsargų."
        )
        return

    if data == "admin_back":
        await query.edit_message_text(
            "🔵🔴 PEPSI",
            reply_markup=admin_keyboard()
        )
        return

    # PREKIŲ LIKUTIS

    if data == "stock":
        await query.edit_message_text(
            "📊 PASIRINKITE VIETĄ, KURIOS LIKUTĮ NORITE MATYTI:",
            reply_markup=location_keyboard(
                "stockloc",
                "admin_back"
            )
        )
        return

    if data.startswith("stockloc_"):
        location = data.replace("stockloc_", "", 1)
        await show_location_stock(query, location)
        return

    # VIETŲ VALDYMAS

    if data == "location_management":
        await query.edit_message_text(
            "📍 VIETŲ VALDYMAS\n\n"
            "Pasirinkite vietą, kurios atsargas norite tvarkyti:",
            reply_markup=location_keyboard(
                "manageloc",
                "admin_back"
            )
        )
        return

    if data.startswith("manageloc_"):
        location = data.replace("manageloc_", "", 1)

        if location not in LOCATIONS:
            return

        stock_counts = get_stock_counts(location)

        text = (
            f"📍 {LOCATIONS[location]}\n\n"
            "Esami likučiai:\n\n"
        )

        for product_id, (name, price) in PRODUCTS.items():
            text += (
                f"{name} – "
                f"{stock_counts.get(product_id, 0)} vnt.\n"
            )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📸 ĮKELTI PREKES",
                    callback_data=f"uploadloc_{location}"
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 PERŽIŪRĖTI LIKUTĮ",
                    callback_data=f"stockloc_{location}"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ VIETOS",
                    callback_data="location_management"
                )
            ],
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard
        )
        return

    # UŽSAKYMO PATVIRTINIMAS

    if data.startswith("approve"):
        order_id = int(data.replace("approve", ""))

        with connect() as db:
            order = db.execute(
                """
                SELECT user_id, product, status, stock_id
                FROM orders
                WHERE id=?
                """,
                (order_id,)
            ).fetchone()

            if not order:
                await query.edit_message_text("Užsakymas nerastas.")
                return

            customer_id, product_id, status, stock_id = order

            if status != "LAUKIA APMOKĖJIMO":
                await query.edit_message_text(
                    f"Užsakymas jau apdorotas: {status}"
                )
                return

            if not stock_id:
                await query.edit_message_text(
                    "⚠️ Šis senas užsakymas neturi rezervuotos prekės. "
                    "Jį reikia apdoroti rankiniu būdu."
                )
                return

            photo = db.execute(
                """
                SELECT id, filename
                FROM stock
                WHERE id=?
                AND reserved_order_id=?
                """,
                (stock_id, order_id)
            ).fetchone()

            if photo:
                photo_id, filename = photo
            else:
                filename = None

        if not filename:
            await query.edit_message_text(
                "⚠️ Rezervuota prekė nerasta. "
                "Užsakymas lieka laukimo būsenoje."
            )
            return

        path = PHOTO_DIR / filename

        if not path.exists():
            await query.edit_message_text(
                "⚠️ Nuotraukos failas nerastas. "
                "Prekė lieka rezervuota, o užsakymas laukia pristatymo."
            )
            return

        name, price = PRODUCTS[product_id]

        try:
            with open(path, "rb") as photo_file:
                await context.bot.send_photo(
                    customer_id,
                    photo=photo_file,
                    caption=(
                        "✅ Jūsų užsakymas pristatytas!\n"
                        "Ačiū, kad pirkote PEPSI 🔵🔴!"
                    )
                )

        except Exception:
            await query.edit_message_text(
                "⚠️ Nepavyko išsiųsti prekės. "
                "Ji lieka rezervuota. Galite bandyti dar kartą."
            )
            return

        with connect() as db:
            db.execute(
                "DELETE FROM stock WHERE id=?",
                (photo_id,)
            )

            db.execute(
                "UPDATE orders SET status=? WHERE id=?",
                ("PRISTATYTA", order_id)
            )

        path.unlink(missing_ok=True)

        await query.edit_message_text(
            f"✅ Užsakymas #{order_id} pristatytas."
        )
        return

    # UŽSAKYMO ATMETIMAS

    if data.startswith("reject_"):
        order_id = int(data.split("_")[1])

        with connect() as db:
            order = db.execute(
                """
                SELECT user_id, status, stock_id
                FROM orders
                WHERE id=?
                """,
                (order_id,)
            ).fetchone()

            if not order:
                return

            customer_id, status, stock_id = order

            if status != "LAUKIA APMOKĖJIMO":
                await query.edit_message_text(
                    f"Užsakymas jau apdorotas: {status}"
                )
                return

            db.execute(
                "UPDATE orders SET status=? WHERE id=?",
                ("ATMESTA", order_id)
            )

            if stock_id:
                db.execute(
                    """
                    UPDATE stock
                    SET reserved_order_id=NULL
                    WHERE id=? AND reserved_order_id=?
                    """,
                    (stock_id, order_id)
                )

        await context.bot.send_message(
            customer_id,
            f"❌ Jūsų užsakymas #{order_id} atmestas. "
            "Susisiekite su administratoriumi, jei turite klausimų."
        )

        await query.edit_message_text(
            f"❌ Užsakymas #{order_id} atmestas."
        )
        return


# NUOTRAUKŲ ĮKĖLIMAS

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    category = context.user_data.get("upload_category")
    location = context.user_data.get("upload_location")

    if (
        not location
        or location not in LOCATIONS
        or not category
        or category not in PRODUCTS
    ):
        await update.message.reply_text(
            "Pirmiausia pasirinkite vietą ir prekę nuotraukoms įkelti per /admin."
        )
        return

    photo = update.message.photo[-1]
    telegram_file = await photo.get_file()

    filename = f"{photo.file_unique_id}.jpg"
    path = PHOTO_DIR / filename

    await telegram_file.download_to_drive(path)

    with connect() as db:
        db.execute(
            """
            INSERT INTO stock (category, filename, location)
            VALUES (?, ?, ?)
            """,
            (category, filename, location)
        )

    await update.message.reply_text(
        f"✅ Nuotrauka pridėta prie {PRODUCTS[category][0]} atsargų!\n"
        f"Vieta: {LOCATIONS[location]}"
    )


# KLIENTŲ ŽINUTĖS

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    if is_owner(user_id):
        return

    if not has_access(user_id):
        await message.reply_text(
            "⏳ Norėdami rašyti administratoriui arba naudotis parduotuve, "
            "pirmiausia gaukite prieigos patvirtinimą."
        )
        return

    with connect() as db:
        order = db.execute(
            "SELECT id FROM orders WHERE user_id=? "
            "ORDER BY id DESC LIMIT 1",
            (user_id,)
        ).fetchone()

    if not order:
        await message.reply_text(
            "Norėdami susisiekti su administratoriumi, "
            "pirmiausia sukurkite užsakymą."
        )
        return

    order_id = order[0]

    try:
        await context.bot.send_message(
            OWNER_ID,
            f"💬 KLIENTO ŽINUTĖ\n"
            f"Užsakymas: #{order_id}\n"
            f"Kliento ID: {user_id}\n\n"
            f"{message.text or '[Netekstinė žinutė]'}\n\n"
            f"Atsakyti: /reply {order_id} jūsų žinutė"
        )

        await message.reply_text(
            "✅ Jūsų žinutė išsiųsta administratoriui."
        )

    except Exception:
        await message.reply_text(
            "Nepavyko išsiųsti žinutės. Bandykite vėliau."
        )


# ADMINISTRATORIAUS ATSAKYMAS

async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Naudojimas: /reply UŽSAKYMO_ID jūsų žinutė"
        )
        return

    try:
        order_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "Neteisingas užsakymo numeris."
        )
        return

    text = " ".join(context.args[1:])

    with connect() as db:
        order = db.execute(
            "SELECT user_id FROM orders WHERE id=?",
            (order_id,)
        ).fetchone()

    if not order:
        await update.message.reply_text("Užsakymas nerastas.")
        return

    await context.bot.send_message(
        order[0],
        f"💬 PEPSI:\n\n{text}"
    )

    await update.message.reply_text(
        "✅ Žinutė išsiųsta klientui."
    )


# BOTO PALEIDIMAS

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN nenustatytas!")

    setup_database()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("reply", reply_command))

    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        message_handler
    ))

    port = int(os.getenv("PORT", "10000"))
    external_url = os.getenv("RENDER_EXTERNAL_URL")

    if external_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{external_url}/{BOT_TOKEN}",
            secret_token=None
        )
    else:
        app.run_polling()


if __name__ == "__main__":
    main()