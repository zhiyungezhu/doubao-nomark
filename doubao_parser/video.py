import json
import re
import urllib.parse

import httpx

SHARE_API = "https://www.doubao.com/samantha/thread/share/snapshot/get"
MEDIA_API = "https://www.doubao.com/samantha/media/get_play_info"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
}

MEDIA_PARAMS = {
    "version_code": "20800",
    "language": "zh-CN",
    "device_platform": "web",
    "aid": "497858",
    "real_aid": "497858",
    "pkg_type": "release_version",
    "device_id": "",
    "pc_version": "2.51.7",
    "region": "",
    "sys_region": "",
    "samantha_web": "1",
    "use-olympus-account": "1",
    "web_tab_id": "",
}

DEFINITION_ORDER = ["8k", "4k", "2160p", "1080p", "720p", "540p", "480p", "360p", "auto"]


QIANWEN_API = "https://chat2-api.qianwen.com/api/v1/share/info"

QIANWEN_HEADERS = {
    "origin": "https://www.qianwen.com",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
}


def _best_quality(items: list) -> dict:
    best = items[0]
    best_meta = best.get("meta", {})
    best_def = best_meta.get("definition", "auto")
    best_score = DEFINITION_ORDER.index(best_def) if best_def in DEFINITION_ORDER else -1
    best_area = int(best_meta.get("width", 0)) * int(best_meta.get("height", 0))

    for item in items[1:]:
        meta = item.get("meta", {})
        defn = meta.get("definition", "auto")
        score = DEFINITION_ORDER.index(defn) if defn in DEFINITION_ORDER else -1
        area = int(meta.get("width", 0)) * int(meta.get("height", 0))
        if score < best_score or (score == best_score and area > best_area):
            best = item
            best_score = score
            best_area = area
    return best


async def doubao_video_parse(url: str, return_raw: bool = False):
    match = re.search(r"doubao\.com/thread/([a-zA-Z0-9]+)", url)
    if not match:
        raise ValueError("链接格式不正确，请使用豆包对话链接（包含 /thread/）")

    share_id = match.group(1)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SHARE_API, json={"share_id": share_id, "need_bot": False}, headers=HEADERS
            )
            result = response.json()
    except httpx.RequestError as e:
        raise ValueError(f"网络请求失败，请检查网络连接: {str(e)}")

    if result.get("code") != 0:
        raise KeyError("API返回异常，请确认链接是否有效")

    data = result.get("data", {})

    vids = []
    message_list = data.get("message_snapshot", {}).get("message_list", [])
    for message in message_list:
        for block in message.get("content_block", []):
            if block.get("block_type") != 2074:
                continue
            content_str = block.get("content", "")
            if not isinstance(content_str, str):
                continue
            try:
                parsed = json.loads(content_str)
            except json.JSONDecodeError:
                continue
            for creation in parsed.get("creations", []):
                video_data = creation.get("video")
                if video_data and video_data.get("vid"):
                    vids.append(video_data["vid"])

    if not vids:
        raise KeyError("未找到视频信息，请确认链接中是否包含视频")

    video_list = []
    for vid in vids:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    MEDIA_API,
                    params=MEDIA_PARAMS,
                    headers={**HEADERS, "origin": "https://www.doubao.com"},
                    json={"key": vid},
                )
                media_result = response.json()
        except httpx.RequestError as e:
            raise ValueError(f"网络请求失败，请检查网络连接: {str(e)}")

        if media_result.get("code") != 0:
            raise KeyError("视频解析失败，请检查链接是否有效")

        if return_raw:
            return media_result

        media_data = media_result.get("data", {})
        media_info = media_data.get("media_info", [])

        if not media_info:
            raise KeyError("未获取到视频播放地址")

        best = _best_quality(media_info)
        meta = best.get("meta", {})

        video_list.append(
            {
                "url": best.get("main_url", ""),
                "width": int(meta.get("width", 0)),
                "height": int(meta.get("height", 0)),
                "definition": meta.get("definition", "auto"),
                "duration": meta.get("duration", 0),
                "poster_url": media_data.get("poster_url", ""),
                "vid": vid,
            }
        )

    return video_list


