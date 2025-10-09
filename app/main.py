import json
import time
import requests
import datetime
import urllib.parse
from pathlib import Path 
from typing import Union
import asyncio 
from fastapi import FastAPI, Response, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool 

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates")) 

class APITimeoutError(Exception): pass
def getRandomUserAgent(): return {'User-Agent': 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.61 Safari/537.36'}
def isJSON(json_str):
    try: json.loads(json_str); return True
    except json.JSONDecodeError: return False

# Global Configuration
max_time = 10.0
max_api_wait_time = (3.0, 5.0)
failed = "Load Failed"
MAX_RETRIES = 4   # ストリームAPIリトライ回数
RETRY_DELAY = 1.0 # ストリームAPIリトライ待機時間 (秒)

# 新規追加: /api/edu で使用する外部ストリームAPIのURL
EDU_STREAM_API_BASE_URL = "https://siawaseok.duckdns.org/api/stream/" 


invidious_api_data = {
    'video': [
        'https://yt.omada.cafe/',
        'https://inv.perditum.com/',
        'https://iv.melmac.space/', 
    ], 
    'playlist': [
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.melmac.space/',
    ], 
    'search': [
        'https://invid-api.poketube.fun/',
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.melmac.space/',
    ], 
    'channel': [
        'https://invid-api.poketube.fun/',
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.melmac.space/',
    ], 
    'comments': [
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.melmac.space/',
    ]
}

class InvidiousAPI:
    def __init__(self):
        self.all = invidious_api_data
        self.video = list(self.all['video']); 
        self.playlist = list(self.all['playlist']);
        self.search = list(self.all['search']); 
        self.channel = list(self.all['channel']);
        self.comments = list(self.all['comments']); 
        self.check_video = False

def requestAPI(path, api_urls):
    """
    Sequentially attempts API requests using the provided list of URLs.
    Fails over to the next URL on connection error or non-OK response.
    """
    starttime = time.time()
    
    apis_to_try = api_urls
    
    for api in apis_to_try:
        if time.time() - starttime >= max_time - 1:
            break
            
        try:
            res = requests.get(api + 'api/v1' + path, headers=getRandomUserAgent(), timeout=max_api_wait_time)
            
            if res.status_code == requests.codes.ok and isJSON(res.text):
                return res.text
            
        except requests.exceptions.RequestException:
            continue
            
    # APIFailoverがすべて失敗した場合、例外を投げる
    raise APITimeoutError("All available API instances failed to respond.")

def getStreamData(videoid):
    """カスタムAPIから動画ストリームデータを取得する"""
    api_url = f"https://siawaseok.duckdns.org/api/stream/{videoid}/type2"
    try:
        res = requests.get(api_url, headers=getRandomUserAgent(), timeout=max_api_wait_time)
        res.raise_for_status() # HTTPエラーを確認 (4xx, 5xx)
        if isJSON(res.text):
            return json.loads(res.text)
    except requests.exceptions.RequestException as e:
        pass
    except json.JSONDecodeError:
        pass
    
    return None

def getEduKey():
    """
    KahootのメディアAPIからYouTubeのキーを取得する
    URL: https://apis.kahoot.it/media-api/youtube/key
    """
    api_url = "https://apis.kahoot.it/media-api/youtube/key"
    try:
        res = requests.get(api_url, headers=getRandomUserAgent(), timeout=max_api_wait_time)
        res.raise_for_status() # HTTPエラーを確認
        
        if isJSON(res.text):
            data = json.loads(res.text)
            return data.get("key")
        
    except requests.exceptions.RequestException as e:
        print(f"Kahoot API request failed: {e}")
    except json.JSONDecodeError:
        print("Kahoot API returned non-JSON data.")
    
    return None

def formatSearchData(data_dict, failed="Load Failed"):
    if data_dict["type"] == "video": 
        return {"type": "video", "title": data_dict.get("title", failed), "id": data_dict.get("videoId", failed), "author": data_dict.get("author", failed), "published": data_dict.get("publishedText", failed), "length": str(datetime.timedelta(seconds=data_dict.get("lengthSeconds", 0))), "view_count_text": data_dict.get("viewCountText", failed)}
    elif data_dict["type"] == "playlist": 
        return {"type": "playlist", "title": data_dict.get("title", failed), "id": data_dict.get('playlistId', failed), "thumbnail": data_dict.get("playlistThumbnail", failed), "count": data_dict.get("videoCount", failed)}
    elif data_dict["type"] == "channel":
        thumbnail_url = data_dict.get('authorThumbnails', [{}])[-1].get('url', failed)
        thumbnail = "https://" + thumbnail_url.lstrip("http://").lstrip("//") if not thumbnail_url.startswith("https") else thumbnail_url
        return {"type": "channel", "author": data_dict.get("author", failed), "id": data_dict.get("authorId", failed), "thumbnail": thumbnail}
    return {"type": "unknown", "data": data_dict}

async def getVideoData(videoid):
    t_text = await run_in_threadpool(requestAPI, f"/videos/{urllib.parse.quote(videoid)}", invidious_api.video)
    t = json.loads(t_text)
    recommended_videos = t.get('recommendedvideo') or t.get('recommendedVideos') or []
    
    # InvidiousのフォールバックURL
    fallback_videourls = list(reversed([i["url"] for i in t["formatStreams"]]))[:2]
    
    # データを整理して返す
    return [{
        'video_urls': fallback_videourls, 
        'description_html': t["descriptionHtml"].replace("\n", "<br>"), 'title': t["title"],
        'length_text': str(datetime.timedelta(seconds=t["lengthSeconds"])), 'author_id': t["authorId"], 'author': t["author"], 'author_thumbnails_url': t["authorThumbnails"][-1]["url"], 'view_count': t["viewCount"], 'like_count': t["likeCount"], 'subscribers_count': t["subCountText"]
    }, [
        {"video_id": i["videoId"], "title": i["title"], "author_id": i["authorId"], "author": i["author"], "length_text": str(datetime.timedelta(seconds=i["lengthSeconds"])), "view_count_text": i["viewCountText"]}
        for i in recommended_videos
    ]]
    
async def getSearchData(q, page):
    datas_text = await run_in_threadpool(requestAPI, f"/search?q={urllib.parse.quote(q)}&page={page}&hl=jp", invidious_api.search)
    datas_dict = json.loads(datas_text)
    return [formatSearchData(data_dict) for data_dict in datas_dict]

async def getTrendingData(region: str):
    path = f"/trending?region={region}&hl=jp"
    datas_text = await run_in_threadpool(requestAPI, path, invidious_api.search)
    datas_dict = json.loads(datas_text)
    return [formatSearchData(data_dict) for data_dict in datas_dict if data_dict.get("type") == "video"]

async def getChannelData(channelid):
    t = {}
    try:
        # 外部APIを呼び出す
        t_text = await run_in_threadpool(requestAPI, f"/channels/{urllib.parse.quote(channelid)}", invidious_api.channel)
        t = json.loads(t_text)

        # 最新動画がない場合、APIデータは無効とみなし、tをリセットして次の処理に進む
        latest_videos_check = t.get('latestvideo') or t.get('latestVideos')
        if not latest_videos_check:
            print(f"API returned no latest videos for channel {channelid}. Treating as failure.")
            t = {}

    except APITimeoutError:
        print(f"Error: Invidious API timeout for channel {channelid}. Using default data.")
    except json.JSONDecodeError:
        print(f"Error: JSON decode failed for channel {channelid}. Using default data.")
    except Exception as e:
        print(f"An unexpected error occurred while fetching channel data for {channelid}: {e}")
        
    
    # データを取得（失敗時は空リストまたはデフォルト値）
    latest_videos = t.get('latestvideo') or t.get('latestVideos') or []
    
    # チャンネルアイコンの安全な取得
    author_thumbnails = t.get("authorThumbnails", [])
    author_icon_url = author_thumbnails[-1].get("url", failed) if author_thumbnails else failed

    # チャンネルバナーの安全な取得とURLエンコード
    author_banner_url = ''
    author_banners = t.get('authorBanners', [])
    if author_banners and author_banners[0].get("url"):
        author_banner_url = urllib.parse.quote(author_banners[0]["url"], safe="-_.~/:")
    
    
    # データを整理して返す (tが空でもすべてのキーが存在することを保証)
    return [[
        {"type":"video", "title": i.get("title", failed), "id": i.get("videoId", failed), "author": t.get("author", failed), "published": i.get("publishedText", failed), "view_count_text": i.get('viewCountText', failed), "length_str": str(datetime.timedelta(seconds=i.get("lengthSeconds", 0)))}
        for i in latest_videos
    ], {
        "channel_name": t.get("author", "チャンネル情報取得失敗"), 
        "channel_icon": author_icon_url, 
        "channel_profile": t.get("descriptionHtml", "このチャンネルのプロフィール情報は見つかりませんでした。"),
        "author_banner": author_banner_url,
        "subscribers_count": t.get("subCount", failed), 
        "tags": t.get("tags", [])
    }]

async def getPlaylistData(listid, page):
    t_text = await run_in_threadpool(requestAPI, f"/playlists/{urllib.parse.quote(listid)}?page={urllib.parse.quote(str(page))}", invidious_api.playlist)
    t = json.loads(t_text)["videos"]
    return [{"title": i["title"], "id": i["videoId"], "authorId": i["authorId"], "author": i["author"], "type": "video"} for i in t]

async def getCommentsData(videoid):
    t_text = await run_in_threadpool(requestAPI, f"/comments/{urllib.parse.quote(videoid)}", invidious_api.comments)
    t = json.loads(t_text)["comments"]
    return [{"author": i["author"], "authoricon": i["authorThumbnails"][-1]["url"], "authorid": i["authorId"], "body": i["contentHtml"].replace("\n", "<br>")} for i in t]

# 新規追加: /api/edu から呼び出す外部APIヘルパー関数
async def fetch_embed_url_from_external_api(videoid: str) -> str:
    """
    外部ストリームAPIを呼び出し、埋め込みURLを取得する（requestsは同期のためスレッドプールで実行）
    """
    
    target_url = f"{EDU_STREAM_API_BASE_URL}{videoid}"
    
    def sync_fetch():
        res = requests.get(
            target_url, 
            headers=getRandomUserAgent(), 
            timeout=max_api_wait_time
        )
        res.raise_for_status()
        data = res.json()
        
        embed_url = data.get("url")
        if not embed_url:
            raise ValueError("External API response is missing the 'url' field.")
            
        return embed_url

    return await run_in_threadpool(sync_fetch)


# FastAPI Application
app = FastAPI()
invidious_api = InvidiousAPI() 

app.mount(
    "/static", 
    StaticFiles(directory=str(BASE_DIR / "static")), 
    name="static"
)


# --- API Routes ---

@app.get("/api/stream/{videoid}")
async def get_stream_url(videoid: str):
    video_data = None
    
    while True:
        data = await run_in_threadpool(getStreamData, videoid)
        
        if data:
            video_data = data
            break
        
        await asyncio.sleep(RETRY_DELAY) 

    stream_url = ''
    
    if 'm3u8' in video_data and '1080p' in video_data['m3u8']:
        stream_url = video_data['m3u8']['1080p']['url'].get('url', '')

    elif 'videoStreams' in video_data and video_data['videoStreams']:
        video_streams = video_data['videoStreams']
        if len(video_streams) >= 5:
            stream_url = video_streams[4].get('url', '')
    
    elif 'videourl' in video_data and video_data['videourl']:
        # '1080p' in video_data['videourl'] のチェックを修正し、キーの存在を確認
        if '1080p' in video_data['videourl']:
            stream_url = video_data['videourl']['1080p']['video'].get('url', '')
    
    
    if stream_url:
        return {"videoid": videoid, "stream_url": stream_url}
    else:
        return Response(content='{"error": "Stream URL not found (HLS 1080p or fallback) in retrieved data"}', media_type="application/json", status_code=404)

@app.get("/api/edu")
async def get_edu_key_route():
    """
    KahootのYouTubeキーを取得し、JSONで返す
    """
    key = await run_in_threadpool(getEduKey)
    
    if key:
        return {"key": key}
    else:
        return Response(content='{"error": "Failed to retrieve key from Kahoot API"}', media_type="application/json", status_code=500)

# 新規追加: /api/edu/{videoid} ルート (全画面埋め込み)
@app.get('/api/edu/{videoid}', response_class=HTMLResponse)
async def embed_edu_video(request: Request, videoid: str, proxy: Union[str] = Cookie(None)):
    """
    /api/edu/<videoid> ルート。
    外部APIからストリームURLを取得し、そのURLを埋め込んだ全画面表示用の HTML ページを返します。
    """
    embed_url = None
    try:
        # 外部APIから埋め込みURLを取得
        embed_url = await fetch_embed_url_from_external_api(videoid)
        
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        if status_code == 404:
            return Response(f"Stream URL for videoid '{videoid}' not found.", status_code=404)
        print(f"Error calling external API (HTTP {status_code}): {e}")
        return Response("Failed to retrieve stream URL from external service (HTTP Error).", status_code=503)
        
    except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as e:
        print(f"Error calling external API: {e}")
        return Response("Failed to retrieve stream URL from external service (Connection/Format Error).", status_code=503)

    # 取得した埋め込み URL をテンプレートに渡し、HTML をレンダリングして返す
    return templates.TemplateResponse(
        'embed.html', 
        {
            "request": request, 
            "embed_url": embed_url,
            "videoid": videoid,
            "proxy": proxy
        }
    )


# --- Frontend Routes ---

@app.get('/', response_class=HTMLResponse)
async def home(request: Request, proxy: Union[str] = Cookie(None)):
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "proxy": proxy
    })

