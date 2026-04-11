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
BUTTON_TEMPLATE_MAX_ACTIONS = 5

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
    if size <= 0:
        return [items]
    return [items[i:i + size] for i in range(0, len(items), size)]


def load_csv_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DATA CSV 로드
CSV_PATH = os.path.join(BASE_DIR, "data.csv")
for row in load_csv_rows(CSV_PATH):
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

# FAQ CSV 로드
FAQ_PATH = os.path.join(BASE_DIR, "faq.csv")
for row in load_csv_rows(FAQ_PATH):
    if safe_str(row.get("사용여부", "")).upper() != "Y":
        continue

    question = safe_str(row.get("질문키", "")) or safe_str(row.get("질문", ""))
    answer = safe_str(row.get("응답유형", "")) or safe_str(row.get("답변", "")) or safe_str(row.get("응답텍스트", ""))

    if question and answer:
        FAQ[question] = answer

FAQ_NORMALIZED = {normalize_text(k): v for k, v in FAQ.items()}

# PRODUCT CSV 로드
PRODUCT_PATH = os.path.join(BASE_DIR, "PRODUCT.csv")
for row in load_csv_rows(PRODUCT_PATH):
    if safe_str(row.get("사용여부", "Y")).upper() == "Y":
        cleaned = {
            "구분": safe_str(row.get("구분", "")),
            "품명": safe_str(row.get("품명", "")),
            "온도": safe_str(row.get("온도", "")),
            "재질": safe_str(row.get("재질", "")),
            "특징": safe_str(row.get("특징", "")),
            "제품사진": safe_str(row.get("제품사진", "")),
            "도면사진": safe_str(row.get("도면사진", "")),
            "순서": to_int(row.get("순서", 9999), 9999),
        }
        if cleaned["품명"]:
            product_data.append(cleaned)

# OEM CSV 로드
OEM_PATH = os.path.join(BASE_DIR, "OEM.csv")
for row in load_csv_rows(OEM_PATH):
    cleaned = {
        "OEM": safe_str(row.get("OEM", "")),
        "HANMI P/N": safe_str(row.get("HANMI P/N", "")),
        "OEM P/NO": safe_str(row.get("OEM P/NO", "")),
        "DESCRIPTION": safe_str(row.get("DESCRIPTION", "")),
        "Temp": safe_str(row.get("Temp", "")),
        "Type": safe_str(row.get("Type", "")),
        "PDF 링크": safe_str(row.get("PDF 링크", "")),
        "순서": to_int(row.get("순서", 9999), 9999),
    }
    if cleaned["OEM"] or cleaned["HANMI P/N"]:
        oem_data.append(cleaned)


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
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        r = session.post(url, data=token_data, headers=headers, timeout=10)
        print("TOKEN STATUS:", r.status_code)
        print("TOKEN RESPONSE:", r.text)
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
    body = {"content": {"type": "text", "text": safe_str(text)}}
    send_request(user_id, body)


def send_button_template(user_id, content_text, actions):
    valid_actions = [a for a in actions if a]
    if not valid_actions:
        send_text_message(user_id, content_text)
        return

    for action_chunk in chunk_list(valid_actions, BUTTON_TEMPLATE_MAX_ACTIONS):
        body = {
            "content": {
                "type": "button_template",
                "contentText": content_text,
                "actions": action_chunk
            }
        }
        send_request(user_id, body)


