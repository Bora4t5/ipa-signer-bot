import os, logging, requests, io
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
API_URL = os.environ.get('API_URL')
API_KEY = os.environ.get('API_KEY')

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

WAITING_UDID = 1
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""🚀 *IPA Signer Bot*

Send me an IPA file, then send your UDID (40 characters).

Commands: /start, /help, /cancel""", parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📖 Find UDID in iTunes/Finder or Settings → General → About\n\nFormat: `00008020-001234567890ABCD`", parse_mode='Markdown')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in user_data: del user_data[uid]
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

async def get_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    doc = update.message.document
    
    if not doc or not doc.file_name.lower().endswith('.ipa'):
        await update.message.reply_text("❌ Send an .ipa file")
        return
    
    user_data[uid] = {'ipa': doc, 'name': doc.file_name}
    await update.message.reply_text(f"✅ Received: `{doc.file_name}`\n\nNow send UDID:", parse_mode='Markdown')
    return WAITING_UDID

async def get_udid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    udid = update.message.text.strip().upper().replace('-', '').replace(' ', '')
    
    if len(udid) != 40 or not all(c in '0123456789ABCDEF' for c in udid):
        await update.message.reply_text("❌ Invalid UDID. 40 characters needed.")
        return WAITING_UDID
    
    if uid not in user_data:
        await update.message.reply_text("❌ No IPA. Send /start")
        return ConversationHandler.END
    
    msg = await update.message.reply_text("🔄 Signing...")
    
    try:
        await msg.edit_text("⬇️ Downloading...")
        ipa = user_data[uid]['ipa']
        file = await context.bot.get_file(ipa.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        buf.seek(0)
        
        await msg.edit_text("🔐 Signing... (30-60s)")
        
        files = {'ipa': (ipa.file_name, buf, 'application/octet-stream')}
        data = {'udid': udid, 'auto_register': 'true'}
        headers = {'Authorization': f'Bearer {API_KEY}', 'X-API-Key': API_KEY}
        
        r = requests.post(API_URL, files=files, data=data, headers=headers, timeout=300)
        
        if r.status_code != 200:
            err = r.json().get('message', f'HTTP {r.status_code}') if 'json' in r.headers.get('content-type', '') else r.text
            await msg.edit_text(f"❌ Failed: {err}")
            return ConversationHandler.END
        
        if 'json' in r.headers.get('content-type', ''):
            res = r.json()
            if not res.get('success', True):
                await msg.edit_text(f"❌ {res.get('message', 'Error')}")
                return ConversationHandler.END
            
            if res.get('download_url'):
                await msg.edit_text("⬇️ Fetching...")
                r = requests.get(res['download_url'], timeout=120)
                signed = r.content
            else:
                import base64
                signed = base64.b64decode(res['signed_ipa'])
            filename = res.get('filename', ipa.file_name.replace('.ipa', '_signed.ipa'))
        else:
            signed = r.content
            filename = ipa.file_name.replace('.ipa', '_signed.ipa')
        
        await msg.edit_text("📤 Uploading...")
        out = io.BytesIO(signed)
        out.name = filename
        
        await update.message.reply_document(document=out, filename=filename, 
            caption=f"✅ Signed!\n📦 {len(signed):,} bytes", parse_mode='Markdown')
        await msg.delete()
        
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")
    
    finally:
        if uid in user_data: del user_data[uid]
    
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={WAITING_UDID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_udid), MessageHandler(filters.Document.FileExtension("ipa"), get_ipa)]},
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('help', help_cmd)],
    )
    
    app.add_handler(conv)
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(MessageHandler(filters.Document.FileExtension("ipa"), get_ipa))
    
    print("🤖 Bot running...")
    app.run_polling()

if __name__ == '__main__':
    main()
