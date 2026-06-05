# import os
# import httpx
# import logging
# import asyncio
# from datetime import datetime
# from fastapi import APIRouter, Request, Response, BackgroundTasks
# from app.models.request_models import ChatRequest
# from app.api.chat import chat

# router = APIRouter(prefix="", tags=["WhatsApp"])
# logger = logging.getLogger(__name__)

# # ── Configuration ─────────────────────────────────────────────────────────────
# WHATSAPP_TOKEN   = os.environ.get("WHATSAPP_TOKEN", "")
# PHONE_NUMBER_ID  = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
# VERIFY_TOKEN     = os.environ.get("WHATSAPP_VERIFY_TOKEN", "siratsync_secret")
# WHATSAPP_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
# API_VERSION      = "v19.0"

# # ── Greeting & Help Messages ───────────────────────────────────────────────────
# WELCOME_MESSAGE = """🕌 *Assalamualaikum! Welcome to Sirat Assistant*

# I'm your AI-powered Islamic companion from *SiratSync* — the all-in-one Islamic lifestyle app.

# Here's what I can help you with:
# 📖 *Quran* — Type a verse like _2:43_ or _Surah Fatiha_
# 🕌 *Salah* — Prayer times & guidance
# 📿 *Duas & Dhikr* — Daily supplications
# ⭐ *Habits* — Ibadah tracking tips
# 🧭 *Qibla* — Direction guidance
# 🌙 *Ramadan* — Fasting & Suhoor tips

# Type *help* anytime to see this menu again.

# _جزاك الله خيرا_ 🤲"""

# HELP_MESSAGE = """📋 *Sirat Assistant — Help Menu*

# *Quran Lookup:*
# • Type _2:43_ → Surah Baqarah Verse 43
# • Type _Surah Fatiha_ → Full Surah
# • Type _Surah 1_ → By number

# *Ask Anything:*
# • _How do I perform Wudu?_
# • _What is the dua before sleeping?_
# • _I'm struggling with my prayers_

# *App Features:*
# • Type _features_ → See all SiratSync features
# • Type _download_ → Get the app

# ⚠️ _This is an automated AI assistant._
# _Please do not use for personal conversations._

# _Powered by SiratSync_ 🕌"""

# UNSUPPORTED_MESSAGE = """⚠️ *Unsupported Message Type*

# I can only process *text messages* at the moment.

# Please type your question or a Quran verse like _2:43_ and I'll respond right away! 🤲"""

# ERROR_MESSAGE = """⚠️ *Something went wrong on my end.*

# Please try again in a moment.
# _JazakAllah khair for your patience._ 🤲"""


# # ── Webhook Verification (GET) ────────────────────────────────────────────────
# @router.get("/webhook/whatsapp", summary="Meta webhook verification")
# async def verify_webhook(request: Request):
#     params    = dict(request.query_params)
#     mode      = params.get("hub.mode")
#     token     = params.get("hub.verify_token")
#     challenge = params.get("hub.challenge")

#     if mode == "subscribe" and token == VERIFY_TOKEN:
#         logger.info("✅ WhatsApp webhook verified successfully")
#         return Response(content=challenge, media_type="text/plain")

#     logger.warning(f"⚠️ Webhook verification failed — token mismatch")
#     return Response(content="Forbidden", status_code=403)


# # ── Incoming Messages (POST) ──────────────────────────────────────────────────
# @router.post("/webhook/whatsapp", summary="Receive WhatsApp messages")
# async def receive_whatsapp_message(request: Request, background_tasks: BackgroundTasks):
#     body = await request.json()

#     try:
#         entry   = body["entry"][0]
#         changes = entry["changes"][0]
#         value   = changes["value"]

#         # ── Ignore status updates (sent, delivered, read) ──────────────────
#         if "messages" not in value:
#             return {"status": "ignored"}

#         msg         = value["messages"][0]
#         from_number = msg["from"]
#         msg_type    = msg.get("type")
#         msg_id      = msg.get("id", "")
#         timestamp   = msg.get("timestamp", "")

