import json
import re

import httpx

API_URL = "https://www.doubao.com/samantha/thread/share/snapshot/get"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
}


async def doubao_image_parse(url: str, return_raw: bool = False):
    match = re.search(r"doubao\.com/thread/([a-zA-Z0-9]+)", url)
    if not match:
        raise ValueError("链接格式不正确，请使用豆包对话链接（包含 /thread/）")

    share_id = match.group(1)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                json={"share_id": share_id, "need_bot": False},
                headers=HEADERS,
            )
            result = response.json()
    except httpx.RequestError as e:
        raise ValueError(f"网络请求失败，请检查网络连接: {str(e)}")

    if result.get("code") != 0:
        raise KeyError("API返回异常，请确认链接是否有效")

    data = result.get("data", {})
    if return_raw:
        return data

    image_list = []
    message_list = data.get("message_snapshot", {}).get("message_list", [])
    for message in message_list:
        content_block = message.get("content_block", [])
        for block in content_block:
            if block.get("block_type") != 2074:
                continue
            content_str = block.get("content", "")
            if not isinstance(content_str, str):
                continue
            try:
                parsed = json.loads(content_str)
            except json.JSONDecodeError:
                continue
            creations = parsed.get("creations", [])
            for creation in creations:
                image_raw = creation.get("image", {}).get("image_ori_raw")
                if image_raw:
                    image_raw["url"] = image_raw.get("url", "").replace("&amp;", "&")
                    image_list.append(image_raw)

    return image_list


async def qianwen_image_parse(url: str, return_raw: bool = False):
    if "qianwen.com/share/chat/" not in url:
        raise ValueError("链接格式不正确，请使用豆包对话链接（包含 qianwen.com/share/chat/）")

    headers = {
        "origin": "https://www.qianwen.com",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    }

    try:
        share_id = url.split("?")[0].rsplit("chat/", maxsplit=1)[-1]
        json_data = {
            "share_id": share_id,
            "biz_id": "ai_qwen",
        }

        async with httpx.AsyncClient() as client:
            api = "https://chat2-api.qianwen.com/api/v1/share/info"
            response = await client.post(api, json=json_data, headers=headers)
            json_data = response.json()
            if return_raw:
                return json_data
    except httpx.RequestError as e:
        raise ValueError(f"网络请求失败，请检查网络连接: {str(e)}")

    try:
        image_list = []
        record_list = json_data["data"]["session"]["record_list"]
        for record in record_list:
            response_messages = record["response_messages"]
            for message in response_messages:
                if message["mime_type"] == "multi_load/iframe" and message["status"] == "complete":
                    multi_load = message["meta_data"]["multi_load"]
                    for item in multi_load:
                        display_list = item["content"]["display_list"]
                        for i in display_list:
                            image_info = i["image"][0]
                            image_list.append(image_info)
    except KeyError as e:
        print(f"Exception: {e}")
        raise KeyError("页面结构发生变化，无法解析图片数据")
    except json.JSONDecodeError:
        raise ValueError("页面数据格式错误，无法解析")

    return image_list


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(doubao_image_parse("https://www.doubao.com/thread/w4ef5e5b8b691bb5c")))