async def yunque_video_parse(url: str, return_raw: bool = False):
    base_headers = {
        "origin": "https://xiaoyunque.jianying.com",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36",
    }
    post_headers = {**base_headers, "content-type": "application/json"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=base_headers, follow_redirects=True)
        query = urllib.parse.urlparse(str(resp.url)).query
        params = urllib.parse.parse_qs(query)

        json_data = {
            "query_params": {
                "content_type": "video",
                "home_input_type": "VIDEO_PART",
                "scene": "agent_tool",
                "share_campaign_key": "pippit_invite_fission",
                "share_id": params["share_id"][0],
                "share_sec_did": params["share_sec_did"][0],
                "share_sec_uid": params["share_sec_uid"][0],
            },
        }

        response = await client.post(
            "https://xiaoyunque.jianying.com/luckycat/cn/jianying/campaign/v1/pippit/share/landing_page",
            headers=post_headers,
            json=json_data,
        )
        result = response.json()

    if "data" not in result or "page_info" not in result["data"]:
        raise KeyError("无法获取视频播放信息，请检查链接是否有效")

    if return_raw:
        return result

    video_info = result["data"]["page_info"]["generate_page"]["item_info"]["video_info"][0]
    return [
        {
            "url": video_info["video_url"],
            "width": video_info["width"],
            "height": video_info["height"],
            "definition": f"{video_info['width']}p",
            "poster_url": video_info["cover_url"],
        }
    ]


async def qianwen_video_parse(url: str, return_raw: bool = False):
    if "qianwen.com/share/chat/" not in url:
        raise ValueError("链接格式不正确，请使用千问对话链接（包含 qianwen.com/share/chat/）")

    try:
        share_id = url.split("?")[0].rsplit("chat/", maxsplit=1)[-1]
        json_data = {
            "share_id": share_id,
            "biz_id": "ai_qwen",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(QIANWEN_API, json=json_data, headers=QIANWEN_HEADERS)
            result = response.json()
            if return_raw:
                return result
    except httpx.RequestError as e:
        raise ValueError(f"网络请求失败，请检查网络连接: {str(e)}")

    try:
        video_list = []
        record_list = result["data"]["session"]["record_list"]
        for record in record_list:
            response_messages = record["response_messages"]
            for message in response_messages:
                if message["mime_type"] == "multi_load/iframe" and message["status"] == "complete":
                    multi_load = message["meta_data"]["multi_load"]
                    for item in multi_load:
                        content = item.get("content", {})
                        display_list = content.get("display_list")
                        if not display_list:
                            continue
                        duration = content.get("duration", 0)
                        for display in display_list:
                            if display.get("type") != "generate_video":
                                continue
                            video = display.get("video")
                            download_video = display.get("download_video")
                            cover = display.get("cover", [])

                            if video and isinstance(video, list) and len(video) > 0:
                                video_info = video[0]
                            elif download_video and isinstance(download_video, list) and len(download_video) > 0:
                                video_info = download_video[0]
                            else:
                                continue

                            cover_item = cover[0] if cover and isinstance(cover, list) else {}
                            video_list.append(
                                {
                                    "url": video_info.get("url", ""),
                                    "width": int(cover_item.get("width", 0)),
                                    "height": int(cover_item.get("height", 0)),
                                    "definition": f"{cover_item.get('width', 0)}p",
                                    "poster_url": cover_item.get("url", ""),
                                    "duration": duration,
                                }
                            )
    except KeyError as e:
        print(f"Exception: {e}")
        raise KeyError("页面结构发生变化，无法解析视频数据")
    except json.JSONDecodeError:
        raise ValueError("页面数据格式错误，无法解析")

    if not video_list:
        raise KeyError("未找到视频信息，请确认链接中是否包含视频")

    return video_list


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(doubao_video_parse("https://www.doubao.com/thread/wf24eae5cccb73141")))