#         # ── Get contact name if available ──────────────────────────────────
#         contacts    = value.get("contacts", [])
#         user_name   = contacts[0]["profile"]["name"] if contacts else from_number

#         logger.info(f"📱 [{msg_type}] from {user_name} ({from_number}) at {_fmt_timestamp(timestamp)}")

#         # ── Mark message as read ───────────────────────────────────────────
#         background_tasks.add_task(mark_message_read, msg_id)

#         # ── Handle non-text messages ───────────────────────────────────────
#         if msg_type != "text":
#             await send_whatsapp_message(from_number, UNSUPPORTED_MESSAGE)
#             return {"status": "unsupported_type"}

#         user_text = msg["text"]["body"].strip()

#         # ── Handle special commands ────────────────────────────────────────
#         if _is_greeting(user_text):
#             await send_whatsapp_message(from_number, WELCOME_MESSAGE)
#             return {"status": "welcome_sent"}

#         if user_text.lower() in {"help", "menu", "start", "/help", "/start"}:
#             await send_whatsapp_message(from_number, HELP_MESSAGE)
#             return {"status": "help_sent"}

#         # ── Send typing indicator ──────────────────────────────────────────
#         background_tasks.add_task(send_typing_indicator, from_number)

#         # ── Process through AI chat engine ────────────────────────────────
#         chat_req = ChatRequest(
#             user_id   = from_number,
#             message   = user_text,
#             user_name = user_name,
#         )

#         chat_response = await chat(chat_req)
#         reply_text    = _format_reply(chat_response)

#         await send_whatsapp_message(from_number, reply_text)

#         logger.info(f"✅ Reply sent to {from_number} | Intent: {chat_response.intent} | Length: {len(reply_text)} chars")
#         return {"status": "sent"}

#     except (KeyError, IndexError) as e:
#         logger.warning(f"⚠️ Could not parse webhook payload: {e}")
#         return {"status": "parse_error"}

#     except Exception as e:
#         logger.error(f"❌ Unexpected error processing message: {e}", exc_info=True)
#         try:
#             await send_whatsapp_message(from_number, ERROR_MESSAGE)
#         except Exception:
#             pass
#         return {"status": "error"}


# # ── Send Text Message ─────────────────────────────────────────────────────────
# async def send_whatsapp_message(to: str, text: str, retries: int = 2) -> bool:
#     headers = {
#         "Authorization": f"Bearer {WHATSAPP_TOKEN}",
#         "Content-Type":  "application/json",
#     }
#     payload = {
#         "messaging_product": "whatsapp",
#         "recipient_type":    "individual",
#         "to":                to,
#         "type":              "text",
#         "text":              {"body": text, "preview_url": False},
#     }

#     for attempt in range(retries + 1):
#         try:
#             async with httpx.AsyncClient(timeout=10.0) as client:
#                 resp = await client.post(WHATSAPP_API_URL, json=payload, headers=headers)

#             if resp.status_code == 200:
#                 return True

#             logger.error(f"❌ WhatsApp send failed (attempt {attempt + 1}): {resp.status_code} — {resp.text}")

#             if resp.status_code in {400, 401, 403}:
#                 break  # Don't retry auth/bad request errors

#             if attempt < retries:
#                 await asyncio.sleep(1.5 * (attempt + 1))  # Exponential backoff

#         except httpx.TimeoutException:
#             logger.warning(f"⏱️ WhatsApp API timeout (attempt {attempt + 1})")
#             if attempt < retries:
#                 await asyncio.sleep(2)

#         except Exception as e:
#             logger.error(f"❌ Unexpected error sending message: {e}")
#             break

#     return False


# # ── Mark Message as Read ──────────────────────────────────────────────────────
# async def mark_message_read(message_id: str):
#     if not message_id:
#         return
#     headers = {
#         "Authorization": f"Bearer {WHATSAPP_TOKEN}",
#         "Content-Type":  "application/json",
#     }
#     payload = {
#         "messaging_product": "whatsapp",
#         "status":            "read",
#         "message_id":        message_id,
#     }
#     try:
#         async with httpx.AsyncClient(timeout=5.0) as client:
#             await client.post(WHATSAPP_API_URL, json=payload, headers=headers)
#     except Exception as e:
#         logger.debug(f"Could not mark message as read: {e}")


