from flask import Flask, request
import csv
import requests
import os
import time
import jwt
from threading import Lock
from math import ceil

app = Flask(__name__)

BOT_ID = os.environ["BOT_ID"]
CATEGORY_LIST = ["HKMC", "GM", "RENAULT", "APTIV"]

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
FAQ_UPPER = {k.upper(): v for k, v in FAQ.items()}

data = []

token_lock = Lock()
cached_token = None
cached_token_expire_at = 0

session = requests.Session()

# 한 페이지에 표시할 항목 수
ROWS_PER_PAGE = 10
# 한 Flex Carousel 안에 넣을 페이지 수
# 공식 문서상 bubble 최대 10개
PAGES_PER_MESSAGE = 10


def to_int(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def safe_str(value):
    return str(value or "").strip()


with open("data.csv", newline="", encoding="utf-8-sig") as f:
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


def make_item_row(row):
    spec_code = row["스펙코드"][:30] if row["스펙코드"] else "-"
    desc = row["간단설명"][:70] if row["간단설명"] else "설명 없음"
    pdf_link = row["PDF링크"]

    row_contents = [
        {
            "type": "box",
            "layout": "vertical",
            "spacing": "xs",
            "flex": 7,
            "contents": [
                {
                    "type": "text",
                    "text": spec_code,
                    "weight": "bold",
                    "size": "sm",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": desc,
                    "size": "xs",
                    "color": "#666666",
                    "wrap": True
                }
            ]
        }
    ]

    if pdf_link:
        row_contents.append({
            "type": "button",
            "style": "primary",
            "height": "sm",
            "color": "#1F64FF",
            "flex": 3,
            "action": {
                "type": "uri",
                "label": "도면 보기",
                "uri": pdf_link
            }
        })
    else:
        row_contents.append({
            "type": "text",
            "text": "링크 없음",
            "size": "xs",
            "color": "#999999",
            "align": "end",
            "flex": 3
        })

    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "margin": "md",
        "contents": [
            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "contents": row_contents
            },
            {
                "type": "separator",
                "margin": "md"
            }
        ]
    }


def make_page_bubble(category, page_rows, page_no, total_pages, total_count):
    body_contents = [
        {
            "type": "text",
            "text": f"{category} 목록",
            "weight": "bold",
            "size": "lg",
            "wrap": True
        },
        {
            "type": "text",
            "text": f"{page_no} / {total_pages} 페이지   총 {total_count}건",
            "size": "xs",
            "color": "#666666",
            "margin": "sm"
        }
    ]

    for row in page_rows:
        body_contents.append(make_item_row(row))

    return {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "16px",
            "contents": body_contents
        }
    }


def send_flex_pages(user_id, category, all_rows):
    if not all_rows:
        send_text_message(user_id, f"{category} 목록이 없습니다.")
        return

    page_chunks = chunk_list(all_rows, ROWS_PER_PAGE)
    total_pages = len(page_chunks)
    total_count = len(all_rows)

    # 한 메시지 안에는 최대 10페이지까지만 가능
    # 11페이지 이상이면 여러 메시지로 나눠 전송
    carousel_groups = chunk_list(list(enumerate(page_chunks, start=1)), PAGES_PER_MESSAGE)

    for group in carousel_groups:
        bubbles = []

        for page_no, page_rows in group:
            bubble = make_page_bubble(
                category=category,
                page_rows=page_rows,
                page_no=page_no,
                total_pages=total_pages,
                total_count=total_count
            )
            bubbles.append(bubble)

        body = {
            "content": {
                "type": "flex",
                "altText": f"{category} 스펙 목록",
                "contents": {
                    "type": "carousel",
                    "contents": bubbles
                }
            }
        }

        send_request(user_id, body)


def handle_message(user_id, raw_msg):
    raw_msg = safe_str(raw_msg)
    msg = raw_msg.upper()

    if msg in FAQ_UPPER:
        send_text_message(user_id, FAQ_UPPER[msg])
        return

    if msg in ["스펙", "SPEC"]:
        send_category_menu(user_id)
        return

    if msg.startswith("CAT|"):
        category = msg.split("|", 1)[1].strip().upper()
        if category in CATEGORY_LIST:
            rows = get_rows_by_category(category)
            send_flex_pages(user_id, category, rows)
        return

    if msg in CATEGORY_LIST:
        rows = get_rows_by_category(msg)
        send_flex_pages(user_id, msg, rows)
        return


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200


@app.route("/pause", methods=["GET"])
def pause():
    return "pause endpoint ready", 200


@app.route("/resume", methods=["GET"])
def resume():
    return "resume endpoint ready", 200


@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True)
    print("CALLBACK JSON:", req)

    user_id = req["source"]["userId"]
    raw_msg = safe_str(req["content"]["text"])

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
