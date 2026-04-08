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
CATEGORY_LIST = ["HKMC", "GM", "RENAULT", "APTIV"]
CAROUSEL_SIZE = 10

FAQ = {
    "주소": "서울시 ...\n한미케이블 본사",
    "회사주소": "서울시 ...\n한미케이블 본사",
    "본사주소": "서울시 ...\n한미케이블 본사",
    "전화번호": "대표번호: 02-1234-5678\n팩스: 02-1111-2222",
    "대표번호": "02-1234-5678",
    "연락처": "02-1234-5678",
    "팩스": "02-1111-2222",
    "이메일": "대표: test@example.com\n기술문의: tech@example.com",
    "홈페이지": "https://example.com"
}

data = []

token_lock = Lock()
cached_token = None
cached_token_expire_at = 0

session = requests.Session()


def normalize_text(text):
    return str(text).strip().upper().replace(" ", "")


FAQ_NORMALIZED = {normalize_text(k): v for k, v in FAQ.items()}


def find_similar_faq_key(msg):
    keys = list(FAQ_NORMALIZED.keys())
    matches = get_close_matches(msg, keys, n=1, cutoff=0.7)
    return matches[0] if matches else None


def to_int(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "data.csv")

with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if str(row.get("사용여부", "")).strip().upper() == "Y":
            cleaned = {
                "구분": str(row.get("구분", "")).strip().upper(),
                "정렬순서": to_int(row.get("정렬순서", 9999), 9999),
                "스펙코드": str(row.get("스펙코드", "")).strip(),
                "간단설명": str(row.get("간단설명", "")).strip(),
                "PDF링크": str(row.get("PDF링크", "")).strip(),
                "이미지링크": str(row.get("이미지링크", "")).strip()
            }
            data.append(cleaned)


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

        print("TOKEN STATUS:", r.status_code)
        print("TOKEN RESPONSE:", r.text)

        r.raise_for_status()
        token_json = r.json()

        if "access_token" not in token_json:
            raise Exception(f"access_token 없음: {token_json}")

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

    print("SEND STATUS:", r.status_code)
    print("SEND RESPONSE:", r.text)

    if r.status_code == 401:
        token = get_token(force_refresh=True)
        headers["Authorization"] = f"Bearer {token}"
        r = session.post(url, headers=headers, json=body, timeout=10)

        print("RETRY SEND STATUS:", r.status_code)
        print("RETRY SEND RESPONSE:", r.text)

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
            "contentText": "스펙 구분을 선택하세요.",
            "actions": [
                {"type": "message", "label": "HKMC", "text": "CAT|HKMC"},
                {"type": "message", "label": "GM", "text": "CAT|GM"},
                {"type": "message", "label": "RENAULT", "text": "CAT|RENAULT"},
                {"type": "message", "label": "APTIV", "text": "CAT|APTIV"}
            ]
        }
    }
    send_request(user_id, body)


def get_rows_by_category(category):
    rows = [row for row in data if row["구분"] == category]
    rows.sort(key=lambda x: (x["정렬순서"], x["스펙코드"]))
    return rows


def chunk_list(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def make_carousel_column(row):
    return {
        "title": row["스펙코드"][:40],
        "text": row["간단설명"][:60] if row["간단설명"] else "설명 없음",
        "actions": [
            {
                "type": "uri",
                "label": "보기",
                "uri": row["PDF링크"]
            }
        ]
    }


def send_carousel_message(user_id, category):
    rows = get_rows_by_category(category)

    if not rows:
        send_text_message(user_id, f"{category} 목록이 없습니다.")
        return

    valid_rows = []
    for row in rows:
        if row["스펙코드"] and row["PDF링크"]:
            valid_rows.append(row)

    if not valid_rows:
        send_text_message(user_id, f"{category} 유효한 데이터가 없습니다.")
        return

    chunks = chunk_list(valid_rows, CAROUSEL_SIZE)

    for chunk in chunks:
        columns = [make_carousel_column(row) for row in chunk]

        body = {
            "content": {
                "type": "carousel",
                "columns": columns
            }
        }

        send_request(user_id, body)


def handle_message(user_id, raw_msg):
    raw_msg = str(raw_msg).strip()
    msg_normalized = normalize_text(raw_msg)
    msg_upper = str(raw_msg).strip().upper()

    if msg_normalized in FAQ_NORMALIZED:
        send_text_message(user_id, FAQ_NORMALIZED[msg_normalized])
        return

    similar_key = find_similar_faq_key(msg_normalized)
    if similar_key:
        send_text_message(user_id, FAQ_NORMALIZED[similar_key])
        return

    if msg_normalized in ["스펙", "스팩", "SPEC"]:
        send_category_menu(user_id)
        return

    if msg_upper.startswith("CAT|"):
        category = msg_upper.split("|", 1)[1].strip().upper()
        if category in CATEGORY_LIST:
            send_carousel_message(user_id, category)
            return

    if msg_upper in CATEGORY_LIST:
        send_carousel_message(user_id, msg_upper)
        return

    send_text_message(user_id, "원하시는 기능을 찾지 못했습니다.\n스펙 또는 회사 정보를 입력해 주세요.")


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200


@app.route("/", methods=["GET"])
def home():
    return "ok", 200


@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True)
    print("CALLBACK JSON:", req)

    user_id = req["source"]["userId"]
    raw_msg = str(req["content"]["text"]).strip()

    try:
        handle_message(user_id, raw_msg)
    except Exception as e:
        print("HANDLE ERROR:", str(e))
        try:
            send_text_message(user_id, "처리 중 오류가 발생했습니다.")
        except Exception as send_err:
            print("ERROR NOTICE FAILED:", str(send_err))

    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
