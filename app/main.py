import json
import time
import requests
import datetime
import urllib.parse
from pathlib import Path 
from typing import Union
from fastapi import FastAPI, Response, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool 
# ytpbのインポートは削除済み

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

# 緊急フォールバックAPIの定義
FALLBACK_API = "https://siawaseok.f5.si/api/2/streams/"

invidious_api_data = {
    'video': [
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
        'https://invidious.ducks.party/',
        'https://super8.absturztau.be/',
        'https://invidious.nikkosphere.com/',
        'https://invidious.ducks.party/',
        'https://yt.omada.cafe/',
        'https://iv.melmac.space/',
    ], 
    'channel': [
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
    Raises APITimeoutError if all APIs fail.
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
            
    raise APITimeoutError("All available API instances failed to respond.")

def formatSearchData(data_dict, failed="Load Failed"):
    if data_dict["type"] == "video": 
        return {"type": "video", 
                "title": data_dict.get("title", failed), 
                "id": data_dict.get("videoId", failed), 
                "author": data_dict.get("author", failed), 
                "published": data_dict.get("publishedText", failed), 
                "length": str(datetime.timedelta(seconds=data_dict.get("lengthSeconds", 0))), 
                "view_count_text": data_dict.get("viewCountText", failed)}
    elif data_dict["type"] == "playlist": 
        return {"type": "playlist", "title": data_dict.get("title", failed), "id": data_dict.get('playlistId', failed), "thumbnail": data_dict.get("playlistThumbnail", failed), "count": data_dict.get("videoCount", failed)}
    elif data_dict["type"] == "channel":
        thumbnail_url = data_dict.get('authorThumbnails', [{}])[-1].get('url', failed)
        thumbnail = "https://" + thumbnail_url.lstrip("http://").lstrip("//") if not thumbnail_url.startswith("https") else thumbnail_url
        return {"type": "channel", "author": data_dict.get("author", failed), "id": data_dict.get("authorId", failed), "thumbnail": thumbnail}
    return {"type": "unknown", "data": data_dict}

def get_fallback_video_data(videoid):
    """緊急APIからtitleとitag=18の動画URLを取得する"""
    try:
        res = requests.get(FALLBACK_API + videoid, headers=getRandomUserAgent(), timeout=max_api_wait_time)
        if res.status_code != requests.codes.ok or not isJSON(res.text):
            return None, None

        data = res.json()
        title = data.get("title", "タイトル不明")
        
        # formatsリストからitagが18のURLを見つける
        formats = data.get("formats", [])
        itag_18_url = None
        for fmt in formats:
            # itagが18であることを厳密にチェック
            if str(fmt.get("itag")) == "18":
                itag_18_url = fmt.get("url")
                break
        
        return title, itag_18_url
        
    except requests.exceptions.RequestException as e:
        print(f"Fallback API error for {videoid}: {e}")
        return None, None

async def getVideoData(videoid):
    failed = "Load Failed"
    
    # requestAPIは失敗した場合APITimeoutErrorをraiseする
    t_text = await run_in_threadpool(requestAPI, f"/videos/{urllib.parse.quote(videoid)}", invidious_api.video)
    t = json.loads(t_text)

    video_urls = []
    
    # Invidiousが通常のストリームURLを返している場合、それを採用
    if t.get("formatStreams"):
        video_urls = list(reversed([i["url"] for i in t["formatStreams"]]))[:2]
    
    length_text = str(datetime.timedelta(seconds=t.get("lengthSeconds", 0)))
    view_count = t.get("viewCount", failed)
        
    recommended_videos = t.get('recommendedvideo') or t.get('recommendedVideos') or []
    
    return [{
        'video_urls': video_urls,
        'description_html': t.get("descriptionHtml", failed).replace("\n", "<br>"), 
        'title': t.get("title", failed),
        'length_text': length_text, 
        'author_id': t.get("authorId", failed), 
        'author': t.get("author", failed), 
        'author_thumbnails_url': t.get("authorThumbnails", [{}])[-1].get("url", failed), 
        'view_count': view_count, 
        'like_count': t.get("likeCount", failed), 
        'subscribers_count': t.get("subCountText", failed)
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
    t_text = await run_in_threadpool(requestAPI, f"/channels/{urllib.parse.quote(channelid)}", invidious_api.channel)
    t = json.loads(t_text)
    latest_videos = t.get('latestvideo') or t.get('latestVideos') or []
    return [[
        {"type":"video", "title": i["title"], "id": i["videoId"], "author": t["author"], "published": i["publishedText"], "view_count_text": i['viewCountText'], "length_str": str(datetime.timedelta(seconds=i["lengthSeconds"]))}
        for i in latest_videos
    ], {
        "channel_name": t.get("author", failed), "channel_icon": t.get("authorThumbnails", [{}])[-1].get("url", failed), "channel_profile": t.get("descriptionHtml", failed),
        "author_banner": urllib.parse.quote(t.get("authorBanners", [{}])[0].get("url", ""), safe="-_.~/:") if 'authorBanners' in t and len(t['authorBanners']) else '',
        "subscribers_count": t.get("subCount", failed), "tags": t.get("tags", [])
    }]

async def getPlaylistData(listid, page):
    t_text = await run_in_threadpool(requestAPI, f"/playlists/{urllib.parse.quote(listid)}?page={urllib.parse.quote(str(page))}", invidious_api.playlist)
    t = json.loads(t_text)["videos"]
    return [{"title": i["title"], "id": i["videoId"], "authorId": i["authorId"], "author": i["author"], "type": "video"} for i in t]

async def getCommentsData(videoid):
    t_text = await run_in_threadpool(requestAPI, f"/comments/{urllib.parse.quote(videoid)}?hl=jp", invidious_api.comments)
    t = json.loads(t_text)["comments"]
    return [{"author": i["author"], "authoricon": i["authorThumbnails"][-1]["url"], "authorid": i["authorId"], "body": i["contentHtml"].replace("\n", "<br>")} for i in t]


# FastAPI Application
app = FastAPI()
invidious_api = InvidiousAPI() 

app.mount(
    "/static", 
    StaticFiles(directory=str(BASE_DIR / "static")), 
    name="static"
)


@app.get('/', response_class=HTMLResponse)
async def home(request: Request, proxy: Union[str] = Cookie(None)):
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "proxy": proxy
    })

# /watch ルート (プライマリ再生ルート)
@app.get('/watch', response_class=HTMLResponse)
async def video(v:str, request: Request, proxy: Union[str] = Cookie(None)):
    try:
        video_data = await getVideoData(v)
        return templates.TemplateResponse('video.html', {
            "request": request, "videoid": v, "videourls": video_data[0]['video_urls'], "description": video_data[0]['description_html'], "video_title": video_data[0]['title'], "author_id": video_data[0]['author_id'], "author_icon": video_data[0]['author_thumbnails_url'], "author": video_data[0]['author'], "length_text": video_data[0]['length_text'], "view_count": video_data[0]['view_count'], "like_count": video_data[0]['like_count'], "subscribers_count": video_data[0]['subscribers_count'], "recommended_videos": video_data[1], "proxy":proxy
        })
    except APITimeoutError:
        # Invidious API失敗時はエラーメッセージと緊急再生ルートへのリンクを提示
        return HTMLResponse(content=f"<html><body><h1>APIエラー</h1><p>動画情報の取得に失敗しました。緊急再生を試す場合は <a href='/w?v={v}'>/w?v={v}</a> を利用してください。</p></body></html>", status_code=503)

# ★ 新規追加: /w ルート (緊急フォールバック再生ルート)
@app.get('/w', response_class=HTMLResponse)
async def sub_video(v:str, request: Request):
    # 緊急フォールバックAPIを試行 (ブロッキング処理)
    title, url = await run_in_threadpool(get_fallback_video_data, v)
    
    # subvideo.htmlをレンダリング
    return templates.TemplateResponse('subvideo.html', {
        "request": request, 
        "title": title or "タイトル不明", 
        "url": url,
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
    return templates.TemplateResponse("channel.html", {"request": request, "results": t[0], "channel_name": t[1]["channel_name"], "channel_icon": t[1]["channel_icon"], "channel_profile": t[1]["descriptionHtml"], "cover_img_url": t[1]["author_banner"], "subscribers_count": t[1]["subscribers_count"], "proxy": proxy})

@app.get("/playlist", response_class=HTMLResponse)
async def playlist(list_id:str, request: Request, page:Union[int, None]=1, proxy: Union[str] = Cookie(None)):
    playlist_data = await getPlaylistData(list_id, str(page))
    return templates.TemplateResponse("search.html", {"request": request, "results": playlist_data, "word": "", "next": f"/playlist?list={list_id}&page={page + 1}", "proxy": proxy})

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