# # ── Typing Indicator ──────────────────────────────────────────────────────────
# async def send_typing_indicator(to: str):
#     """Simulate typing by sending a short delay — WhatsApp Cloud API doesn't
#     support native typing indicators, so we just add a brief pause."""
#     await asyncio.sleep(0.8)


# # ── Helper: Format AI Reply ───────────────────────────────────────────────────
# def _format_reply(chat_response) -> str:
#     reply = chat_response.reply or ERROR_MESSAGE

#     # Append motivational quote if present
#     if getattr(chat_response, "motivational_quote", None):
#         reply += f"\n\n✨ _{chat_response.motivational_quote}_"

#     # WhatsApp max message length is 4096 chars
#     if len(reply) > 4000:
#         reply = reply[:3997] + "..."

#     return reply


# # ── Helper: Detect Greeting ───────────────────────────────────────────────────
# def _is_greeting(text: str) -> bool:
#     greetings = {
#         "hi", "hello", "hey", "salam", "salaam",
#         "assalamualaikum", "assalamu alaikum", "السلام عليكم",
#         "start", "/start", "begin"
#     }
#     return text.lower().strip() in greetings


# # ── Helper: Format Timestamp ──────────────────────────────────────────────────
# def _fmt_timestamp(ts: str) -> str:
#     try:
#         return datetime.fromtimestamp(int(ts)).strftime("%H:%M:%S")
#     except Exception:
#         return ts

import os
import hmac
import json
import hashlib
import httpx
import logging
import asyncio
from collections import OrderedDict
from datetime import datetime
from fastapi import APIRouter, Request, Response, BackgroundTasks
from app.models.request_models import ChatRequest
from app.api.chat import chat

router = APIRouter(prefix="", tags=["WhatsApp"])
logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
VERIFY_TOKEN    = os.environ.get("WHATSAPP_VERIFY_TOKEN", "siratsync_secret")
APP_SECRET      = os.environ.get("WHATSAPP_APP_SECRET", "")
API_VERSION     = os.environ.get("WHATSAPP_API_VERSION", "v19.0")

WHATSAPP_API_URL = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}/messages"


# ── In-Memory Dedup (TTL-based, safe for single-worker deploys) ───────────────
_seen_message_ids: OrderedDict = OrderedDict()
_DEDUP_TTL        = 300   # seconds — messages older than 5 min are safe to forget
_DEDUP_MAX_SIZE   = 5000  # hard cap to prevent unbounded growth


def _is_duplicate(msg_id: str) -> bool:
    """Returns True if this message_id was already processed recently."""
    now     = asyncio.get_event_loop().time()
    cutoff  = now - _DEDUP_TTL

    # Evict expired entries (oldest first — OrderedDict preserves insertion order)
    expired_keys = [k for k, v in _seen_message_ids.items() if v < cutoff]
    for k in expired_keys:
        del _seen_message_ids[k]

    # Hard cap fallback
    if len(_seen_message_ids) >= _DEDUP_MAX_SIZE:
        _seen_message_ids.clear()
        logger.warning("⚠️ Dedup cache hit max size — cleared. Consider using Redis.")

    if msg_id in _seen_message_ids:
        return True

    _seen_message_ids[msg_id] = now
    return False


# ── Greeting & Help Messages ──────────────────────────────────────────────────
WELCOME_MESSAGE = """🕌 *Assalamualaikum! Welcome to Sirat Assistant*

I'm your AI-powered Islamic companion from *SiratSync* — the all-in-one Islamic lifestyle app.

Here's what I can help you with:
📖 *Quran* — Type a verse like _2:43_ or _Surah Fatiha_
🕌 *Salah* — Prayer times & guidance
📿 *Duas & Dhikr* — Daily supplications
⭐ *Habits* — Ibadah tracking tips
🧭 *Qibla* — Direction guidance
🌙 *Ramadan* — Fasting & Suhoor tips

Type *help* anytime to see this menu again.

_جزاك الله خيرا_ 🤲"""

