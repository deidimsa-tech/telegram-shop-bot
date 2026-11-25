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

DB = DATA_DIR / "ledas.db"


# PRODUCT IDs
# Original diamond IDs 1, 2, 3 are preserved.

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


def connect():
    return sqlite3.connect(DB)


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


def is_owner(user_id):
    return user_id == OWNER_ID


def get_stock_counts():
    with connect() as db:
        counts = db.execute(
            "SELECT category, COUNT() FROM stock GROUP BY category"
        ).fetchall()

    return dict(counts)


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
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💎 LEDAS\n\n"
        "Sveiki atvykę į LEDAS!\n\n"
        "✨ Išskirtinės prekės.\n"
        "💎 Greitas pristatymas.\n\n"
        "Pasirinkite, ką norite daryti:",
        reply_markup=main_keyboard()
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return

    await update.message.reply_text(
        "👑 LEDAS ADMIN PANELĖ",
        reply_markup=admin_keyboard()
    )


# CUSTOMER CATALOGUE

async def show_catalog(query):
    keyboard = [
        [InlineKeyboardButton("💎", callback_data="cat_diamond")],
        [InlineKeyboardButton("❄️", callback_data="cat_snow")],
        [InlineKeyboardButton("🌲", callback_data="cat_tree")],
        [InlineKeyboardButton("⬅️ GRĮŽTI", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        "💎 LEDAS | PREKIŲ KATALOGAS\n\n"
        "Pasirinkite kategoriją:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_category(query, category_key):
    if category_key not in CATEGORIES:
        return

    emoji, product_ids = CATEGORIES[category_key]
    stock_counts = get_stock_counts()

    buttons = []

    for product_id in product_ids:
        name, price = PRODUCTS[product_id]

        if stock_counts.get(product_id, 0) > 0:
            label = f"✅ {name} – {price}"
            callback = f"buy_{product_id}"
        else:
            label = f"❌ {name} – {price}"
            callback = f"unavailable_{product_id}"

        buttons.append([
            InlineKeyboardButton(label, callback_data=callback)
        ])

    buttons.append([
        InlineKeyboardButton("⬅️ KATEGORIJOS", callback_data="catalog")
    ])

    await query.edit_message_text(
        f"{emoji} LEDAS | KATALOGAS\n\n"
        "Pasirinkite norimą prekę:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# CUSTOMER ORDERS

async def show_orders(query, user_id):
    with connect() as db:
        orders = db.execute(
            "SELECT id, product, status FROM orders "
            "WHERE user_id=? ORDER BY id DESC",
            (user_id,)
        ).fetchall()

    if not orders:
        await query.edit_message_text(
            "📦 Jūs dar neturite užsakymų.",
            reply_markup=main_keyboard()
        )
        return

    text = "📦 MANO UŽSAKYMAI\n\n"

    for order_id, product, status in orders:
        name, price = PRODUCTS.get(
            product, ("Nežinoma prekė", "")
        )

        text += (
            f"Užsakymas #{order_id}\n"
            f"Prekė: {name} – {price}\n"
            f"Būsena: {status}\n\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard()
    )


# CALLBACK HANDLER

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # MAIN MENU

    if data == "main_menu":
        await query.edit_message_text(
            "💎 LEDAS\n\nPasirinkite, ką norite daryti:",
            reply_markup=main_keyboard()
        )
        return

    # CATALOGUE

    if data == "catalog":
        await show_catalog(query)
        return

    if data.startswith("cat_"):
        category_key = data.replace("cat_", "", 1)
        await show_category(query, category_key)
        return

    if data == "myorders":
        await show_orders(query, user_id)
        return

    # UNAVAILABLE PRODUCT

    if data.startswith("unavailable_"):
        await query.answer(
            "❌ Šiuo metu šios prekės nėra.",
            show_alert=True
        )
        return

    # PRODUCT SELECTION

    if data.startswith("buy_"):
        product_id = int(data.split("_")[1])

        if product_id not in PRODUCTS:
            return

        # Check stock again before allowing an order.
        with connect() as db:
            available = db.execute(
                "SELECT COUNT() FROM stock WHERE category=?",
                (product_id,)
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
                callback_data=f"cash_{product_id}"
            )],
            [InlineKeyboardButton(
                "⬅️ GRĮŽTI",
                callback_data=f"back_{product_id}"
            )]
        ])

        await query.edit_message_text(
            "💎 LEDAS\n\n"
            f"Pasirinkta prekė: {name}\n"
            f"Kaina: {price}\n\n"
            "Pasirinkite mokėjimo būdą:",
            reply_markup=keyboard
        )
        return

    # BACK TO PRODUCT CATEGORY

    if data.startswith("back_"):
        product_id = int(data.split("")[1])

        category_key = next(
            (
                key for key, (, ids) in CATEGORIES.items()
                if product_id in ids
            ),
            None
        )

        if category_key:
            await show_category(query, category_key)
        return

    # CASH PAYMENT

    if data.startswith("cash_"):
        product_id = int(data.split("")[1])

        if product_id not in PRODUCTS:
            return

        name, price = PRODUCTS[product_id]

        # Check that stock is still available.
        with connect() as db:
            available = db.execute(
                "SELECT COUNT(*) FROM stock WHERE category=?",
                (product_id,)
            ).fetchone()[0]

            if available <= 0:
                await query.edit_message_text(
                    "❌ Šios prekės šiuo metu nebėra.",
                    reply_markup=main_keyboard()
                )
                return

            cursor = db.execute(
                "INSERT INTO orders (user_id, product, status) "
                "VALUES (?, ?, ?)",
                (user_id, product_id, "LAUKIA APMOKĖJIMO")
            )

            order_id = cursor.lastrowid

        await query.edit_message_text(
            f"💎 LEDAS\n\n"
            f"✅ UŽSAKYMAS #{order_id}\n\n"
            f"Prekė: {name}\n"
            f"Kaina: {price}\n"
            f"Mokėjimas: 💵 Grynieji pinigai\n\n"
            "Administratorius susisieks dėl apmokėjimo.\n"
            "Prekė bus pristatyta patvirtinus mokėjimą."
        )

        try:
            await context.bot.send_message(
                OWNER_ID,
                f"🛍️ NAUJAS UŽSAKYMAS #{order_id}\n"
                f"Kliento ID: {user_id}\n"
                f"Prekė: {name} – {price}\n"
                f"Mokėjimas: Grynieji pinigai\n"
                f"Patvirtinimas: /admin"
            )
        except Exception:
            pass

        return

    # ADMIN ONLY ACTIONS

    if not is_owner(user_id):
        return

    # ADMIN ORDERS

    if data == "admin_orders":
        with connect() as db:
            orders = db.execute(
                "SELECT id, user_id, product, status "
                "FROM orders ORDER BY id DESC LIMIT 20"
            ).fetchall()

        if not orders:
            await query.edit_message_text(
                "Užsakymų nėra.",
                reply_markup=admin_keyboard()
            )
            return

        for order_id, customer_id, product, status in orders:
            name, price = PRODUCTS.get(
                product, ("Nežinoma prekė", "")
            )

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
                f"Būsena: {status}",
                reply_markup=keyboard
            )

        await query.edit_message_text(
            "Užsakymai išsiųsti.",
            reply_markup=admin_keyboard()
        )
        return

    # PHOTO UPLOAD MENU

    if data == "upload_menu":
        keyboard = [
            [InlineKeyboardButton("💎", callback_data="uploadcat_diamond")],
            [InlineKeyboardButton("❄️", callback_data="uploadcat_snow")],
            [InlineKeyboardButton("🌲", callback_data="uploadcat_tree")],
            [InlineKeyboardButton("⬅️ GRĮŽTI", callback_data="admin_back")],
        ]

        await query.edit_message_text(
            "📸 PASIRINKITE KATEGORIJĄ:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # PHOTO UPLOAD PRODUCT SELECTION

    if data.startswith("uploadcat_"):
        category_key = data.replace("uploadcat_", "", 1)

        if category_key not in CATEGORIES:
            return

        emoji, product_ids = CATEGORIES[category_key]
        stock_counts = get_stock_counts()

        buttons = []

        for product_id in product_ids:
            name, price = PRODUCTS[product_id]
            count = stock_counts.get(product_id, 0)

            buttons.append([
                InlineKeyboardButton(
                    f"{name} – {price} ({count} vnt.)",
                    callback_data=f"upload_{product_id}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "⬅️ KATEGORIJOS",
                callback_data="upload_menu"
            )
        ])

        await query.edit_message_text(
            f"📸 {emoji} PASIRINKITE PREKĘ NUOTRAUKOMS:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("upload_"):
        category = int(data.split("")[1])

        if category not in PRODUCTS:
            return

        context.user_data["upload_category"] = category

        await query.edit_message_text(
            f"📸 Dabar siųskite {PRODUCTS[category][0]} nuotraukas.\n\n"
            "Galite siųsti po vieną nuotrauką.\n"
            "Kiekviena nuotrauka bus pridėta prie šios prekės atsargų."
        )
        return

    if data == "admin_back":
        await query.edit_message_text(
            "👑 LEDAS ADMIN PANELĖ",
            reply_markup=admin_keyboard()
        )
        return

    # STOCK

    if data == "stock":
        stock_counts = get_stock_counts()

        text = "📊 PREKIŲ LIKUTIS\n\n"

        for product_id, (name, price) in PRODUCTS.items():
            count = stock_counts.get(product_id, 0)
            emoji = "✅" if count > 0 else "❌"

            text += f"{emoji} {name} – {count} vnt.\n"

        await query.edit_message_text(
            text,
            reply_markup=admin_keyboard()
        )
        return

    # APPROVE ORDER

    if data.startswith("approve"):
        order_id = int(data.split("")[1])

        with connect() as db:
            order = db.execute(
                "SELECT user_id, product, status FROM orders WHERE id=?",
                (order_id,)
            ).fetchone()

            if not order:
                await query.edit_message_text("Užsakymas nerastas.")
                return

            customer_id, product_id, status = order

            if status != "LAUKIA APMOKĖJIMO":
                await query.edit_message_text(
                    f"Užsakymas jau apdorotas: {status}"
                )
                return

            photo = db.execute(
                "SELECT id, filename FROM stock "
                "WHERE category=? ORDER BY RANDOM() LIMIT 1",
                (product_id,)
            ).fetchone()

            if photo:
                photo_id, filename = photo
            else:
                filename = None

        # NO STOCK AVAILABLE

        if not filename:
            with connect() as db:
                db.execute(
                    "UPDATE orders SET status=? WHERE id=?",
                    ("APMOKĖTA – LAUKIA PREKĖS", order_id)
                )

            await context.bot.send_message(
                customer_id,
                "✅ Mokėjimas patvirtintas!\n"
                "Prekė šiuo metu ruošiama. Netrukus ją atsiųsime."
            )

            await query.edit_message_text(
                f"⚠️ Užsakymas #{order_id} apmokėtas, "
                "bet trūksta nuotraukų."
            )
            return

        path = PHOTO_DIR / filename

        # FILE MISSING

        if not path.exists():
            with connect() as db:
                db.execute(
                    "UPDATE orders SET status=? WHERE id=?",
                    ("APMOKĖTA – LAUKIA PRISTATYMO", order_id)
                )

            await query.edit_message_text(
                "⚠️ Nuotraukos failas nerastas. "
                "Užsakymas pažymėtas kaip apmokėtas, "
                "bet laukia pristatymo."
            )
            return

        # SEND PHOTO FIRST.
        # Stock is only removed after successful delivery.

        try:
            with open(path, "rb") as photo_file:
                await context.bot.send_photo(
                    customer_id,
                    photo=photo_file,
                    caption=(
                        "✅ Jūsų užsakymas pristatytas!\n"
                        "Ačiū, kad pirkote LEDAS 💎!"
                    )
                )

        except Exception:
            with connect() as db:
                db.execute(
                    "UPDATE orders SET status=? WHERE id=?",
                    ("APMOKĖTA – LAUKIA PRISTATYMO", order_id)
                )

            await query.edit_message_text(
                "⚠️ Nepavyko išsiųsti prekės. "
                "Užsakymas pažymėtas kaip apmokėtas, "
                "bet laukia pristatymo. Patikrinkite rankiniu būdu."
            )
            return

        # DELIVERY SUCCESSFUL: remove stock record and file.

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

    # REJECT ORDER

    if data.startswith("reject"):
        order_id = int(data.split("_")[1])

        with connect() as db:
            order = db.execute(
                "SELECT user_id, status FROM orders WHERE id=?",
                (order_id,)
            ).fetchone()

            if not order:
                return

            customer_id, status = order

            if status != "LAUKIA APMOKĖJIMO":
                await query.edit_message_text(
                    f"Užsakymas jau apdorotas: {status}"
                )
                return

            db.execute(
                "UPDATE orders SET status=? WHERE id=?",
                ("ATMESTA", order_id)
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


# PHOTO UPLOAD

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    category = context.user_data.get("upload_category")

    if not category or category not in PRODUCTS:
        await update.message.reply_text(
            "Pirmiausia pasirinkite prekę nuotraukoms įkelti per /admin."
        )
        return

    photo = update.message.photo[-1]
    telegram_file = await photo.get_file()

    filename = f"{photo.file_unique_id}.jpg"
    path = PHOTO_DIR / filename

    await telegram_file.download_to_drive(path)

    with connect() as db:
        db.execute(
            "INSERT INTO stock (category, filename) VALUES (?, ?)",
            (category, filename)
        )

    await update.message.reply_text(
        f"✅ Nuotrauka pridėta prie {PRODUCTS[category][0]} atsargų!"
    )


# CUSTOMER MESSAGES

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    if is_owner(user_id):
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


# ADMIN REPLY

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
        f"💬 LEDAS ADMINISTRATORIUS:\n\n{text}"
    )

    await update.message.reply_text(
        "✅ Žinutė išsiųsta klientui."
    )


# START BOT

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


if name == "__main