@app.get('/watch', response_class=HTMLResponse)
async def video(v:str, request: Request, proxy: Union[str] = Cookie(None)):
    video_data = await getVideoData(v)
    
    high_quality_url = ""
    
    return templates.TemplateResponse('video.html', {
        "request": request, "videoid": v, "videourls": video_data[0]['video_urls'], 
        "high_quality_url": high_quality_url,
        "description": video_data[0]['description_html'], "video_title": video_data[0]['title'], "author_id": video_data[0]['author_id'], "author_icon": video_data[0]['author_thumbnails_url'], "author": video_data[0]['author'], "length_text": video_data[0]['length_text'], "view_count": video_data[0]['view_count'], "like_count": video_data[0]['like_count'], "subscribers_count": video_data[0]['subscribers_count'], "recommended_videos": video_data[1], "proxy":proxy
    })

@app.get("/search", response_class=HTMLResponse)
async def search(q:str, request: Request, page:Union[int, None]=1, proxy: Union[str] = Cookie(None)):
    search_results = await getSearchData(q, page)
    return templates.TemplateResponse("search.html", {"request": request, "results":search_results, "word":q, "next":f"/search?q={q}&page={page + 1}", "proxy":proxy})

@app.get("/hashtag/{tag}")
async def hashtag_search(tag:str):
    return RedirectResponse(f"/search?q={tag}", status_code=302)