HELP_MESSAGE = """📋 *Sirat Assistant — Help Menu*

*Quran Lookup:*
• Type _2:43_ → Surah Baqarah Verse 43
• Type _Surah Fatiha_ → Full Surah
• Type _Surah 1_ → By number

*Ask Anything:*
• _How do I perform Wudu?_
• _What is the dua before sleeping?_
• _I'm struggling with my prayers_

*App Features:*
• Type _features_ → See all SiratSync features
• Type _download_ → Get the app

⚠️ _This is an automated AI assistant._
_Please do not use for personal conversations._

_Powered by SiratSync_ 🕌"""

UNSUPPORTED_MESSAGE = """⚠️ *Unsupported Message Type*

I can only process *text messages* at the moment.

Please type your question or a Quran verse like _2:43_ and I'll respond right away! 🤲"""

ERROR_MESSAGE = """⚠️ *Something went wrong on my end.*

Please try again in a moment.
_JazakAllah khair for your patience._ 🤲"""


# ── Webhook Verification (GET) ────────────────────────────────────────────────
@router.get("/webhook/whatsapp", summary="Meta webhook verification")
async def verify_webhook(request: Request):
    params    = dict(request.query_params)
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified successfully")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("⚠️ Webhook verification failed — token mismatch")
    return Response(content="Forbidden", status_code=403)


# ── Incoming Messages (POST) ──────────────────────────────────────────────────
@router.post("/webhook/whatsapp", summary="Receive WhatsApp messages")
async def receive_whatsapp_message(request: Request, background_tasks: BackgroundTasks):
    body_bytes = await request.body()

    # ── HMAC Signature Verification ───────────────────────────────────────
    if APP_SECRET:
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected  = "sha256=" + hmac.new(
            APP_SECRET.encode(), body_bytes, digestmod=hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("⚠️ Webhook signature mismatch — request rejected")
            return Response(content="Forbidden", status_code=403)

    body = json.loads(body_bytes)

    # Initialise before try block so it's always in scope for error handler
    from_number: str | None = None

    try:
        entry   = body["entry"][0]
        changes = entry["changes"][0]
        value   = changes["value"]

        if "messages" not in value:
            return {"status": "ignored"}

        msg         = value["messages"][0]
        from_number = msg["from"]
        msg_type    = msg.get("type")
        msg_id      = msg.get("id", "")
        timestamp   = msg.get("timestamp", "")

        # ── Deduplication ──────────────────────────────────────────────────
        if msg_id and _is_duplicate(msg_id):
            logger.info(f"⏭️ Duplicate message {msg_id} — ignored")
            return {"status": "duplicate"}

        # ── Contact Name ───────────────────────────────────────────────────
        contacts  = value.get("contacts", [])
        user_name = contacts[0]["profile"]["name"] if contacts else from_number

        logger.info(
            f"📱 [{msg_type}] from {user_name} ({from_number}) "
            f"at {_fmt_timestamp(timestamp)}"
        )

        # ── Mark as Read (background) ──────────────────────────────────────
        if msg_id:
            background_tasks.add_task(mark_message_read, msg_id)

        # ── Non-text messages ──────────────────────────────────────────────
        if msg_type != "text":
            await send_whatsapp_message(from_number, UNSUPPORTED_MESSAGE)
            return {"status": "unsupported_type"}

        user_text = msg["text"]["body"].strip()
        if not user_text:
            return {"status": "empty_message"}

        # ── Special Commands ───────────────────────────────────────────────
        if _is_greeting(user_text):
            await send_whatsapp_message(from_number, WELCOME_MESSAGE)
            return {"status": "welcome_sent"}

        if user_text.lower() in {"help", "menu", "/help", "/menu"}:
            await send_whatsapp_message(from_number, HELP_MESSAGE)
            return {"status": "help_sent"}

        # ── Typing Indicator (background — best-effort) ────────────────────
        background_tasks.add_task(send_typing_indicator, from_number)

        # ── AI Chat Engine ─────────────────────────────────────────────────
        chat_req = ChatRequest(
            user_id   = from_number,
            message   = user_text,
            user_name = user_name,
        )

        chat_response = await chat(chat_req)
        reply_text    = _format_reply(chat_response)

        await send_whatsapp_message(from_number, reply_text)

        logger.info(
            f"✅ Reply sent to {from_number} | "
            f"Intent: {chat_response.intent} | "
            f"Length: {len(reply_text)} chars"
        )
        return {"status": "sent"}

    except (KeyError, IndexError) as e:
        logger.warning(f"⚠️ Could not parse webhook payload: {e}")
        return {"status": "parse_error"}

    except Exception as e:
        logger.error(f"❌ Unexpected error processing message: {e}", exc_info=True)
        if from_number:
            try:
                await send_whatsapp_message(from_number, ERROR_MESSAGE)
            except Exception:
                pass
        return {"status": "error"}


# ── Send Text Message ─────────────────────────────────────────────────────────
async def send_whatsapp_message(to: str, text: str, retries: int = 2) -> bool:
    """Send a WhatsApp text message with retry + exponential backoff."""
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "text",
        "text":              {"body": text, "preview_url": False},
    }

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(WHATSAPP_API_URL, json=payload, headers=headers)

            if resp.status_code == 200:
                return True

            logger.error(
                f"❌ WhatsApp send failed (attempt {attempt + 1}): "
                f"{resp.status_code} — {resp.text}"
            )

            # Don't retry on client errors (auth, bad request)
            if resp.status_code in {400, 401, 403}:
                break

            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))

        except httpx.TimeoutException:
            logger.warning(f"⏱️ WhatsApp API timeout (attempt {attempt + 1})")
            if attempt < retries:
                await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"❌ Unexpected error sending message: {e}")
            break

    return False