def make_download_box(pdf_link):
    if is_valid_uri(pdf_link):
        return {
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

    return {
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


def make_product_select_box(item_name):
    return {
        "type": "box",
        "layout": "vertical",
        "flex": 1,
        "backgroundColor": "#C8C8C8",
        "cornerRadius": "6px",
        "paddingTop": "3px",
        "paddingBottom": "3px",
        "paddingStart": "4px",
        "paddingEnd": "4px",
        "action": {
            "type": "message",
            "label": safe_str(item_name)[:20] or "select",
            "text": safe_str(item_name)
        },
        "contents": [
            {
                "type": "text",
                "text": "▽",
                "size": "xs",
                "weight": "bold",
                "color": "#FFFFFF",
                "align": "center"
            }
        ]
    }


def make_list_row(title, desc, right_component):
    left_box = {
        "type": "box",
        "layout": "vertical",
        "flex": 9,
        "spacing": "xs",
        "contents": [
            {
                "type": "text",
                "text": safe_str(title)[:32] or "-",
                "weight": "bold",
                "size": "md",
                "color": "#222222",
                "wrap": True
            },
            {
                "type": "text",
                "text": safe_str(desc)[:60] or "설명 없음",
                "size": "sm",
                "color": "#666666",
                "wrap": True
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
                "contents": [left_box, right_component]
            },
            {"type": "separator", "color": "#B8B8B8"}
        ]
    }


def make_page_bubble(title, page_rows, page_no, total_pages, total_count, row_renderer):
    body_contents = [
        {
            "type": "text",
            "text": title,
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
        body_contents.append(row_renderer(row))

    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents
        }
    }


def send_flex_grouped_pages(user_id, title, alt_prefix, rows, row_renderer):
    if not rows:
        send_text_message(user_id, f"{title} 데이터가 없습니다.")
        return

    page_chunks = chunk_list(rows, ROWS_PER_PAGE)
    total_pages = len(page_chunks)
    total_count = len(rows)

    bubble_pages = []
    for idx, page_rows in enumerate(page_chunks, start=1):
        bubble_pages.append(
            make_page_bubble(
                title=title,
                page_rows=page_rows,
                page_no=idx,
                total_pages=total_pages,
                total_count=total_count,
                row_renderer=row_renderer,
            )
        )

    bubble_groups = chunk_list(bubble_pages, MAX_BUBBLES_PER_MESSAGE)

    for group_index, bubble_group in enumerate(bubble_groups, start=1):
        body = {
            "content": {
                "type": "flex",
                "altText": f"{alt_prefix} {group_index}",
                "contents": {
                    "type": "carousel",
                    "contents": bubble_group
                }
            }
        }
        send_request(user_id, body)


# 기존 스펙 기능 유지

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
                {"type": "message", "label": "UL", "text": "CAT|UL"},
            ]
        }
    }
    send_request(user_id, body)


def get_rows_by_category(category):
    rows = [row for row in data if row["구분"] == category]
    rows.sort(key=lambda x: (x["정렬순서"], x["스펙코드"]))
    return rows


def make_spec_item_row(row):
    spec_code = safe_str(row.get("스펙코드", ""))
    desc = safe_str(row.get("간단설명", ""))
    pdf_link = safe_str(row.get("PDF링크", ""))
    return make_list_row(spec_code, desc, make_download_box(pdf_link))


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
            invalid_rows.append({"스펙코드": spec_code, "PDF링크": pdf_link})

    print("CATEGORY:", category)
    print("ROW COUNT:", len(rows))
    print("VALID ROW COUNT:", len(valid_rows))
    print("INVALID ROWS:", invalid_rows)

    if not valid_rows:
        send_text_message(user_id, f"{category} 유효한 데이터가 없습니다.")
        return

    send_flex_grouped_pages(user_id, f"{category} 스펙 목록", f"{category} 스펙 목록", valid_rows, make_spec_item_row)


# OEM 기능

def display_oem_group_name(raw_group):
    raw = normalize_text(raw_group)
    if raw == "GMW":
        return "GM"
    return safe_str(raw_group).upper()


def get_oem_groups_in_order():
    existing = []
    seen = set()
    for row in oem_data:
        group = safe_str(row.get("OEM", ""))
        if group and group not in seen:
            seen.add(group)
            existing.append(group)

    preferred = ["HKMC", "GMW", "GM", "RENAULT", "APTIV", "UL", "DAIMLER"]
    ordered = []
    used = set()

    for p in preferred:
        for e in existing:
            if normalize_text(e) == normalize_text(p) and e not in used:
                ordered.append(e)
                used.add(e)

    for e in existing:
        if e not in used:
            ordered.append(e)
            used.add(e)

    return ordered


def get_oem_rows_by_group(group_name):
    target = normalize_text(group_name)
    rows = [row for row in oem_data if normalize_text(row.get("OEM", "")) == target]
    rows.sort(key=lambda x: (x["순서"], safe_str(x["HANMI P/N"]), safe_str(x["OEM P/NO"])))
    return rows


def send_oem_group_menu(user_id):
    groups = get_oem_groups_in_order()
    if not groups:
        send_text_message(user_id, "OEM 데이터가 없습니다.")
        return

    actions = []
    for raw_group in groups:
        display_name = display_oem_group_name(raw_group)
        actions.append({
            "type": "message",
            "label": display_name[:20],
            "text": f"OEMCAT|{raw_group}"
        })

    send_button_template(user_id, "OEM 구분을 선택하세요.", actions)


