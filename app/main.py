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
import logging # Logging module added

# Logging setup initialization
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates")) 

class APITimeoutError(Exception): pass
def getRandomUserAgent(): return {'User-Agent': 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.61 Safari/537.36'}
def isJSON(json_str):
    try: json.loads(json_str); return True
    except json.JSONDecodeError: return False

# Global Configuration (STRICT TIMEOUTS APPLIED)
max_time = 5.0  # Reduced to 5.0 seconds total attempt time
max_api_wait_time = (1.5, 3.0) # Reduced per-request connection/read time
failed = "Load Failed"

invidious_api_data = {
    'video': [
        'https://yt.omada.cafe/',
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

# Function with detailed logging
def requestAPI(path, api_urls):
    """
    Sequentially attempts API requests using the provided list of URLs.
    Fails over to the next URL on connection error or non-OK response.
    """
    starttime = time.time()
    logger.info(f"--- Invidious API Request Started for path: {path} ---")
    
    apis_to_try = api_urls
    
    for api in apis_to_try:
        current_url = api + 'api/v1' + path
        if time.time() - starttime >= max_time - 1:
            logger.warning(f"Total time limit (max_time - 1 = {max_time - 1:.1f}s) approaching. Aborting further attempts.")
            break
            
        try:
            logger.info(f"Attempting Invidious instance: {current_url}")
            res = requests.get(current_url, headers=getRandomUserAgent(), timeout=max_api_wait_time)
            
            if res.status_code == requests.codes.ok and isJSON(res.text):
                logger.info(f"SUCCESS: API request to {api} completed in {time.time() - starttime:.2f}s.")
                return res.text
            else:
                logger.warning(f"FAIL: {api} returned status {res.status_code} or non-JSON content. Moving to next instance.")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"ERROR: Request to {api} failed due to exception: {type(e).__name__}. Moving to next instance.")
            continue
            
    logger.error(f"FAILURE: All available Invidious API instances failed to respond after {time.time() - starttime:.2f}s.")
    raise APITimeoutError("All available API instances failed to respond.")

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
    logger.info(f"Calling Invidious for video metadata: {videoid}")
    t_text = await run_in_threadpool(requestAPI, f"/videos/{urllib.parse.quote(videoid)}", invidious_api.video)
    t = json.loads(t_text)
    recommended_videos = t.get('recommendedvideo') or t.get('recommendedVideos') or []
    return [{
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


# Function with detailed logging and specific timeout
async def getPrimaryStreamUrl(videoid):
    """
    Fetches the primary video stream URL from the user-specified external API (siawaseok.f5.si).
    """
    api_url = f"https://siawaseok.f5.si/api/2/streams/{urllib.parse.quote(videoid)}"
    logger.info(f"--- Stream API Request Started for video: {videoid} ---")
    
    # Specific, strict timeout for the new stream API
    STREAM_API_TIMEOUT = (3.0, 2.0)

    def fetch_stream_url_sync():
        try:
            logger.info(f"Attempting Stream API URL: {api_url}")
            res = requests.get(api_url, headers=getRandomUserAgent(), timeout=STREAM_API_TIMEOUT)
            
            if res.status_code == requests.codes.ok and isJSON(res.text):
                data = json.loads(res.text)
                
                # Extract 'url' key
                result_url = None
                if isinstance(data, list) and data:
                    result_url = data[0].get("url")
                elif isinstance(data, dict):
                    result_url = data.get("url")
                
                if result_url:
                    logger.info(f"SUCCESS: Stream URL found. Starts with: {result_url[:40]}...")
                    return result_url
                else:
                    logger.error(f"ERROR: Stream API returned JSON but no 'url' key was found.")
                    return None
            else:
                logger.error(f"ERROR: Stream API returned status {res.status_code} or non-JSON content.")
                return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"ERROR: Stream API request failed due to exception (Timeout/Connection): {type(e).__name__}")
            return None

    # Run in thread pool
    result_url = await run_in_threadpool(fetch_stream_url_sync)
    
    final_url = result_url if result_url else failed
    logger.info(f"--- Stream API Request Finished. Result: {final_url[:20]}... ---")
    return final_url


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

# Modified route with logging and error handling
@app.get('/watch', response_class=HTMLResponse)
async def video(v:str, request: Request, proxy: Union[str] = Cookie(None)):
    logger.info(f"\n======== START PROCESSING VIDEO: {v} ========")
    
    # 1. Fetch the primary video stream URL
    primary_stream_url = await getPrimaryStreamUrl(v)
    
    # 2. Fetch the metadata from Invidious (with error handling for critical failure)
    try:
        video_data = await getVideoData(v)
    except APITimeoutError:
        logger.critical(f"CRITICAL: Failed to get Invidious metadata for {v} due to timeout.")
        # Provide fallback data so the template doesn't crash
        video_data = [{"description_html": failed, "title": failed, "author": failed, "author_thumbnails_url": "", "view_count": failed, "like_count": failed, "subscribers_count": failed, "length_text": failed, "author_id": ""}, []]
    
    # Final result logging
    if primary_stream_url != failed:
        logger.info(f"RESULT: Successfully retrieved stream URL and metadata for {v}.")
    else:
        logger.error(f"RESULT: Failed to retrieve stream URL for {v}.")
    
    logger.info(f"======== END PROCESSING VIDEO: {v} ========\n")

    return templates.TemplateResponse('video.html', {
        "request": request, 
        "videoid": v, 
        "videourls": [primary_stream_url],
        "description": video_data[0]['description_html'], 
        "video_title": video_data[0]['title'], 
        "author_id": video_data[0]['author_id'], 
        "author_icon": video_data[0]['author_thumbnails_url'], 
        "author": video_data[0]['author'], 
        "length_text": video_data[0]['length_text'], 
        "view_count": video_data[0]['view_count'], 
        "like_count": video_data[0]['like_count'], 
        "subscribers_count": video_data[0]['subscribers_count'], 
        "recommended_videos": video_data[1], 
        "proxy":proxy
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
    return templates.TemplateResponse("channel.html", {"request": request, "results": t[0], "channel_name": t[1]["channel_name"], "channel_icon": t[1]["channel_icon"], "channel_profile": t[1]["channel_profile"], "cover_img_url": t[1]["author_banner"], "subscribers_count": t[1]["subscribers_count"], "proxy": proxy})

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
