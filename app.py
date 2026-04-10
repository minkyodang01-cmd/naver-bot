from flask import Flask, request
import csv
import requests
import os
import time
import jwt
from threading import Lock
from difflib import get_close_matches

app = Flask(__name__)

BOT_ID = os.environ["BOT_ID"]

CATEGORY_LIST = ["HKMC", "GM", "RENAULT", "APTIV", "UL"]

data = []
FAQ = {}
product_data = []
oem_data = []

token_lock = Lock()
cached_token = None
cached_token_expire_at = 0

session = requests.Session()

def normalize_text(text):
    return str(text or "").strip().upper().replace(" ", "")

def safe_str(v):
    return str(v or "").strip()

def is_valid_uri(uri):
    uri = safe_str(uri)
    return uri.startswith("http")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# =====================
# DATA (스펙)
# =====================
with open(os.path.join(BASE_DIR, "data.csv"), newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if safe_str(row.get("사용여부")).upper() == "Y":
            data.append(row)

# =====================
# FAQ
# =====================
with open(os.path.join(BASE_DIR, "faq.csv"), newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if safe_str(row.get("사용여부")).upper() == "Y":
            FAQ[row["질문"]] = row["답변"]

FAQ_NORMALIZED = {normalize_text(k): v for k, v in FAQ.items()}

# =====================
# PRODUCT / OEM
# =====================
with open(os.path.join(BASE_DIR, "PRODUCT.csv"), newline="", encoding="utf-8-sig") as f:
    product_data = list(csv.DictReader(f))

with open(os.path.join(BASE_DIR, "OEM.csv"), newline="", encoding="utf-8-sig") as f:
    oem_data = list(csv.DictReader(f))

# =====================
# TOKEN
# =====================
def get_token():
    global cached_token, cached_token_expire_at
    now = int(time.time())

    if cached_token and now < cached_token_expire_at:
        return cached_token

    payload = {
        "iss": os.environ["CLIENT_ID"],
        "sub": os.environ["CLIENT_EMAIL"],
        "iat": now,
        "exp": now + 3600
    }

    private_key = os.environ["PRIVATE_KEY"].replace("\\n", "\n")
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

    r = session.post(
        "https://auth.worksmobile.com/oauth2/v2.0/token",
        data={
            "assertion": jwt_token,
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "client_id": os.environ["CLIENT_ID"],
            "client_secret": os.environ["CLIENT_SECRET"],
            "scope": "bot.message"
        }
    )

    token = r.json()["access_token"]
    cached_token = token
    cached_token_expire_at = now + 3000
    return token

def send(user_id, body):
    token = get_token()
    session.post(
        f"https://www.worksapis.com/v1.0/bots/{BOT_ID}/users/{user_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json=body
    )

def send_text(user_id, text):
    send(user_id, {"content": {"type": "text", "text": text}})

# =====================
# 스펙 메뉴 (복구)
# =====================
def send_category_menu(user_id):
    send(user_id, {
        "content": {
            "type": "button_template",
            "contentText": "스펙 선택",
            "actions": [
                {"type": "message", "label": c, "text": c}
                for c in CATEGORY_LIST
            ]
        }
    })

# =====================
# 스펙 출력 (간단 복구)
# =====================
def send_spec(user_id, category):
    rows = [r for r in data if r.get("구분") == category]
    if not rows:
        send_text(user_id, "데이터 없음")
        return

    text = "\n".join([r.get("스펙코드", "-") for r in rows[:10]])
    send_text(user_id, text)

# =====================
# PRODUCT FLEX
# =====================
def send_product(user_id, row):
    name = safe_str(row.get("제품명"))
    desc = safe_str(row.get("설명"))
    img = safe_str(row.get("이미지"))

    bubble = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [{"type": "text", "text": name}]
        }
    }

    if desc:
        bubble["body"]["contents"].append({"type": "text", "text": desc})

    if is_valid_uri(img):
        bubble["hero"] = {"type": "image", "url": img}

    send(user_id, {
        "content": {"type": "flex", "altText": name, "contents": bubble}
    })

# =====================
# OEM
# =====================
def send_oem(user_id):
    bubbles = []
    for r in oem_data:
        bubbles.append({
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [{"type": "text", "text": r.get("OEM", "-")}]
            }
        })

    send(user_id, {
        "content": {
            "type": "flex",
            "altText": "OEM",
            "contents": {"type": "carousel", "contents": bubbles[:10]}
        }
    })

# =====================
# MAIN
# =====================
def handle_message(user_id, msg):
    norm = normalize_text(msg)

    if norm in FAQ_NORMALIZED:
        send_text(user_id, FAQ_NORMALIZED[norm])
        return

    # PRODUCT 직접
    for r in product_data:
        if normalize_text(r.get("제품명")) == norm:
            send_product(user_id, r)
            return

    if norm == "OEM":
        send_oem(user_id)
        return

    if norm in ["스펙", "SPEC"]:
        send_category_menu(user_id)
        return

    if norm in CATEGORY_LIST:
        send_spec(user_id, norm)
        return

    send_text(user_id, "원하시는 기능을 찾지 못했습니다.")

@app.route("/", methods=["POST"])
def bot():
    req = request.get_json()
    handle_message(req["source"]["userId"], req["content"]["text"])
    return "ok"

@app.route("/health")
def health():
    return "ok"
