import json
import logging
import re

import httpx

from .browser import fetch_page_html

logger = logging.getLogger(__name__)


def _extract_images_from_messages(messages):
    """Extract images from message list, supporting both old (creation_block)
    and new (attachment_block) formats."""
    images = []
    for message in messages:
        # New format: content_block (old) or content (new, contains JSON array)
        blocks = message.get("content_block") or []

        # Also try direct `content` field (newer format)
        if not blocks and message.get("content"):
            try:
                content_arr = json.loads(message["content"])
                if isinstance(content_arr, list):
                    blocks = content_arr
            except (json.JSONDecodeError, TypeError):
                blocks = []

        for block in blocks:
            if isinstance(block, str):
                try:
                    block = json.loads(block)
                except json.JSONDecodeError:
                    continue
            if not isinstance(block, dict):
                continue

            content = block.get("content", block)

            # New format: attachment_block
            attachments = content.get("attachment_block", {}).get("attachments")
            if attachments:
                for att in attachments:
                    img = att.get("image")
                    if not img:
                        continue
                    # Prefer image_ori (original quality), fallback to thumb/preview
                    ori = img.get("image_ori") or img.get("image_thumb") or img.get("image_preview")
                    if ori and ori.get("url"):
                        ori["url"] = ori["url"].replace("&amp;", "&")
                        # Add name if available
                        ori["name"] = img.get("name", "")
                        images.append(ori)
                continue

            # Old format: creation_block
            creations = content.get("creation_block", {}).get("creations")
            if not creations:
                # Try content_v2 or content directly
                content_v2 = block.get("content_v2") or block.get("content")
                if content_v2 and isinstance(content_v2, str):
                    try:
                        parsed = json.loads(content_v2)
                        creations = parsed.get("creation_block", {}).get("creations")
                    except json.JSONDecodeError:
                        pass

            if creations:
                for img_data in creations:
                    img = img_data.get("image")
                    if not img:
                        continue
                    raw = img.get("image_ori_raw")
                    if raw and raw.get("url"):
                        raw["url"] = raw["url"].replace("&amp;", "&")
                        images.append(raw)

    return images


def _parse_html_for_images(html_str: str, return_raw: bool = False) -> list | dict | None:
    """Try all methods to extract image data from HTML.
    Returns image list, raw data dict, or None if all methods fail."""
    # Method 1: Try modern-run-window-fn format (current)
    match = re.search(
        r'data-script-src="modern-run-window-fn".*?data-fn-args="([^"]+)"',
        html_str,
        re.DOTALL,
    )
    if match:
        try:
            raw = match.group(1).replace("&quot;", '"')
            parsed = json.loads(raw)
            route_data = parsed[1]
            fn_args = route_data[0].get("routerDataFnArgs", [])
            if fn_args:
                actual_data = json.loads(fn_args[0])
                if return_raw:
                    return actual_data
                messages = actual_data.get("data", {}).get("message_snapshot", {}).get("message_list", [])
                return _extract_images_from_messages(messages)
        except (json.JSONDecodeError, (KeyError, IndexError, TypeError)):
            pass

    # Method 2: Try _ROUTER_DATA format (alternative inline data)
    match = re.search(r"_ROUTER_DATA\s*=\s*(\{.+?\});", html_str, re.DOTALL)
    if match:
        try:
            router_data = json.loads(match.group(1))
            loader_data = router_data.get("loaderData", {})
            layout = loader_data.get("thread_layout", {})
            if layout.get("data", {}).get("message_snapshot"):
                messages = layout["data"]["message_snapshot"]["message_list"]
                return _extract_images_from_messages(messages)
        except (json.JSONDecodeError, (KeyError, IndexError, TypeError)):
            pass

    # Method 3: Try modern-run-router-data-fn format (older)
    match = re.search(
        r'data-script-src="modern-run-router-data-fn".*?data-fn-args="([^"]+)"',
        html_str,
        re.DOTALL,
    )
    if match:
        try:
            raw = match.group(1).replace("&quot;", '"')
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("data"):
                messages = parsed["data"]["message_snapshot"]["message_list"]
                return _extract_images_from_messages(messages)
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and item.get("data"):
                        messages = item["data"]["message_snapshot"]["message_list"]
                        return _extract_images_from_messages(messages)
        except (json.JSONDecodeError, (KeyError, IndexError, TypeError)):
            pass

    # Method 4: Try modern-inline format with _ROUTER_DATA
    match = re.search(
        r'data-script-src="modern-inline".*?_ROUTER_DATA\s*=\s*(\{.+?\});',
        html_str,
        re.DOTALL,
    )
    if match:
        try:
            router_data = json.loads(match.group(1))
            loader_data = router_data.get("loaderData", {})
            layout = loader_data.get("thread_layout", {})
            if layout.get("data", {}).get("message_snapshot"):
                messages = layout["data"]["message_snapshot"]["message_list"]
                return _extract_images_from_messages(messages)
        except (json.JSONDecodeError, (KeyError, IndexError, TypeError)):
            pass

    return None


async def doubao_image_parse(url: str, return_raw: bool = False):
    if "doubao.com/thread/" not in url:
        raise ValueError("链接格式不正确，请使用豆包对话链接（包含 /thread/）")

    headers = {
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
    }

    html_str = None

    # Method A: Try direct HTTP fetch first (works for SSR pages)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            html_str = response.text
    except httpx.RequestError as e:
        raise ValueError(f"网络请求失败，请检查网络连接: {str(e)}")

    result = _parse_html_for_images(html_str, return_raw)
    if result is not None:
        return result

    # Method B: Try Playwright (handles CSR pages by executing JS)
    logger.info("Direct fetch returned no data, trying Playwright for CSR page...")
    pw_html = await fetch_page_html(url)
    if pw_html:
        result = _parse_html_for_images(pw_html, return_raw)
        if result is not None:
            return result

    raise KeyError("无法解析页面数据，请确认链接是否有效")


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

    print(asyncio.run(doubao_image_parse("https://www.doubao.com/thread/xfdf0eacab48586a2913c5a0122687146")))
