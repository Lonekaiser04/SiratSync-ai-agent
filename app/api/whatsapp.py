import os
import httpx
import logging
from fastapi import APIRouter, Request, Response
from app.models.request_models import ChatRequest
from app.api.chat import chat  # using existing chat logic

router = APIRouter()
logger = logging.getLogger(__name__)

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "siratsync_secret")

WHATSAPP_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"


# ── Webhook verification (GET) — Meta calls this once when you register ──────
@router.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified")
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


# ── Incoming messages (POST) — Meta sends every user message here ─────────────
@router.post("/webhook/whatsapp")
async def receive_whatsapp_message(request: Request):
    body = await request.json()

    try:
        entry    = body["entry"][0]
        changes  = entry["changes"][0]
        value    = changes["value"]

        # Ignore status updates (delivered, read receipts)
        if "messages" not in value:
            return {"status": "ignored"}

        msg      = value["messages"][0]
        from_number = msg["from"]           # e.g. "919876543210"
        msg_type    = msg.get("type")

        if msg_type != "text":
            await send_whatsapp_message(from_number, "Sorry, I can only understand text messages right now. 🤲")
            return {"status": "non-text ignored"}

        user_text = msg["text"]["body"]
        logger.info(f"📱 WhatsApp message from {from_number}: {user_text}")

        # ── Call your existing /chat logic ────────────────────────────────────
        chat_req = ChatRequest(
            user_id=from_number,      # use phone number as user_id
            message=user_text,
            user_name=from_number,
        )
        chat_response = await chat(chat_req)

        reply_text = chat_response.reply

        # Optionally append suggestions as a menu
        if chat_response.suggestions:
            suggestions_str = "\n".join(f"• {s}" for s in chat_response.suggestions[:4])
            reply_text += f"\n\n💡 *Quick Options:*\n{suggestions_str}"

        await send_whatsapp_message(from_number, reply_text)
        return {"status": "sent"}

    except (KeyError, IndexError) as e:
        logger.warning(f"⚠️ Could not parse webhook payload: {e}")
        return {"status": "parse_error"}


async def send_whatsapp_message(to: str, text: str):
    """Send a text message via WhatsApp Cloud API."""
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(WHATSAPP_API_URL, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.error(f"❌ WhatsApp send failed: {resp.text}")