def make_item_row(row):
    spec_code = safe_str(row.get("스펙코드", ""))[:26] or "-"
    desc = safe_str(row.get("간단설명", ""))[:38] or "설명 없음"
    pdf_link = safe_str(row.get("PDF링크", ""))

    left_box = {
        "type": "box",
        "layout": "vertical",
        "flex": 8,
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
            "flex": 2,
            "justifyContent": "center",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#9B8CFF",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "보기",
                        "uri": pdf_link
                    }
                }
            ]
        }
    else:
        right_component = {
            "type": "box",
            "layout": "vertical",
            "flex": 2,
            "justifyContent": "center",
            "contents": [
                {
                    "type": "text",
                    "text": "링크 없음",
                    "size": "xs",
                    "color": "#999999",
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
                "margin": "none",
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