@app.get("/channel/{channelid}", response_class=HTMLResponse)
async def channel(channelid:str, request: Request, proxy: Union[str] = Cookie(None)):
    t = await getChannelData(channelid)
    return templates.TemplateResponse("channel.html", {"request": request, "results": t[0], "channel_name": t[1]["channel_name"], "channel_icon": t[1]["channel_icon"], "channel_profile": t[1]["channel_profile"], "cover_img_url": t[1]["author_banner"], "subscribers_count": t[1]["subscribers_count"], "tags": t[1]["tags"], "proxy": proxy})

@app.get("/playlist", response_class=HTMLResponse)
async def playlist(list:str, request: Request, page:Union[int, None]=1, proxy: Union[str] = Cookie(None)):
    playlist_data = await getPlaylistData(list, str(page))
    return templates.TemplateResponse("search.html", {"request": request, "results": playlist_data, "word": "", "next": f"/playlist?list={list}&page={page + 1}", "proxy": proxy})

@app.get("/comments", response_class=HTMLResponse)
async def comments(request: Request, v:str):
    comments_data = await getCommentsData(v)
    return templates.TemplateResponse("comments.html", {"request": request, "comments": comments_data})

@app.get("/thumbnail")
def thumbnail(v:str):
    return Response(content = requests.get(f"https://img.youtube.com/vi/{v}/0.jpg").content, media_type="image/jpeg")

@app.get("/suggest")
def suggest(keyword:str):
    res_text = requests.get("http://www.google.com/complete/search?client=youtube&hl=ja&ds=yt&q=" + urllib.parse.quote(keyword), headers=getRandomUserAgent()).text
    return [i[0] for i in json.loads(res_text[19:-1])[1]]
