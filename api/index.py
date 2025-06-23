import os
import re
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
REQUEST_TIMEOUT = 45  # Increased timeout
MAX_RETRIES = 8       # Increased retries
RETRY_DELAY = 3
PORT = 3000

# Supported domains list
SUPPORTED_DOMAINS = [
    "terabox.com",
    "1024terabox.com",
    "teraboxapp.com",
    "teraboxlink.com",
    "terasharelink.com",
    "terafileshare.com",
    "www.1024tera.com",
    "1024tera.com",
    "1024tera.cn",
    "teraboxdrive.com",
    "dubox.com"
]

# Regex pattern for Terabox URLs
TERABOX_URL_REGEX = r'^https:\/\/(www\.)?(terabox\.com|1024terabox\.com|teraboxapp\.com|teraboxlink\.com|terasharelink\.com|terafileshare\.com|1024tera\.com|1024tera\.cn|teraboxdrive\.com|dubox\.com)\/(s|sharing\/link)\/[A-Za-z0-9]+'

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize user agent rotator
ua = UserAgent()

# UPDATED COOKIES (Refreshed on 2024-06-23)
COOKIES = {
    'ndut_fmt': '082E0D57C65BDC31F6FF293F5D23164958B85D6952CCB6ED5D8A3870CB302BE7',
    'ndus': 'Y-wWXKyteHuigAhC03Fr4bbee-QguZ4JC6UAdqap',
    '__bid_n': '196ce76f980a5dfe624207',
    '__stripe_mid': '148f0bd1-59b1-4d4d-8034-6275095fc06f99e0e6',
    '__stripe_sid': '7b425795-b445-47da-b9db-5f12ec8c67bf085e26',
    'browserid': 'veWFJBJ9hgVgY0eI9S7yzv66aE28f3als3qUXadSjEuICKF1WWBh4inG3KAWJsAYMkAFpH2FuNUum87q',
    'csrfToken': 'wlv_WNcWCjBtbNQDrHSnut2h',
    'lang': 'en',
    'PANWEB': '1'
}

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
        'Referer': 'https://terabox.com/'
    }

def load_cookies():
    return COOKIES

def validate_terabox_url(url):
    try:
        if not re.match(TERABOX_URL_REGEX, url):
            return False
        
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        return any(supported_domain in domain for supported_domain in SUPPORTED_DOMAINS)
    except Exception:
        return False

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
                if response.status in [403, 429]:
                    logger.warning(f"Blocked ({response.status}), retrying... (attempt {retry_count + 1})")
                    retry_count += 1
                    await asyncio.sleep(RETRY_DELAY * (2 ** retry_count))  # Exponential backoff
                    continue
                response.raise_for_status()
                return response
        except (aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError) as e:
            logger.warning(f"Connection error: {str(e)}")
            retry_count += 1
            await asyncio.sleep(RETRY_DELAY * (2 ** retry_count))
            last_exception = e
        except Exception as e:
            last_exception = e
            retry_count += 1
            logger.warning(f"Request failed (attempt {retry_count}): {str(e)}")
            await asyncio.sleep(RETRY_DELAY * (retry_count + 1))
    raise Exception(f"Max retries exceeded. Last error: {str(last_exception)}")

