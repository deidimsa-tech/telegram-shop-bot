import os
import sqlite3
import random
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

PRODUCTS = {
    1: ("1 💎", "35 €"),
    2: ("2 💎", "60 €"),
    3: ("5 💎", "100 €"),
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


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ PREKIŲ KATALOGAS", callback_data="catalog")],
        [InlineKeyboardButton("📦 MANO UŽSAKYMAI", callback_data="myorders")],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 UŽSAKYMAI", callback_data="admin_orders")],
        [InlineKeyboardButton("📸 ĮKELTI PREKES", callback_data="upload_menu")],
        [InlineKeyboardButton("📊 PREKIŲ LIKUTIS", callback_data="stock")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Sveiki atvykę į LEDAS 💎!\n\n"
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


async def show_catalog(query):
    buttons = []

    for product_id, (name, price) in PRODUCTS.items():
        buttons.append([
            InlineKeyboardButton(
                f"{name} – {price}",
                callback_data=f"buy_{product_id}"
            )
        ])

    await query.edit_message_text(
        "🛍️ PREKIŲ KATALOGAS\n\nPasirinkite prekę:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


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
        name, price = PRODUCTS[product]
        text += (
            f"Užsakymas #{order_id}\n"
            f"Prekė: {name} – {price}\n"
            f"Būsena: {status}\n\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard()
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "catalog":
        await show_catalog(query)
        return

    if data == "myorders":
        await show_orders(query, user_id)
        return

    if data.startswith("buy_"):
        product_id = int(data.split("_")[1])

        if product_id not in PRODUCTS:
            return

        with connect() as db:
            cursor = db.execute(
                "INSERT INTO orders (user_id, product, status) "
                "VALUES (?, ?, ?)",
                (user_id, product_id, "LAUKIA APMOKĖJIMO")
            )
            order_id = cursor.lastrowid

        name, price = PRODUCTS[product_id]

        await query.edit_message_text(
            f"✅ Užsakymas #{order_id} sukurtas!\n\n"
            f"Prekė: {name}\n"
            f"Kaina: {price}\n\n"
            "Apmokėjimą patvirtina administratorius.\n"
            "Atsiųskite mokėjimo patvirtinimą šiam botui.\n\n"
            "Jei turite klausimų, parašykite žinutę čia."
        )

        try:
            await context.bot.send_message(
                OWNER_ID,
                f"🛍️ NAUJAS UŽSAKYMAS #{order_id}\n"
                f"Kliento ID: {user_id}\n"
                f"Prekė: {name} – {price}\n"
                f"Patvirtinimui naudokite /admin."
            )
        except Exception:
            pass

        return

    if not is_owner(user_id):
        return

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
            name, price = PRODUCTS[product]

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ PATVIRTINTI",
                        callback_data=f"approve_{order_id}"
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

        await query.edit_message_text("Užsakymai išsiųsti.")
        return

    if data == "upload_menu":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 💎", callback_data="upload_1")],
            [InlineKeyboardButton("2 💎", callback_data="upload_2")],
            [InlineKeyboardButton("5 💎", callback_data="upload_3")],
        ])

        await query.edit_message_text(
            "Pasirinkite, kurios prekės nuotraukas įkelti:",
            reply_markup=keyboard
        )
        return

     if data.startswith("buy_"):
    product_id = int(data.split("_")[1])

    if product_id not in PRODUCTS:
        return

    name, price = PRODUCTS[product_id]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💵 GRYNIEJI PINIGAI",
            callback_data=f"cash_{product_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ GRĮŽTI",
            callback_data="catalog"
        )]
    ])

    await query.edit_message_text(
        f"💎 LEDAS\n\n"
        f"Pasirinkta prekė: {name}\n"
        f"Kaina: {price}\n\n"
        f"Pasirinkite mokėjimo būdą:",
        reply_markup=keyboard
    )
    return

