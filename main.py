import os
import sqlite3
import random
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "6957346235"))

logging.basicConfig(level=logging.INFO)

db = sqlite3.connect("shop.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS products
              (id INTEGER PRIMARY KEY, name TEXT, price TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS stock
              (id INTEGER PRIMARY KEY AUTOINCREMENT, category INTEGER, file_id TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS orders
              (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
               product INTEGER, status TEXT)""")
db.commit()

DEFAULT_PRODUCTS = [
    (1, "1 💎", "35 €"),
    (2, "2 💎", "60 €"),
    (3, "5 💎", "100 €"),
]

for product in DEFAULT_PRODUCTS:
    db.execute("INSERT OR IGNORE INTO products VALUES (?, ?, ?)", product)
db.commit()

def is_admin(user_id):
    return user_id == OWNER_ID

def main_menu():
    return ReplyKeyboardMarkup(
        [["🛍️ PREKIŲ KATALOGAS"], ["📦 MANO UŽSAKYMAI"]],
        resize_keyboard=True
    )

def admin_menu():
    return ReplyKeyboardMarkup(
        [
            ["📦 UŽSAKYMAI", "📸 NUOTRAUKŲ LIKUTIS"],
            ["➕ ĮKELTI 1 💎", "➕ ĮKELTI 2 💎"],
            ["➕ ĮKELTI 5 💎", "⬅️ PAGRINDINIS MENIU"]
        ],
        resize_keyboard=True
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Sveiki atvykę į LEDAS 💎 parduotuvę!",
        reply_markup=main_menu()
    )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("Administratoriaus meniu:", reply_markup=admin_menu())

async def show_catalog(update, context):
    rows = db.execute("SELECT * FROM products ORDER BY id").fetchall()
    buttons = [
        [InlineKeyboardButton(f"{name} – {price}", callback_data=f"product_{pid}")]
        for pid, name, price in rows
    ]
    await update.message.reply_text(
        "🛍️ PREKIŲ KATALOGAS\n\nPasirinkite prekę:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("product_"):
        pid = int(data.split("_")[1])
        product = db.execute(
            "SELECT * FROM products WHERE id=?", (pid,)
        ).fetchone()

        if not product:
            await query.edit_message_text("Prekė nerasta.")
            return

        await query.edit_message_text(
            f"💎 {product[1]}\n💶 Kaina: {product[2]}\n\n"
            "Norite užsakyti šią prekę?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 UŽSAKYTI", callback_data=f"order_{pid}")]
            ])
        )

    elif data.startswith("order_"):
        pid = int(data.split("_")[1])
        cursor = db.execute(
            "INSERT INTO orders (user_id, product, status) VALUES (?, ?, ?)",
            (query.from_user.id, pid, "LAUKIA APMOKĖJIMO")
        )
        db.commit()
        order_id = cursor.lastrowid

        product = db.execute(
            "SELECT name, price FROM products WHERE id=?", (pid,)
        ).fetchone()

        await query.edit_message_text(
            f"✅ Užsakymas #{order_id} pateiktas!\n"
            f"Prekė: {product[0]}\nKaina: {product[1]}\n\n"
            "🟡 Laukiama apmokėjimo. Susisieksime su jumis per šį botą."
        )

        await context.bot.send_message(
            OWNER_ID,
            f"🛍️ NAUJAS UŽSAKYMAS #{order_id}\n"
            f"Klientas: {query.from_user.id}\n"
            f"Prekė: {product[0]} – {product[1]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ PATVIRTINTI APMOKĖJIMĄ",
                    callback_data=f"approve_{order_id}"
                )],
                [InlineKeyboardButton(
                    "❌ ATMESTI UŽSAKYMĄ",
                    callback_data=f"reject_{order_id}"
                )]
            ])
        )

    elif data.startswith("approve_"):
        if not is_admin(query.from_user.id):
            return

        order_id = int(data.split("_")[1])
        order = db.execute(
            "SELECT user_id, product, status FROM orders WHERE id=?",
            (order_id,)
        ).fetchone()

        if not order or order[2] != "LAUKIA APMOKĖJIMO":
            await query.message.reply_text("Šis užsakymas jau apdorotas.")
            return

        user_id, product_id, _ = order
        photo = db.execute(
            "SELECT id, file_id FROM stock WHERE category=? ORDER BY RANDOM() LIMIT 1",
            (product_id,)
        ).fetchone()

        if not photo:
            db.execute(
                "UPDATE orders SET status='APMOKĖTA – LAUKIA PREKĖS' WHERE id=?",
                (order_id,)
            )
            db.commit()
            await query.message.reply_text(
                f"⚠️ Užsakymas #{order_id}: apmokėjimas patvirtintas, "
                "bet šios kategorijos nuotraukų atsargos tuščios. "
                "Įkelkite nuotrauką ir pristatykite prekę."
            )
            await context.bot.send_message(
                user_id,
                "✅ Apmokėjimas patvirtintas! Jūsų prekė ruošiama. "
                "Netrukus ją gausite."
            )
            return

        try:
            await context.bot.send_photo(user_id, photo[1],
                                         caption="💎 Jūsų užsakymas pristatytas! Ačiū!")
        except Exception:
            await query.message.reply_text(
                "Nepavyko išsiųsti nuotraukos. Užsakymas liko neapdorotas."
            )
            return

        db.execute("DELETE FROM stock WHERE id=?", (photo[0],))
        db.execute("UPDATE orders SET status='APMOKĖTA – PRISTATYTA' WHERE id=?",
                   (order_id,))
        db.commit()
        await query.message.reply_text(
            f"✅ Užsakymas #{order_id} apmokėtas ir pristatytas!"
        )

    elif data.startswith("reject_"):
        if not is_admin(query.from_user.id):
            return
        order_id = int(data.split("_")[1])
        order = db.execute(
            "SELECT user_id FROM orders WHERE id=?", (order_id,)
        ).fetchone()
        if order:
            db.execute("UPDATE orders SET status='ATMESTAS' WHERE id=?", (order_id,))
            db.commit()
            await context.bot.send_message(order[0], "❌ Jūsų užsakymas atmestas.")
            await query.message.reply_text(f"Užsakymas #{order_id} atmestas.")

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🛍️ PREKIŲ KATALOGAS":
        await show_catalog(update, context)

    elif text == "📦 MANO UŽSAKYMAI":
        orders = db.execute(
            "SELECT id, product, status FROM orders WHERE user_id=? ORDER BY id DESC",
            (user_id,)
        ).fetchall()
        if not orders:
            await update.message.reply_text("Jūs dar neturite užsakymų.")
            return
        result = "📦 JŪSŲ UŽSAKYMAI:\n\n"
        for oid, pid, status in orders:
            product = db.execute(
                "SELECT name FROM products WHERE id=?", (pid,)
            ).fetchone()
            result += f"#{oid} – {product[0]} – {status}\n"
        await update.message.reply_text(result)

    elif is_admin(user_id):
        if text == "📦 UŽSAKYMAI":
            orders = db.execute(
                "SELECT id, user_id, product, status FROM orders ORDER BY id DESC"
            ).fetchall()
            if not orders:
                await update.message.reply_text("Užsakymų nėra.")
                return
            for oid, uid, pid, status in orders:
                product = db.execute(
                    "SELECT name FROM products WHERE id=?", (pid,)
                ).fetchone()
                await update.message.reply_text(
                    f"Užsakymas #{oid}\nKlientas: {uid}\n"
                    f"Prekė: {product[0]}\nBūsena: {status}"
                )

        elif text == "📸 NUOTRAUKŲ LIKUTIS":
            counts = db.execute(
                "SELECT category, COUNT(*) FROM stock GROUP BY category"
            ).fetchall()
            result = "📸 NUOTRAUKŲ LIKUTIS:\n"
            for pid, name, price in DEFAULT_PRODUCTS:
                count = next((n for cat, n in counts if cat == pid), 0)
                result += f"{name}: {count} vnt.\n"
            await update.message.reply_text(result)

        elif text in ["➕ ĮKELTI 1 💎", "➕ ĮKELTI 2 💎", "➕ ĮKELTI 5 💎"]:
            category = {"➕ ĮKELTI 1 💎": 1,
                        "➕ ĮKELTI 2 💎": 2,
                        "➕ ĮKELTI 5 💎": 3}[text]
            context.user_data["upload_category"] = category
            await update.message.reply_text(
                "📸 Dabar siųskite nuotraukas. Kiekviena nuotrauka bus pridėta į atsargas."
            )

        elif text == "⬅️ PAGRINDINIS MENIU":
            await update.message.reply_text("Pagrindinis meniu:", reply_markup=main_menu())

    elif "upload_category" in context.user_data:
        await update.message.reply_text("Prašome įkelti nuotrauką.")

    else:
        # Customer messages are relayed to the shop owner.
        latest = db.execute(
            """SELECT id FROM orders WHERE user_id=?
               AND status IN ('LAUKIA APMOKĖJIMO', 'APMOKĖTA – LAUKIA PREKĖS')
               ORDER BY id DESC LIMIT 1""", (user_id,)
        ).fetchone()
        if latest:
            await context.bot.send_message(
                OWNER_ID, f"💬 Kliento žinutė (užsakymas #{latest[0]}):\n{text}"
            )
            await update.message.reply_text("✅ Jūsų žinutė išsiųsta parduotuvei.")
        else:
            await update.message.reply_text(
                "Pasirinkite veiksmą iš meniu.", reply_markup=main_menu()
            )

async def photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    category = context.user_data.get("upload_category")
    if not category:
        await update.message.reply_text("Pirmiausia pasirinkite nuotraukų kategoriją.")
        return

    file_id = update.message.photo[-1].file_id
    db.execute("INSERT INTO stock (category, file_id) VALUES (?, ?)",
               (category, file_id))
    db.commit()
    await update.message.reply_text("✅ Nuotrauka pridėta į atsargas!")

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN aplinkos kintamasis nenustatytas.")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, photo_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))

    port = int(os.environ.get("PORT", "10000"))
    url = os.environ.get("RENDER_EXTERNAL_URL")

    if url:
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="telegram",
            webhook_url=f"{url}/telegram"
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    main()