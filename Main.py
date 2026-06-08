"""
Bot de Telegram para monitorear cuentas de Instagram inhabilitadas.
"""

import logging
import asyncio
import re
from datetime import datetime, timedelta
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN      = "8671102020:AAHc6n1Jh0gul1UYT_vnX3SCk5LpePxjmc4"
CHECK_INTERVAL = 1800

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

monitored: dict = {}


def check_instagram(username):
    url = f"https://www.instagram.com/{username}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if r.status_code == 200:
            return True
        elif r.status_code == 404:
            return False
        return None
    except requests.RequestException:
        return None


def get_follower_count(username):
    url = f"https://www.instagram.com/{username}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        match = re.search(r'"edge_followed_by":\{"count":(\d+)\}', r.text)
        if match:
            n = int(match.group(1))
            if n >= 1_000_000:
                return f"{n/1_000_000:.1f}M"
            elif n >= 1_000:
                return f"{n/1_000:.1f}K"
            return str(n)
    except Exception:
        pass
    return "N/A"


async def take_screenshot(username):
    url = f"https://www.instagram.com/{username}/"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
            try:
                await page.click("svg[aria-label='Close']", timeout=3000)
            except Exception:
                pass
            screenshot = await page.screenshot(full_page=False)
            await browser.close()
            return screenshot
    except Exception as e:
        logging.error(f"Error screenshot: {e}")
        return None


def build_notification_image(screenshot, username, followers, elapsed):
    total_sec = int(elapsed.total_seconds())
    hours, remainder = divmod(total_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    time_str = f"{hours} hours, {minutes} minutes, {seconds} seconds"

    ss_img = Image.open(BytesIO(screenshot)).convert("RGBA")
    ss_w, ss_h = ss_img.size
    banner_h = 130
    canvas = Image.new("RGBA", (ss_w, banner_h + ss_h), (255, 255, 255, 255))
    canvas.paste(ss_img, (0, banner_h))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([(0, 0), (ss_w, banner_h)], fill=(15, 15, 15, 255))
    draw.rectangle([(0, 0), (ss_w, 4)], fill=(220, 50, 80, 255))

    try:
        font_big   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_med   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except Exception:
        font_big = font_med = font_small = ImageFont.load_default()

    draw.text((20, 15), f"✅  Cuenta Desbaneada  |  @{username}", font=font_big, fill=(0, 220, 100, 255))
    draw.text((20, 58), f"👥  Seguidores: {followers}", font=font_med, fill=(200, 200, 200, 255))
    draw.text((20, 92), f"⏱  Tiempo transcurrido: {time_str}", font=font_small, fill=(180, 180, 180, 255))

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👁 *Bot Monitor de Instagram*\n\n"
        "Comandos:\n"
        "• /monitor <usuario> — Empezar a monitorear\n"
        "• /list — Ver cuentas monitoreadas\n"
        "• /stop <usuario> — Dejar de monitorear",
        parse_mode="Markdown"
    )


async def cmd_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Uso: /monitor <usuario>\nEj: /monitor john_doe")
        return

    username = context.args[0].lstrip("@").lower()

    if chat_id not in monitored:
        monitored[chat_id] = {}

    if username in monitored[chat_id]:
        await update.message.reply_text(f"⚠️ Ya estás monitoreando a @{username}.")
        return

    estado = check_instagram(username)
    monitored[chat_id][username] = {"estado": estado, "inicio": datetime.now()}

    if estado is True:
        await update.message.reply_text(f"✅ @{username} ya está *activa* ahora mismo.", parse_mode="Markdown")
    elif estado is False:
        await update.message.reply_text(
            f"👁 Monitoreando *@{username}*\nCuenta inhabilitada. Te aviso cuando vuelva ⏱",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"👁 Monitoreando *@{username}*\nNo se pudo verificar ahora, seguiré revisando.",
            parse_mode="Markdown"
        )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cuentas = monitored.get(chat_id, {})

    if not cuentas:
        await update.message.reply_text("No estás monitoreando ninguna cuenta.")
        return

    lineas = ["📋 *Cuentas monitoreadas:*\n"]
    for user, data in cuentas.items():
        estado = data["estado"]
        elapsed = datetime.now() - data["inicio"]
        h, rem = divmod(int(elapsed.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        icono = "🟢 Activa" if estado is True else ("🔴 Inhabilitada" if estado is False else "🟡 Desconocido")
        lineas.append(f"• @{user} — {icono} | hace {h}h {m}m {s}s")

    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Uso: /stop <usuario>")
        return

    username = context.args[0].lstrip("@").lower()

    if chat_id in monitored and username in monitored[chat_id]:
        del monitored[chat_id][username]
        await update.message.reply_text(f"🛑 Dejé de monitorear a @{username}.")
    else:
        await update.message.reply_text(f"No estaba monitoreando a @{username}.")


async def monitor_loop(app: Application):
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        for chat_id, cuentas in list(monitored.items()):
            for username, data in list(cuentas.items()):
                estado_anterior = data["estado"]
                nuevo_estado = check_instagram(username)

                if estado_anterior is False and nuevo_estado is True:
                    elapsed = datetime.now() - data["inicio"]
                    followers = get_follower_count(username)
                    screenshot = await take_screenshot(username)
                    try:
                        if screenshot:
                            img = build_notification_image(screenshot, username, followers, elapsed)
                            await app.bot.send_photo(
                                chat_id=chat_id,
                                photo=img,
                                caption=f"✅ *¡@{username} fue desbaneada!*\nhttps://www.instagram.com/{username}/",
                                parse_mode="Markdown"
                            )
                        else:
                            h, rem = divmod(int(elapsed.total_seconds()), 3600)
                            m, s = divmod(rem, 60)
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    f"✅ *¡@{username} fue desbaneada!*\n"
                                    f"👥 Seguidores: {followers}\n"
                                    f"⏱ Tiempo: {h}h {m}m {s}s\n"
                                    f"🔗 https://www.instagram.com/{username}/"
                                ),
                                parse_mode="Markdown"
                            )
                    except Exception as e:
                        logging.error(f"Error notificando: {e}")

                if nuevo_estado is not None:
                    monitored[chat_id][username]["estado"] = nuevo_estado


async def post_init(app: Application):
    asyncio.create_task(monitor_loop(app))


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("monitor", cmd_monitor))
    app.add_handler(CommandHandler("list",    cmd_list))
    app.add_handler(CommandHandler("stop",    cmd_stop))
    print("🤖 Bot iniciado.")
    app.run_polling()


if __name__ == "__main__":
    main()
