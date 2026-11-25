import os
import io
import logging
import random

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from supabase import create_client

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET = "product-photos"

PRODUCTS = {
    1: ("1 💎", "35 €"),
    2: ("2 💎", "60 €"),
    3: ("5 💎", "100 €"),
}


def is_admin(user_id):
    return user_id == OWNER_ID


def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["🛍️ PREKIŲ KATALOGAS"],
            ["📦 MANO UŽSAKYMAI"]
        ],
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

    await update.message.reply_text(
        "💎 LEDAS ADMINISTRATORIUS",
        reply_markup=admin_menu()
    )


async def show_catalog(update):
    rows = supabase.table("products").select("*").order("id").execute().data

    buttons = []

    for product in rows:
        buttons.append([
            InlineKeyboardButton(
                f"{product['name']} – {product['price']}",
                callback_data=f"product_{product['id']}"
            )
        ])

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

        product = supabase.table("products").select("*").eq(
            "id", pid
        ).execute().data

        if not product:
            await query.message.reply_text("Prekė nerasta.")
            return

        p = product[0]

        await query.edit_message_text(
            f"💎 {p['name']}\n"
            f"💶 Kaina: {p['price']}\n\n"
            "Norite užsakyti šią prekę?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🛒 UŽSAKYTI",
                    callback_data=f"order_{pid}"
                )]
            ])
        )

    elif data.startswith("order_"):
        pid = int(data.split("_")[1])

        product = supabase.table("products").select("*").eq(
            "id", pid
        ).execute().data[0]

        result = supabase.table("orders").insert({
            "user_id": query.from_user.id,
            "product": pid,
            "status": "LAUKIA APMOKĖJIMO"
        }).execute()

        order_id = result.data[0]["id"]

        await query.edit_message_text(
            f"✅ Užsakymas #{order_id} pateiktas!\n\n"
            f"Prekė: {product['name']}\n"
            f"Kaina: {product['price']}\n\n"
            "🟡 Laukiama apmokėjimo.\n"
            "Susisieksime su jumis per šį botą."
        )

        await context.bot.send_message(
            OWNER_ID,
            f"🛍️ NAUJAS UŽSAKYMAS #{order_id}\n"
            f"Klientas: {query.from_user.id}\n"
            f"Prekė: {product['name']} – {product['price']}\n\n"
            f"Atsakymas klientui: /reply {order_id} Jūsų žinutė",
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

        orders = supabase.table("orders").select("*").eq(
            "id", order_id
        ).execute().data

        if not orders or orders[0]["status"] != "LAUKIA APMOKĖJIMO":
            await query.message.reply_text("Užsakymas jau apdorotas.")
            return

        order = orders[0]
        category = order["product"]

        photos = supabase.table("stock").select("*").eq(
            "category", category
        ).execute().data

        if not photos:
            supabase.table("orders").update({
                "status": "APMOKĖTA – LAUKIA PREKĖS"
            }).eq("id", order_id).execute()

            await query.message.reply_text(
                "⚠️ Apmokėjimas patvirtintas, tačiau šios kategorijos "
                "nuotraukų atsargos tuščios.\n"
                "Įkelkite nuotrauką, kad galėtumėte pristatyti užsakymą."
            )

            await context.bot.send_message(
                order["user_id"],
                "✅ Apmokėjimas patvirtintas!\n"
                "Jūsų prekė ruošiama ir bus pristatyta netrukus."
            )
            return

        photo = random.choice(photos)
        path = photo["storage_path"]

        try:
            image_data = supabase.storage.from_(BUCKET).download(path)

            await context.bot.send_photo(
                chat_id=order["user_id"],
                photo=InputFile(
                    io.BytesIO(image_data),
                    filename="ledas.jpg"
                ),
                caption="💎 Jūsų užsakymas pristatytas! Ačiū!"
            )

            # Remove delivered photo from storage and stock.
            supabase.storage.from_(BUCKET).remove([path])

            supabase.table("stock").delete().eq(
                "id", photo["id"]
            ).execute()

            supabase.table("orders").update({
                "status": "APMOKĖTA – PRISTATYTA"
            }).eq("id", order_id).execute()

            await query.message.reply_text(
                f"✅ Užsakymas #{order_id} pristatytas!"
            )

        except Exception:
            logging.exception("Delivery failed")
            await query.message.reply_text(
                "❌ Nepavyko pristatyti nuotraukos. "
                "Atsargos nepašalintos. Patikrinkite klaidą."
            )

    elif data.startswith("reject_"):
        if not is_admin(query.from_user.id):
            return

        order_id = int(data.split("_")[1])

        orders = supabase.table("orders").select("*").eq(
            "id", order_id
        ).execute().data

        if orders:
            supabase.table("orders").update({
                "status": "ATMESTAS"
            }).eq("id", order_id).execute()

            await context.bot.send_message(
                orders[0]["user_id"],
                "❌ Jūsų užsakymas atmestas."
            )

            await query.message.reply_text(
                f"Užsakymas #{order_id} atmestas."
            )


async def photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    category = context.user_data.get("upload_category")

    if not category:
        await update.message.reply_text(
            "Pirmiausia pasirinkite nuotraukų kategoriją."
        )
        return

    try:
        telegram_file = await update.message.photo[-1].get_file()
        image_data = await telegram_file.download_as_bytearray()

        path = f"{category}/{update.message.photo[-1].file_unique_id}.jpg"

        supabase.storage.from_(BUCKET).upload(
            path,
            bytes(image_data),
            file_options={
                "content-type": "image/jpeg",
                "upsert": "false"
            }
        )

        supabase.table("stock").insert({
            "category": category,
            "storage_path": path
        }).execute()

        await update.message.reply_text(
            "✅ Nuotrauka saugiai pridėta į atsargas!"
        )

    except Exception:
        logging.exception("Photo upload failed")
        await update.message.reply_text(
            "❌ Nepavyko įkelti nuotraukos. Patikrinkite atsargas ir nustatymus."
        )


async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🛍️ PREKIŲ KATALOGAS":
        await show_catalog(update)

    elif text == "📦 MANO UŽSAKYMAI":
        orders = supabase.table("orders").select("*").eq(
            "user_id", user_id
        ).order("id", desc=True).execute().data

        if not orders:
            await update.message.reply_text("Jūs dar neturite užsakymų.")
            return

        result = "📦 JŪSŲ UŽSAKYMAI:\n\n"

        for order in orders:
            name = PRODUCTS[order["product"]][0]
            result += (
                f"#{order['id']} – {name}\n"
                f"Būsena: {order['status']}\n\n"
            )

        await update.message.reply_text(result)

    elif is_admin(user_id):

        if text == "📦 UŽSAKYMAI":
            orders = supabase.table("orders").select("*").order(
                "id", desc=True
            ).execute().data

            if not orders:
                await update.message.reply_text("Užsakymų nėra.")
                return

            for order in orders:
                name = PRODUCTS[order["product"]][0]

                await update.message.reply_text(
                    f"Užsakymas #{order['id']}\n"
                    f"Klientas: {order['user_id']}\n"
                    f"Prekė: {name}\n"
                    f"Būsena: {order['status']}"
                )

        elif text == "📸 NUOTRAUKŲ LIKUTIS":
            result = "📸 NUOTRAUKŲ LIKUTIS:\n\n"

            for category, (name, price) in PRODUCTS.items():
                photos = supabase.table("stock").select(
                    "id", count="exact"
                ).eq("category", category).execute()

                result += f"{name}: {photos.count or 0} vnt.\n"

            await update.message.reply_text(result)

        elif text == "➕ ĮKELTI 1 💎":
            context.user_data["upload_category"] = 1
            await update.message.reply_text(
                "📸 Siųskite 1 💎 kategorijos nuotraukas."
            )

        elif text == "➕ ĮKELTI 2 💎":
            context.user_data["upload_category"] = 2
            await update.message.reply_text(
                "📸 Siųskite 2 💎 kategorijos nuotraukas."
            )

        elif text == "➕ ĮKELTI 5 💎":
            context.user_data["upload_category"] = 3
            await update.message.reply_text(
                "📸 Siųskite 5 💎 kategorijos nuotraukas."
            )

        elif text == "⬅️ PAGRINDINIS MENIU":
            await update.message.reply_text(
                "Pagrindinis meniu:",
                reply_markup=main_menu()
            )

    else:
        orders = supabase.table("orders").select("*").eq(
            "user_id", user_id
        ).in_(
            "status",
            ["LAUKIA APMOKĖJIMO", "APMOKĖTA – LAUKIA PREKĖS"]
        ).order("id", desc=True).execute().data

        if orders:
            order_id = orders[0]["id"]

            await context.bot.send_message(
                OWNER_ID,
                f"💬 Kliento žinutė (užsakymas #{order_id})\n"
                f"Klientas: {user_id}\n\n{text}"
            )

            await update.message.reply_text(
                "✅ Jūsų žinutė išsiųsta parduotuvei."
            )
        else:
            await update.message.reply_text(
                "Pasirinkite veiksmą iš meniu.",
                reply_markup=main_menu()
            )


async def reply_to_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    parts = update.message.text.split(maxsplit=2)

    if len(parts) < 3:
        await update.message.reply_text(
            "Naudojimas: /reply UŽSAKYMO_ID Jūsų žinutė"
        )
        return

    try:
        order_id = int(parts[1])
        message = parts[2]

        order = supabase.table("orders").select("*").eq(
            "id", order_id
        ).execute().data

        if not order:
            await update.message.reply_text("Užsakymas nerastas.")
            return

        await context.bot.send_message(
            order[0]["user_id"],
            f"💎 LEDAS parduotuvė:\n\n{message}"
        )

        await update.message.reply_text("✅ Žinutė išsiųsta klientui.")

    except Exception:
        await update.message.reply_text("❌ Nepavyko išsiųsti žinutės.")


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("reply", reply_to_customer))

    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, photo_upload))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, messages)
    )

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