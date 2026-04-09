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

token_lock = Lock()
cached_token = None
cached_token_expire_at = 0

session = requests.Session()


def normalize_text(text):
    return str(text or "").strip().upper().replace(" ", "")


def find_similar_faq_key(msg):
    keys = list(FAQ_NORMALIZED.keys())
    matches = get_close_matches(msg, keys, n=1, cutoff=0.7)
    return matches[0] if matches else None


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

# =========================
# ◇ DATA CSV 로드
# =========================
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

# =========================
# ◇ FAQ CSV 로드
# =========================
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

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

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
    body = {
        "content": {
            "type": "text",
            "text": text
        }
    }
    send_request(user_id, body)


def send_category_menu(user_id):
    body = {
        "content": {
            "type": "button_template",
            "contentText": "스펙구분을 선택하세요.",
            "actions": [
                {"type": "message", "label": "HKMC", "text": "CAT|HKMC"},
                {"type": "message", "label": "GM", "text": "CAT|GM"},
                {"type": "message", "label": "RENAULT", "text": "CAT|RENAULT"},
                {"type": "message", "label": "APTIV", "text": "CAT|APTIV"},
                {"type": "message", "label": "UL", "text": "CAT|UL"}
            ]
        }
    }
    send_request(user_id, body)


def get_rows_by_category(category):
    rows = [row for row in data if row["구분"] == category]
    rows.sort(key=lambda x: (x["정렬순서"], x["스펙코드"]))
    return rows


def make_item_row(row):
    spec_code = safe_str(row.get("스펙코드", ""))[:26] or "-"
    desc = safe_str(row.get("간단설명", ""))[:38] or "설명 없음"
    pdf_link = safe_str(row.get("PDF링크", ""))

    left_box = {
        "type": "box",
        "layout": "vertical",
        "flex": 9,
        "contents": [
            {"type": "text", "text": spec_code, "weight": "bold", "size": "md"},
            {"type": "text", "text": desc, "size": "sm"}
        ]
    }

    if is_valid_uri(pdf_link):
        right_component = {
            "type": "box",
            "layout": "vertical",
            "flex": 1,
            "backgroundColor": "#8F8F8F",
            "cornerRadius": "6px",
            "paddingAll": "4px",
            "action": {"type": "uri", "uri": pdf_link},
            "contents": [{"type": "text", "text": "▼", "size": "xs", "align": "center", "color": "#FFFFFF"}]
        }
    else:
        right_component = {
            "type": "box",
            "layout": "vertical",
            "flex": 1,
            "backgroundColor": "#C8C8C8",
            "cornerRadius": "6px",
            "paddingAll": "4px",
            "contents": [{"type": "text", "text": "-", "size": "xs", "align": "center"}]
        }

    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [left_box, right_component]
    }


def send_flex_spec_pages(user_id, category):
    rows = get_rows_by_category(category)

    if not rows:
        send_text_message(user_id, f"{category} 목록이 없습니다.")
        return

    contents = [make_item_row(r) for r in rows[:10]]

    body = {
        "content": {
            "type": "flex",
            "altText": f"{category} 목록",
            "contents": {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": contents
                }
            }
        }
    }

    send_request(user_id, body)


def handle_message(user_id, raw_msg):
    raw_msg = safe_str(raw_msg)
    msg = normalize_text(raw_msg)

    if msg in FAQ_NORMALIZED:
        send_text_message(user_id, FAQ_NORMALIZED[msg])
        return

    similar_key = find_similar_faq_key(msg)
    if similar_key:
        send_text_message(user_id, FAQ_NORMALIZED[similar_key])
        return

    if msg in ["스펙", "SPEC"]:
        send_category_menu(user_id)
        return

    if raw_msg.upper().startswith("CAT|"):
        category = raw_msg.split("|")[1].upper()
        if category in CATEGORY_LIST:
            send_flex_spec_pages(user_id, category)
            return

    send_text_message(user_id, "원하시는 기능을 찾지 못했습니다.")


@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True)
    user_id = req["source"]["userId"]
    text = req["content"]["text"]

    handle_message(user_id, text)
    return "ok", 200


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
