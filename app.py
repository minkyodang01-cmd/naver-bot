from flask import Flask, request
import csv
import requests
import os
import time
import jwt

app = Flask(__name__)

BOT_ID = os.environ.get("BOT_ID")

# -----------------
# 유틸
# -----------------
def normalize_text(text):
    return str(text or "").strip().upper().replace(" ", "")

def safe_str(v):
    return str(v or "").strip()

def is_valid_uri(uri):
    return safe_str(uri).startswith("http")

# -----------------
# 데이터 로드 (절대 안죽게)
# -----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_csv(name):
    try:
        with open(os.path.join(BASE_DIR, name), newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print("CSV LOAD ERROR:", name, e)
        return []

data = load_csv("data.csv")
faq_raw = load_csv("faq.csv")
product_data = load_csv("PRODUCT.csv")
oem_data = load_csv("OEM.csv")

FAQ = {}
for r in faq_raw:
    if safe_str(r.get("사용여부")).upper() == "Y":
        q = safe_str(r.get("질문"))
        a = safe_str(r.get("답변"))
        if q and a:
            FAQ[normalize_text(q)] = a

# -----------------
# TOKEN
# -----------------
token = None
expire = 0

def get_token():
    global token, expire
    now = int(time.time())

    if token and now < expire:
        return token

    try:
        payload = {
            "iss": os.environ["CLIENT_ID"],
            "sub": os.environ["CLIENT_EMAIL"],
            "iat": now,
            "exp": now + 3600
        }

        private_key = os.environ["PRIVATE_KEY"].replace("\\n", "\n")
        jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

        r = requests.post(
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
        expire = now + 3000
        return token

    except Exception as e:
        print("TOKEN ERROR:", e)
        return None

def send(user_id, body):
    t = get_token()
    if not t:
        print("SEND FAIL: NO TOKEN")
        return

    try:
        r = requests.post(
            f"https://www.worksapis.com/v1.0/bots/{BOT_ID}/users/{user_id}/messages",
            headers={"Authorization": f"Bearer {t}"},
            json=body
        )
        print("SEND:", r.status_code)
    except Exception as e:
        print("SEND ERROR:", e)

def send_text(user_id, text):
    send(user_id, {"content": {"type": "text", "text": text}})

# -----------------
# 기능들 (전부 정의)
# -----------------
def send_category_menu(user_id):
    send_text(user_id, "스펙 기능 준비중")

def send_spec(user_id, category):
    rows = [r for r in data if normalize_text(r.get("구분")) == category]
    if not rows:
        send_text(user_id, "데이터 없음")
        return
    send_text(user_id, rows[0].get("스펙코드", "-"))

def send_product(user_id, row):
    name = safe_str(row.get("제품명")) or "-"
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
        "content": {
            "type": "flex",
            "altText": name,
            "contents": bubble
        }
    })

def send_oem(user_id):
    bubbles = []
    for r in oem_data:
        bubbles.append({
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": safe_str(r.get("OEM"))}
                ]
            }
        })

    if not bubbles:
        send_text(user_id, "OEM 없음")
        return

    send(user_id, {
        "content": {
            "type": "flex",
            "altText": "OEM",
            "contents": {
                "type": "carousel",
                "contents": bubbles[:10]
            }
        }
    })

# -----------------
# 메인
# -----------------
def handle_message(user_id, msg):
    norm = normalize_text(msg)

    # FAQ
    if norm in FAQ:
        send_text(user_id, FAQ[norm])
        return

    # PRODUCT 직접
    for r in product_data:
        if normalize_text(r.get("제품명")) == norm:
            send_product(user_id, r)
            return

    # OEM
    if norm == "OEM":
        send_oem(user_id)
        return

    # 스펙
    if norm in ["스펙", "SPEC"]:
        send_category_menu(user_id)
        return

    send_text(user_id, "원하시는 기능을 찾지 못했습니다.")

@app.route("/", methods=["POST"])
def bot():
    try:
        req = request.get_json()
        user_id = req["source"]["userId"]
        msg = req["content"]["text"]
        handle_message(user_id, msg)
    except Exception as e:
        print("ERROR:", e)
    return "ok"

@app.route("/health")
def health():
    return "ok"
