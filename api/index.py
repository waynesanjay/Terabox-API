import os
from flask import Flask, request, jsonify, Response
import json
import aiohttp
import asyncio
import logging
import time
from urllib.parse import parse_qs, urlparse
from fake_useragent import UserAgent

app = Flask(__name__)

# ====== 🇮🇳 ==============
# # © Developer = WOODcraft 
# ========================
# Configuration
COOKIES_FILE = 'cookies.json'
REQUEST_TIMEOUT = 30
MAX_RETRIES = 5
RETRY_DELAY = 2
PORT = 3000

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize user agent rotator
ua = UserAgent()

def get_random_headers():
    return {
        'User-Agent': ua.random,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'Referer': 'https://terafileshare.com/'
    }

def load_cookies():
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, 'r') as f:
                cookies = json.load(f)
                logger.info(f"Loaded {len(cookies)} cookies from {COOKIES_FILE}")
                return cookies
        except Exception as e:
            logger.error(f"Cookie load error: {str(e)}")
            return {}
    logger.warning(f"No cookies file found at {COOKIES_FILE}")
    return {}

def find_between(string, start, end):
    try:
        if string is None:
            return None
        start_index = string.find(start)
        if start_index == -1:
            return None
        start_index += len(start)
        end_index = string.find(end, start_index)
        if end_index == -1:
            return None
        return string[start_index:end_index]
    except Exception as e:
        logger.error(f"find_between error: {str(e)}")
        return None

async def make_request(session, url, method='GET', headers=None, params=None, allow_redirects=True):
    retry_count = 0
    last_exception = None
    while retry_count < MAX_RETRIES:
        try:
            current_headers = headers or get_random_headers()
            async with session.request(
                method,
                url,
                headers=current_headers,
                params=params,
                allow_redirects=allow_redirects,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            ) as response:
                if response.status == 403:
                    logger.warning(f"Blocked by server (403), retrying... (attempt {retry_count + 1})")
                    retry_count += 1
                    await asyncio.sleep(RETRY_DELAY * (retry_count + 1))
                    continue
                response.raise_for_status()
                return response
        except Exception as e:
            last_exception = e
            retry_count += 1
            logger.warning(f"Request failed (attempt {retry_count}): {str(e)}")
            await asyncio.sleep(RETRY_DELAY * (retry_count + 1))
    raise Exception(f"Max retries exceeded. Last error: {str(last_exception)}")

async def fetch_download_link_async(url):
    try:
        cookies = load_cookies()
        if not cookies:
            raise Exception("No valid cookies found. Please update cookies.json")
        
        logger.info(f"Using cookies: {list(cookies.keys())}")
        
        async with aiohttp.ClientSession(cookies=cookies) as session:
            response = await make_request(session, url)
            response_data = await response.text()
            
            # Debug: Save HTML for inspection
            with open("debug.html", "w", encoding="utf-8") as f:
                f.write(response_data)
            
            js_token = find_between(response_data, 'fn%28%22', '%22%29')
            if not js_token:
                js_token = find_between(response_data, 'fn("', '")')
            
            log_id = find_between(response_data, 'dp-logid=', '&')
            if not log_id:
                log_id = find_between(response_data, 'dp-logid=', '"')
            
            if not js_token or not log_id:
                logger.error("Token extraction failed. Possible reasons:")
                logger.error("1. Cookies expired")
                logger.error("2. Site structure changed")
                logger.error("3. URL format invalid")
                logger.error(f"Response snippet: {response_data[:500]}...")
                raise Exception("Could not extract required tokens from the page")
            
            request_url = str(response.url)
            surl = None
            if 'surl=' in request_url:
                surl = request_url.split('surl=')[1]
                if '&' in surl:
                    surl = surl.split('&')[0]
            
            if not surl:
                parsed = urlparse(request_url)
                query = parse_qs(parsed.query)
                surl = query.get('surl', [None])[0]
                if not surl:
                    raise Exception("Could not extract surl from URL")
            
            logger.info(f"Extracted tokens: js_token={js_token[:5]}..., log_id={log_id}, surl={surl}")
            
            params = {
                'app_id': '250528',
                'web': '1',
                'channel': 'dubox',
                'clienttype': '0',
                'jsToken': js_token,
                'dplogid': log_id,
                'page': '1',
                'num': '20',
                'order': 'time',
                'desc': '1',
                'site_referer': request_url,
                'shorturl': surl,
                'root': '1'
            }
            
            list_response = await make_request(session, 'https://www.1024tera.com/share/list', params=params)
            list_data = await list_response.json()
            
            if 'list' not in list_data or not list_data['list']:
                raise Exception("No files found in shared link")
            
            if list_data['list'][0]['isdir'] == "1":
                dir_params = params.copy()
                dir_params.update({
                    'dir': list_data['list'][0]['path'],
                    'order': 'asc',
                    'by': 'name',
                    'dplogid': log_id
                })
                dir_params.pop('desc', None)
                dir_params.pop('root', None)
                
                dir_response = await make_request(session, 'https://www.1024tera.com/share/list', params=dir_params)
                dir_data = await dir_response.json()
                
                if 'list' not in dir_data or not dir_data['list']:
                    raise Exception("No files found in directory")
                
                return dir_data['list']
            
            return list_data['list']
    except Exception as e:
        logger.error(f"fetch_download_link_async error: {str(e)}", exc_info=True)
        raise