def make_oem_item_row(row):
    hanmi_pn = safe_str(row.get("HANMI P/N", ""))
    oem_pno = safe_str(row.get("OEM P/NO", ""))
    desc = safe_str(row.get("DESCRIPTION", ""))
    temp = safe_str(row.get("Temp", ""))
    type_value = safe_str(row.get("Type", ""))
    pdf_link = safe_str(row.get("PDF 링크", ""))

    title = hanmi_pn or oem_pno or safe_str(row.get("OEM", "")) or "-"

    sub_lines = []
    if oem_pno and oem_pno != title:
        sub_lines.append(oem_pno)
    if desc:
        sub_lines.append(desc)

    tail = []
    if temp:
        tail.append(temp)
    if type_value:
        tail.append(type_value)
    if tail:
        sub_lines.append(" / ".join(tail))

    return make_list_row(title, "\n".join(sub_lines), make_download_box(pdf_link))


def send_oem_flex_pages(user_id, group_name):
    rows = get_oem_rows_by_group(group_name)
    display_name = display_oem_group_name(group_name)

    if not rows:
        send_text_message(user_id, f"{display_name} OEM 데이터가 없습니다.")
        return

    valid_rows = []
    for row in rows:
        if safe_str(row.get("HANMI P/N")) or safe_str(row.get("OEM P/NO")) or safe_str(row.get("DESCRIPTION")):
            valid_rows.append(row)

    if not valid_rows:
        send_text_message(user_id, f"{display_name} OEM 유효한 데이터가 없습니다.")
        return

    send_flex_grouped_pages(user_id, f"{display_name} OEM 목록", f"{display_name} OEM 목록", valid_rows, make_oem_item_row)


# PRODUCT 기능

def get_product_groups_in_order():
    groups = []
    seen = set()
    for row in product_data:
        group_name = safe_str(row.get("구분", ""))
        if group_name and group_name not in seen:
            seen.add(group_name)
            groups.append(group_name)
    return groups


def get_products_by_group(group_name):
    rows = [row for row in product_data if normalize_text(row.get("구분", "")) == normalize_text(group_name)]
    rows.sort(key=lambda x: (x["순서"], safe_str(x["품명"])))
    return rows


def find_product_group_by_name(user_input):
    target = normalize_text(user_input)
    for group_name in get_product_groups_in_order():
        if normalize_text(group_name) == target:
            return group_name
    return None


def send_product_group_menu(user_id):
    groups = get_product_groups_in_order()
    if not groups:
        send_text_message(user_id, "제품 데이터가 없습니다.")
        return

    actions = []
    for group_name in groups:
        actions.append({
            "type": "message",
            "label": group_name[:20],
            "text": f"PRODG|{group_name}"
        })

    send_button_template(user_id, "제품구분을 선택하세요.", actions)


def make_product_preview_row(row):
    item_name = safe_str(row.get("품명", "")) or "-"
    temp = safe_str(row.get("온도", ""))
    material = safe_str(row.get("재질", ""))
    feature = safe_str(row.get("특징", ""))

    desc_parts = []
    if feature:
        desc_parts.append(feature)
    if temp:
        desc_parts.append(temp)
    if material:
        desc_parts.append(material)

    return make_list_row(item_name, " / ".join(desc_parts), make_product_select_box(item_name))


def send_product_items_by_group(user_id, group_name):
    rows = get_products_by_group(group_name)
    if not rows:
        send_text_message(user_id, f"{group_name} 제품이 없습니다.")
        return

    send_flex_grouped_pages(user_id, f"{group_name} 목록", f"{group_name} 목록", rows, make_product_preview_row)


def build_product_body_contents(row):
    item_name = safe_str(row.get("품명", "")) or "-"
    group_name = safe_str(row.get("구분", ""))
    temp = safe_str(row.get("온도", ""))
    material = safe_str(row.get("재질", ""))
    feature = safe_str(row.get("특징", ""))

    contents = [{
        "type": "text",
        "text": item_name,
        "weight": "bold",
        "size": "xl",
        "color": "#222222",
        "wrap": True
    }]

    if group_name:
        contents.append({
            "type": "text",
            "text": group_name,
            "size": "sm",
            "color": "#666666",
            "margin": "sm",
            "wrap": True
        })

    detail_lines = []
    if temp:
        detail_lines.append(f"온도 : {temp}")
    if material:
        detail_lines.append(f"재질 : {material}")
    if feature:
        detail_lines.append(f"특징 : {feature}")

    if detail_lines:
        contents.append({
            "type": "text",
            "text": "\n".join(detail_lines),
            "size": "sm",
            "color": "#444444",
            "margin": "md",
            "wrap": True
        })

    return contents