# ── Mark Message as Read ──────────────────────────────────────────────────────
async def mark_message_read(message_id: str) -> None:
    """Mark a received message as read (shows double blue tick on sender's end)."""
    if not message_id:
        return

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status":            "read",
        "message_id":        message_id,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(WHATSAPP_API_URL, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.debug(f"Could not mark message as read: {resp.status_code}")
    except Exception as e:
        logger.debug(f"Could not mark message as read: {e}")


# ── Typing Indicator ──────────────────────────────────────────────────────────
async def send_typing_indicator(to: str) -> None:
    """
    WhatsApp Cloud API does not natively support typing indicators.
    This adds a brief pause to simulate processing time before the reply arrives,
    making the conversation feel more natural.
    """
    await asyncio.sleep(0.8)


# ── Helper: Format AI Reply ───────────────────────────────────────────────────
def _format_reply(chat_response) -> str:
    reply = chat_response.reply or ERROR_MESSAGE

    # Append motivational quote if present
    if getattr(chat_response, "motivational_quote", None):
        reply += f"\n\n✨ _{chat_response.motivational_quote}_"

    # WhatsApp max message length is 4096 chars
    # Use word-boundary truncation to avoid splitting Unicode/Arabic mid-character
    if len(reply) > 4000:
        reply = reply[:3997].rsplit(" ", 1)[0] + "..."

    return reply


# ── Helper: Detect Greeting ───────────────────────────────────────────────────
_GREETINGS = frozenset({
    "hi", "hello", "hey",
    "salam", "salaam",
    "assalamualaikum", "assalamu alaikum",
    "السلام عليكم",
    "start", "/start", "begin",
})

def _is_greeting(text: str) -> bool:
    return text.lower().strip() in _GREETINGS


# ── Helper: Format Timestamp ──────────────────────────────────────────────────
def _fmt_timestamp(ts: str) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%H:%M:%S")
    except Exception:
        return ts