async def fetch_download_link_async(url):
    try:
        cookies = load_cookies()
        logger.info(f"Using cookies: {list(cookies.keys())}")
        
        async with aiohttp.ClientSession(cookies=cookies) as session:
            # Follow redirects manually
            response = await make_request(session, url, allow_redirects=False)
            if response.status in (301, 302, 303, 307, 308):
                redirect_url = response.headers.get('Location')
                logger.info(f"Following redirect to: {redirect_url}")
                response = await make_request(session, redirect_url)
            
            response_data = await response.text()
            
            # Improved token extraction
            js_token = find_between(response_data, 'fn%28%22', '%22%29') or \
                       find_between(response_data, 'fn("', '")') or \
                       find_between(response_data, "fn('", "')")
            
            log_id = find_between(response_data, 'dp-logid=', '&') or \
                     find_between(response_data, 'dp-logid=', '"') or \
                     find_between(response_data, 'dp-logid=', "'")
            
            if not js_token or not log_id:
                # New fallback: Search in script tags
                script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
                for script in script_pattern.findall(response_data):
                    if 'dp-logid' in script and 'jsToken' in script:
                        js_token = js_token or find_between(script, 'jsToken:"', '"')
                        log_id = log_id or find_between(script, 'dp-logid=', '"')
                        if js_token and log_id:
                            break
                
                if not js_token or not log_id:
                    logger.error("Token extraction failed")
                    raise Exception("Could not extract required tokens from the page")
            
            request_url = str(response.url)
            surl = None
            parsed = urlparse(request_url)
            query = parse_qs(parsed.query)
            surl = query.get('surl', [None])[0]
            
            if not surl:
                # Alternative extraction from URL path
                if '/s/' in request_url:
                    surl = request_url.split('/s/')[-1].split('/')[0].split('?')[0]
                elif '/sharing/link?sid=' in request_url:
                    surl = find_between(request_url, 'sid=', '&') or find_between(request_url, 'sid=', '"')
            
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
            
            # Use new API endpoint
            api_url = 'https://www.1024tera.com/api/share/list'
            list_response = await make_request(session, api_url, params=params)
            list_data = await list_response.json()
            
            if 'list' not in list_data or not list_data['list']:
                # Try alternative API version
                params['ver'] = '4'
                list_response = await make_request(session, api_url, params=params)
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
                
                dir_response = await make_request(session, api_url, params=dir_params)
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
        response = await make_request(session, dlink, method='HEAD', allow_redirects=False)
        if 300 <= response.status < 400:
            location = response.headers.get('Location')
            if location and location != dlink:
                return await get_direct_link(session, location)  # Recursive redirect handling
            return location or dlink
        return dlink
    except Exception as e:
        logger.warning(f"Direct link error: {str(e)}")
        return dlink

async def get_formatted_size(size_bytes):
    try:
        size_bytes = int(size_bytes)
        if size_bytes >= 1024**3:  # GB
            return f"{size_bytes / (1024**3):.2f} GB"
        elif size_bytes >= 1024**2:  # MB
            return f"{size_bytes / (1024**2):.2f} MB"
        elif size_bytes >= 1024:  # KB
            return f"{size_bytes / 1024:.2f} KB"
        return f"{size_bytes} bytes"
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
                "message": "URL parameter is required",
                "usage": "/api?url=YOUR_TERABOX_SHARE_URL"
            }), 400
        
        if not validate_terabox_url(url):
            return jsonify({
                "status": "error",
                "message": "Invalid Terabox URL format",
                "supported_domains": SUPPORTED_DOMAINS,
                "url": url
            }), 400
        
        logger.info(f"Processing URL: {url}")
        files = await fetch_download_link_async(url)
        
        async with aiohttp.ClientSession(cookies=load_cookies()) as session:
            results = []
            for file in files:
                processed = await process_file(session, file)
                if processed:
                    results.append(processed)
            
            return jsonify({
                "status": "success",
                "url": url,
                "files": results,
                "processing_time": f"{time.time() - start_time:.2f}s",
                "file_count": len(results),
                "cookie_status": "valid"
            })
    except Exception as e:
        logger.error(f"API error: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Service error: {str(e)}",
            "solution": "Try again later or contact support",
            "url": url or "Not provided",
            "developer": "@Farooq_is_king"
        }), 500

@app.route('/')
def home():
    return jsonify({
        "status": "API Running",
        "developer": "@Farooq_is_king",
        "endpoint": "/api?url=TERABOX_SHARE_URL",
        "note": "Use valid Terabox share links"
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    logger.info(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True)