def build_product_bubbles(row):
    item_name = safe_str(row.get("품명", "")) or "-"
    product_img = safe_str(row.get("제품사진", ""))
    drawing_img = safe_str(row.get("도면사진", ""))
    body_contents = build_product_body_contents(row)

    bubbles = []

    first_bubble = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents
        }
    }

    if is_valid_uri(product_img):
        first_bubble["hero"] = {
            "type": "image",
            "url": product_img,
            "size": "full",
            "aspectMode": "cover",
            "aspectRatio": "20:13"
        }

    bubbles.append(first_bubble)

    if is_valid_uri(drawing_img):
        drawing_bubble = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [{
                    "type": "text",
                    "text": f"{item_name} 도면",
                    "weight": "bold",
                    "size": "md",
                    "color": "#222222",
                    "wrap": True
                }]
            },
            "hero": {
                "type": "image",
                "url": drawing_img,
                "size": "full",
                "aspectMode": "contain",
                "aspectRatio": "20:13"
            }
        }
        bubbles.append(drawing_bubble)

    return bubbles


def send_product_flex(user_id, row):
    bubbles = build_product_bubbles(row)
    if len(bubbles) == 1:
        body = {
            "content": {
                "type": "flex",
                "altText": safe_str(row.get("품명", "")) or "제품 정보",
                "contents": bubbles[0]
            }
        }
    else:
        body = {
            "content": {
                "type": "flex",
                "altText": safe_str(row.get("품명", "")) or "제품 정보",
                "contents": {
                    "type": "carousel",
                    "contents": bubbles[:MAX_BUBBLES_PER_MESSAGE]
                }
            }
        }
    send_request(user_id, body)


def find_product_by_name(user_input):
    target = normalize_text(user_input)
    for row in product_data:
        if normalize_text(row.get("품명", "")) == target:
            return row
    return None


# UPTIME 유지

def edit_uptimerobot_monitor(status_value):
    api_key = os.environ["UPTIMEROBOT_API_KEY"]
    monitor_id = os.environ["UPTIMEROBOT_MONITOR_ID"]
    url = "https://api.uptimerobot.com/v2/editMonitor"
    payload = {"api_key": api_key, "id": monitor_id, "status": status_value}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(url, data=payload, headers=headers, timeout=10)
    print("UPTIMEROBOT STATUS:", r.status_code)
    print("UPTIMEROBOT RESPONSE:", r.text)
    r.raise_for_status()
    return r.text


# 메인 처리

def handle_message(user_id, raw_msg):
    raw_msg = safe_str(raw_msg)
    msg_normalized = normalize_text(raw_msg)
    msg_upper = raw_msg.upper()

    # 1. 제품명 우선
    matched_product = find_product_by_name(raw_msg)
    if matched_product:
        send_product_flex(user_id, matched_product)
        return

    # 2. 제품구분 직접 입력 우선
    matched_group = find_product_group_by_name(raw_msg)
    if matched_group:
        send_product_items_by_group(user_id, matched_group)
        return

    # 3. 제품 시작 키워드
    if msg_normalized in ["제품", "튜브"]:
        send_product_group_menu(user_id)
        return

    # 4. 제품구분 버튼 선택
    if msg_upper.startswith("PRODG|"):
        group_name = raw_msg.split("|", 1)[1].strip()
        send_product_items_by_group(user_id, group_name)
        return

    # 5. FAQ
    if msg_normalized in FAQ_NORMALIZED:
        send_text_message(user_id, FAQ_NORMALIZED[msg_normalized])
        return

    # 6. OEM
    if msg_normalized in ["OEM", "승인도", "오엠"]:
        send_oem_group_menu(user_id)
        return

    if msg_upper.startswith("OEMCAT|"):
        group_name = raw_msg.split("|", 1)[1].strip()
        send_oem_flex_pages(user_id, group_name)
        return

    # 7. 스펙
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

    # 8. FAQ 유사어는 맨 마지막
    similar_key = find_similar_faq_key(msg_normalized)
    if similar_key:
        send_text_message(user_id, FAQ_NORMALIZED[similar_key])
        return

    send_text_message(user_id, "원하시는 기능을 찾지 못했습니다.")


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200


@app.route("/wake", methods=["GET"])
def wake():
    return "ok", 200


@app.route("/pause", methods=["GET"])
def pause_monitor():
    edit_uptimerobot_monitor(0)
    return "paused", 200


@app.route("/resume", methods=["GET"])
def resume_monitor():
    edit_uptimerobot_monitor(1)
    return "resumed", 200


@app.route("/", methods=["GET"])
def home():
    return "ok", 200


@app.route("/", methods=["POST"])
def bot():
    req = request.get_json(force=True, silent=True) or {}
    print("CALLBACK JSON:", req)

    source = req.get("source", {}) or {}
    content = req.get("content", {}) or {}

    user_id = safe_str(source.get("userId", ""))
    text = safe_str(content.get("text", ""))

    if not user_id or not text:
        return "ok", 200

    try:
        handle_message(user_id, text)
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