if data.startswith("cash_"):
    product_id = int(data.split("_")[1])

    if product_id not in PRODUCTS:
        return

    name, price = PRODUCTS[product_id]

    with connect() as db:
        cursor = db.execute(
            "INSERT INTO orders (user_id, product, status) "
            "VALUES (?, ?, ?)",
            (user_id, product_id, "LAUKIA APMOKĖJIMO")
        )
        order_id = cursor.lastrowid

    await query.edit_message_text(
        f"✅ UŽSAKYMAS #{order_id}\n\n"
        f"Prekė: {name}\n"
        f"Kaina: {price}\n"
        f"Mokėjimas: 💵 Grynieji pinigai\n\n"
        f"Administratorius susisieks dėl apmokėjimo.\n"
        f"Prekė bus pristatyta patvirtinus mokėjimą."
    )

    await context.bot.send_message(
        OWNER_ID,
        f"🛍️ NAUJAS UŽSAKYMAS #{order_id}\n"
        f"Kliento ID: {user_id}\n"
        f"Prekė: {name} – {price}\n"
        f"Mokėjimas: Grynieji pinigai\n"
        f"Patvirtinimas: /admin"
    )
    return data.startswith("upload_"):
        category = int(data.split("_")[1])
        context.user_data["upload_category"] = category

        await query.edit_message_text(
            f"📸 Dabar siųskite {PRODUCTS[category][0]} nuotraukas.\n"
            "Galite siųsti po vieną nuotrauką."
        )
        return

    if data == "stock":
        with connect() as db:
            counts = db.execute(
                "SELECT category, COUNT(*) FROM stock GROUP BY category"
            ).fetchall()

        stock_counts = dict(counts)
        text = "📊 PREKIŲ LIKUTIS\n\n"

        for product_id, (name, price) in PRODUCTS.items():
            text += f"{name}: {stock_counts.get(product_id, 0)} vnt.\n"

        await query.edit_message_text(
            text,
            reply_markup=admin_keyboard()
        )
        return

    if data.startswith("approve_"):
        order_id = int(data.split("_")[1])

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
                db.execute("DELETE FROM stock WHERE id=?", (photo_id,))
                db.execute(
                    "UPDATE orders SET status=? WHERE id=?",
                    ("PRISTATYTA", order_id)
                )
            else:
                filename = None
                db.execute(
                    "UPDATE orders SET status=? WHERE id=?",
                    ("APMOKĖTA – LAUKIA PREKĖS", order_id)
                )

        if filename:
            path = PHOTO_DIR / filename

            try:
                with open(path, "rb") as photo_file:
                    await context.bot.send_photo(
                        customer_id,
                        photo=photo_file,
                        caption="✅ Jūsų užsakymas pristatytas! Ačiū, kad pirkote LEDAS 💎!"
                    )

                path.unlink(missing_ok=True)

                await query.edit_message_text(
                    f"✅ Užsakymas #{order_id} pristatytas."
                )

            except Exception:
                await query.edit_message_text(
                    "⚠️ Nepavyko išsiųsti prekės. Patikrinkite žurnalus."
                )

        else:
            await context.bot.send_message(
                customer_id,
                "✅ Mokėjimas patvirtintas!\n"
                "Prekė šiuo metu ruošiama. Netrukus ją atsiųsime."
            )

            await query.edit_message_text(
                f"⚠️ Užsakymas #{order_id} apmokėtas, bet trūksta nuotraukų."
            )

        return

    if data.startswith("reject_"):
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


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    category = context.user_data.get("upload_category")

    if not category:
        await update.message.reply_text(
            "Pirmiausia pasirinkite prekių kategoriją per /admin."
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
            "Norėdami susisiekti su administratoriumi, pirmiausia sukurkite užsakymą."
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

        await message.reply_text("✅ Jūsų žinutė išsiųsta administratoriui.")

    except Exception:
        await message.reply_text("Nepavyko išsiųsti žinutės. Bandykite vėliau.")


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
        await update.message.reply_text("Neteisingas užsakymo numeris.")
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

    await update.message.reply_text("✅ Žinutė išsiųsta klientui.")


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