async def get_direct_link(session, dlink):
    try:
        try:
            response = await make_request(session, dlink, method='HEAD', allow_redirects=False)
            if 300 <= response.status < 400:
                return response.headers.get('Location', dlink)
        except Exception:
            pass
        
        response = await make_request(session, dlink, method='GET', allow_redirects=False)
        if 300 <= response.status < 400:
            return response.headers.get('Location', dlink)
        return dlink
    except Exception as e:
        logger.warning(f"Direct link error: {str(e)}")
        return dlink

async def get_formatted_size(size_bytes):
    try:
        size_bytes = int(size_bytes)
        for unit in ['bytes', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}" if unit != 'bytes' else f"{size_bytes} bytes"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"
    except Exception:
        return "Unknown size"

async def process_file(session, file_data):
    try:
        direct_link = await get_direct_link(session, file_data['dlink'])
        return {
            "file_name": file_data.get("server_filename"),
            "size": await get_formatted_size(file_data.get("size", 0)),
            "size_bytes": file_data.get("size", 0),
            "download_url": file_data['dlink'],
            "direct_download_url": direct_link,
            "is_directory": file_data.get("isdir", "0") == "1",
            "modify_time": file_data.get("server_mtime"),
            "thumbnails": file_data.get("thumbs", {})
        }
    except Exception as e:
        logger.error(f"File processing error: {str(e)}")
        return None

@app.route('/api', methods=['GET'])
async def api_handler():
    start_time = time.time()
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({
                "status": "error",
                "message": "URL parameter is required. Developed by @Farooq_is_king. Join @OPLEECH_WD for updates.",
                "usage": "/api?url=YOUR_TERABOX_SHARE_URL"
            }), 400
        
        logger.info(f"Processing URL: {url}")
        files = await fetch_download_link_async(url)
        
        if not files:
            return jsonify({
                "status": "error",
                "message": "No files found in the shared link",
                "url": url
            }), 404
        
        async with aiohttp.ClientSession(cookies=load_cookies()) as session:
            results = []
            for file in files:
                processed = await process_file(session, file)
                if processed:
                    results.append(processed)
            
            if not results:
                return jsonify({
                    "status": "error",
                    "message": "Could not process any files",
                    "url": url
                }), 500
            
            return jsonify({
                "status": "success",
                "url": url,
                "files": results,
                "processing_time": f"{time.time() - start_time:.2f} seconds",
                "file_count": len(results),
                "cookie_status": "valid" if load_cookies() else "invalid"
            })
    except Exception as e:
        logger.error(f"API error: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Service error: {str(e)}",
            "solution": "Check server logs or refresh cookies",
            "url": url or "Not provided",
            "developer": "@Farooq_is_king"
        }), 500

@app.route('/')
def home():
    data = {
        "status": "Running ✅",
        "developer": "@Farooq_is_king",
        "channel": "@Opleech_WD",
        "cookie_status": "valid" if load_cookies() else "invalid",
        "endpoints": {
            "/api": "GET with ?url=TERABOX_SHARE_URL parameter",
            "/health": "Service health check",
            "/cookie-status": "Check cookie validity"
        }
    }
    return Response(json.dumps(data, ensure_ascii=False), mimetype='application/json')

@app.route('/health')
def health_check():
    data = {
        "status": "healthy",
        "developer": "@Farooq_is_king",
        "channel": "@Opleech_WD",
        "cookie_count": len(load_cookies())
    }
    return Response(json.dumps(data, ensure_ascii=False), mimetype='application/json')

@app.route('/cookie-status')
def cookie_check():
    cookies = load_cookies()
    status = {
        "status": "valid" if cookies else "invalid",
        "cookie_count": len(cookies),
        "required_cookies": [
            "ndut_fmt", "ndus", "__bid_n", 
            "__stripe_mid", "__stripe_sid", 
            "browserid", "csrfToken"
        ],
        "present_cookies": list(cookies.keys())
    }
    return Response(json.dumps(status, ensure_ascii=False), mimetype='application/json')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    logger.info(f"Starting server on port {port}")
    logger.info(f"Cookie status: {'valid' if load_cookies() else 'INVALID'}")
    app.run(host='0.0.0.0', port=port, threaded=True)
