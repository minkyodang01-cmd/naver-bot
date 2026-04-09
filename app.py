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

ROWS_PER_PAGE = 10
MAX_BUBBLES_PER_MESSAGE = 10

data = []

token_lock = Lock()
cached_token = None
cached_token_expire_at = 0

session = requests.Session()


def normalize_text(text):
    return str(text or "").strip().upper().replace(" ", "")


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


def safe_str(value):
    return str(value or "").strip()


def is_valid_uri(uri):
    uri = safe_str(uri)
    return uri.startswith("https://") or uri.startswith("http://")


def chunk_list(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

print("DATA COUNT:", len(data))


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
    print("SEND BODY:", body)

    if r.status_code == 401:
        token = get_token(force_refresh=True)
        headers["Authorization"] = f"Bearer {token}"
        r = session.post(url, headers=headers, json=body, timeout=10)

        print("RETRY SEND STATUS:", r.status_code)
        print("RETRY SEND RESPONSE:", r.text)
        print("RETRY SEND BODY:", body)

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
                {"type": "message", "label": "APTIV", "text": "CAT|APTIV"}
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
        "spacing": "xs",
        "contents": [
            {
                "type": "text",
                "text": spec_code,
                "weight": "bold",
                "size": "md",
                "color": "#222222",
                "wrap": True
            },
            {
                "type": "text",
                "text": desc,
                "size": "sm",
                "color": "#666666",
                "wrap": True
            }
        ]
    }

    if is_valid_uri(pdf_link):
        right_component = {
            "type": "box",
            "layout": "vertical",
            "flex": 1,
            "backgroundColor": "#8F8F8F",
            "cornerRadius": "6px",
            "paddingTop": "3px",
            "paddingBottom": "3px",
            "paddingStart": "4px",
            "paddingEnd": "4px",
            "action": {
                "type": "uri",
                "label": "download",
                "uri": pdf_link
            },
            "contents": [
                {
                    "type": "text",
                    "text": "▼",
                    "size": "xs",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "align": "center"
                }
            ]
        }
    else:
        right_component = {
            "type": "box",
            "layout": "vertical",
            "flex": 1,
            "backgroundColor": "#C8C8C8",
            "cornerRadius": "6px",
            "paddingTop": "3px",
            "paddingBottom": "3px",
            "paddingStart": "4px",
            "paddingEnd": "4px",
            "contents": [
                {
                    "type": "text",
                    "text": "-",
                    "size": "xs",
                    "color": "#FFFFFF",
                    "align": "center"
                }
            ]
        }

    return {
        "type": "box",
        "layout": "vertical",
        "margin": "sm",
        "spacing": "sm",
        "contents": [
            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    left_box,
                    right_component
                ]
            },
            {
                "type": "separator",
                "color": "#B8B8B8"
            }
        ]
    }


def make_page_bubble(category, page_rows, page_no, total_pages, total_count):
    body_contents = [
        {
            "type": "text",
            "text": f"{category} 스펙 목록",
            "weight": "bold",
            "size": "lg",
            "color": "#333333",
            "wrap": True
        },
        {
            "type": "text",
            "text": f"{page_no}/{total_pages} 페이지  총 {total_count}건",
            "size": "xs",
            "color": "#666666",
            "margin": "md"
        }
    ]

    for row in page_rows:
        body_contents.append(make_item_row(row))

    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents
        }
    }


def send_flex_message_groups(user_id, category, valid_rows):
    page_chunks = chunk_list(valid_rows, ROWS_PER_PAGE)
    total_pages = len(page_chunks)
    total_count = len(valid_rows)

    bubble_pages = []
    for idx, page_rows in enumerate(page_chunks, start=1):
        bubble_pages.append(
            make_page_bubble(
                category=category,
                page_rows=page_rows,
                page_no=idx,
                total_pages=total_pages,
                total_count=total_count
            )
        )

    bubble_groups = chunk_list(bubble_pages, MAX_BUBBLES_PER_MESSAGE)

    for group_index, bubble_group in enumerate(bubble_groups, start=1):
        body = {
            "content": {
                "type": "flex",
                "altText": f"{category} 스펙 목록 {group_index}",
                "contents": {
                    "type": "carousel",
                    "contents": bubble_group
                }
            }
        }
        send_request(user_id, body)


def send_flex_spec_pages(user_id, category):
    rows = get_rows_by_category(category)

    if not rows:
        send_text_message(user_id, f"{category} 목록이 없습니다.")
        return

    valid_rows = []
    invalid_rows = []

    for row in rows:
        spec_code = safe_str(row.get("스펙코드", ""))
        pdf_link = safe_str(row.get("PDF링크", ""))

        if spec_code and is_valid_uri(pdf_link):
            valid_rows.append(row)
        else:
            invalid_rows.append({
                "스펙코드": spec_code,
                "PDF링크": pdf_link
            })

    print("CATEGORY:", category)
    print("ROW COUNT:", len(rows))
    print("VALID ROW COUNT:", len(valid_rows))
    print("INVALID ROWS:", invalid_rows)

    if not valid_rows:
        send_text_message(user_id, f"{category} 유효한 데이터가 없습니다.")
        return

    send_flex_message_groups(user_id, category, valid_rows)


def handle_message(user_id, raw_msg):
    raw_msg = safe_str(raw_msg)
    msg_normalized = normalize_text(raw_msg)
    msg_upper = raw_msg.upper()

    print("RAW MSG:", raw_msg)
    print("NORMALIZED MSG:", msg_normalized)
    print("UPPER MSG:", msg_upper)

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
            send_flex_spec_pages(user_id, category)
            return

    if msg_upper in CATEGORY_LIST:
        send_flex_spec_pages(user_id, msg_upper)
        return

    send_text_message(user_id, "원하시는 기능을 찾지 못했습니다.\n\n(입력 : 스펙, 전화번호, 주소, SSA, 열수축튜브 등) .")


@app.route("/health", methods=["GET", "HEAD"])
def health():
    return "ok", 200


@app.route("/", methods=["GET"])
def home():
    return "ok", 200


@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True, silent=True) or {}
    print("CALLBACK JSON:", req)

    try:
        source = req.get("source", {}) or {}
        content = req.get("content", {}) or {}
        user_id = safe_str(source.get("userId", ""))

        if not user_id:
            print("NO USER ID")
            return "ok", 200

        raw_msg = safe_str(content.get("text", ""))

        if not raw_msg:
            print("NO TEXT MESSAGE")
            return "ok", 200

        handle_message(user_id, raw_msg)

    except Exception as e:
        print("HANDLE ERROR:", str(e))
        try:
            source = req.get("source", {}) or {}
            user_id = safe_str(source.get("userId", ""))
            if user_id:
                send_text_message(user_id, "처리 중 오류가 발생했습니다.")
        except Exception as send_err:
            print("ERROR NOTICE FAILED:", str(send_err))

    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
