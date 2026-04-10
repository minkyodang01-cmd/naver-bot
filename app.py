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

ROWS_PER_PAGE = 10
MAX_BUBBLES_PER_MESSAGE = 10

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


def to_int(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def safe_str(value):
    return str(value or "").strip()


def is_valid_uri(uri):
    uri = safe_str(uri)
    return uri.startswith("https://") or uri.startswith("http://")


def chunk_list(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------
# DATA CSV (스펙) 그대로
# -------------------
CSV_PATH = os.path.join(BASE_DIR, "data.csv")
with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if safe_str(row.get("사용여부", "")).upper() == "Y":
            cleaned = {
                "구분": safe_str(row.get("구분", "")).upper(),
                "정렬순서": to_int(row.get("정렬순서", 9999), 9999),
                "스펙코드": safe_str(row.get("스펙코드", "")),
                "간단설명": safe_str(row.get("간단설명", "")),
                "PDF링크": safe_str(row.get("PDF링크", "")),
                "이미지링크": safe_str(row.get("이미지링크", ""))
            }
            data.append(cleaned)

# -------------------
# FAQ 그대로
# -------------------
FAQ_PATH = os.path.join(BASE_DIR, "faq.csv")
with open(FAQ_PATH, newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if safe_str(row.get("사용여부", "")).upper() == "Y":
            q = safe_str(row.get("질문", ""))
            a = safe_str(row.get("답변", ""))
            if q and a:
                FAQ[q] = a

FAQ_NORMALIZED = {normalize_text(k): v for k, v in FAQ.items()}

# -------------------
# PRODUCT / OEM 추가
# -------------------
PRODUCT_PATH = os.path.join(BASE_DIR, "PRODUCT.csv")
OEM_PATH = os.path.join(BASE_DIR, "OEM.csv")

with open(PRODUCT_PATH, newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        product_data.append(row)

with open(OEM_PATH, newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        oem_data.append(row)


def find_similar_faq_key(msg):
    keys = list(FAQ_NORMALIZED.keys())
    matches = get_close_matches(msg, keys, n=1, cutoff=0.7)
    return matches[0] if matches else None


def get_token(force_refresh=False):
    global cached_token, cached_token_expire_at

    now = int(time.time())

    with token_lock:
        if not force_refresh and cached_token and now < cached_token_expire_at:
            return cached_token

        payload = {
            "iss": os.environ["CLIENT_ID"],
            "sub": os.environ["CLIENT_EMAIL"],
            "iat": now,
            "exp": now + 3600
        }

        private_key = os.environ["PRIVATE_KEY"].replace("\\n", "\n")
        jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

        url = "https://auth.worksmobile.com/oauth2/v2.0/token"

        token_data = {
            "assertion": jwt_token,
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "client_id": os.environ["CLIENT_ID"],
            "client_secret": os.environ["CLIENT_SECRET"],
            "scope": "bot.message"
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        r = session.post(url, data=token_data, headers=headers, timeout=10)
        r.raise_for_status()

        token_json = r.json()
        cached_token = token_json["access_token"]
        expires_in = to_int(token_json.get("expires_in", 3600), 3600)
        cached_token_expire_at = now + max(60, expires_in - 120)

        return cached_token


def send_request(user_id, body):
    token = get_token()

    url = f"https://www.worksapis.com/v1.0/bots/{BOT_ID}/users/{user_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    r = session.post(url, headers=headers, json=body, timeout=10)

    if r.status_code == 401:
        token = get_token(force_refresh=True)
        headers["Authorization"] = f"Bearer {token}"
        r = session.post(url, headers=headers, json=body, timeout=10)

    r.raise_for_status()


def send_text_message(user_id, text):
    body = {"content": {"type": "text", "text": text}}
    send_request(user_id, body)


# -------------------
# PRODUCT
# -------------------

def send_product_menu(user_id):
    actions = []
    for row in product_data:
        actions.append({
            "type": "message",
            "label": row["제품명"],
            "text": f"PROD|{row['제품명']}"
        })

    body = {
        "content": {
            "type": "button_template",
            "contentText": "제품을 선택하세요",
            "actions": actions[:5]
        }
    }
    send_request(user_id, body)


def send_product_flex(user_id, row):
    body = {
        "content": {
            "type": "flex",
            "altText": row["제품명"],
            "contents": {
                "type": "bubble",
                "hero": {
                    "type": "image",
                    "url": row["이미지"],
                    "size": "full"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": row["제품명"], "weight": "bold"},
                        {"type": "text", "text": row["설명"], "wrap": True}
                    ]
                }
            }
        }
    }
    send_request(user_id, body)


# -------------------
# OEM
# -------------------

def send_oem_flex(user_id):
    bubbles = []

    for row in oem_data:
        bubbles.append({
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": row["이미지"],
                "size": "full"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": row["OEM"], "weight": "bold"}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [{
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "다운로드",
                        "uri": row["PDF"]
                    }
                }]
            }
        })

    body = {
        "content": {
            "type": "flex",
            "altText": "OEM 목록",
            "contents": {
                "type": "carousel",
                "contents": bubbles[:10]
            }
        }
    }

    send_request(user_id, body)


# -------------------
# 기존 스펙 함수 그대로 유지 (건드리지 않음)
# -------------------

def get_rows_by_category(category):
    rows = [row for row in data if row["구분"] == category]
    rows.sort(key=lambda x: (x["정렬순서"], x["스펙코드"]))
    return rows

# (이하 기존 flex spec 함수 전부 그대로 유지)


def handle_message(user_id, raw_msg):
    raw_msg = safe_str(raw_msg)
    msg_normalized = normalize_text(raw_msg)
    msg_upper = raw_msg.upper()

    # FAQ
    if msg_normalized in FAQ_NORMALIZED:
        send_text_message(user_id, FAQ_NORMALIZED[msg_normalized])
        return

    similar_key = find_similar_faq_key(msg_normalized)
    if similar_key:
        send_text_message(user_id, FAQ_NORMALIZED[similar_key])
        return

    # PRODUCT
    if msg_normalized == "제품":
        send_product_menu(user_id)
        return

    if msg_upper.startswith("PROD|"):
        name = msg_upper.split("|")[1]
        for row in product_data:
            if row["제품명"].upper() == name:
                send_product_flex(user_id, row)
                return

    # OEM
    if msg_normalized == "OEM":
        send_oem_flex(user_id)
        return

    # 기존 스펙
    if msg_normalized in ["스펙", "스팩", "SPEC"]:
        send_category_menu(user_id)
        return

    if msg_upper.startswith("CAT|"):
        category = msg_upper.split("|", 1)[1].strip().upper()
        if category in CATEGORY_LIST:
            send_flex_spec_pages(user_id, category)
            return

    if msg_upper in CATEGORY_LIST:
        send_flex_spec_pages(user_id, msg_upper)
        return

    send_text_message(user_id, "원하시는 기능을 찾지 못했습니다.")


@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True, silent=True) or {}
    user_id = safe_str(req.get("source", {}).get("userId"))
    text = safe_str(req.get("content", {}).get("text"))

    if user_id and text:
        handle_message(user_id, text)

    return "ok", 200


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200


@app.route("/wake", methods=["GET"])
def wake():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
