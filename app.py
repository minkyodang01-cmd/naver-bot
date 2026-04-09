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
