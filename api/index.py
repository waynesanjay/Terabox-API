import os
import re
import json
import aiohttp
import asyncio
import logging
import time
from urllib.parse import urlparse, parse_qs
from flask import Flask, request, jsonify
from fake_useragent import UserAgent

app = Flask(__name__)

# ====== 🇮🇳 ==============
# # © Developer = WOODcraft 
# ========================
# Configuration
REQUEST_TIMEOUT = 60  # Increased timeout
MAX_RETRIES = 10      # Increased retries
RETRY_DELAY = 2
PORT = 3000

# Supported domains
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
TERABOX_URL_REGEX = r'^https:\/\/(www\.)?(terabox\.com|1024terabox\.com|teraboxapp\.com|teraboxlink\.com|terasharelink\.com|terafileshare\.com|1024tera\.com|1024tera\.cn|teraboxdrive\.com|dubox\.com)\/(s|sharing\/link)\/[A-Za-z0-9_\-]+'

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# User agent rotator
ua = UserAgent()

# FRESH TESTED COOKIES (Updated 2024-06-23)
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
    'ab_sr': '1.0.1_NjA1ZWE3ODRiYjJiYjZkYjQzYjU4NmZkZGVmOWYxNDg4MjU3ZDZmMTg0Nzg4MWFlNzQzZDMxZWExNmNjYzliMGFlYjIyNWUzYzZiODQ1Nzg3NWM0MzIzNWNiYTlkYTRjZTc0ZTc5ODRkNzg4NDhiMTljOGRiY2I4MzY4ZmYyNTU5ZDE5NDczZmY4NjJhMDgyNjRkZDI2MGY5M2Q1YzIyMg=='
}
    

def get_headers():
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
        'Referer': 'https://www.terabox.com/'
    }

def validate_terabox_url(url):
    try:
        return re.match(TERABOX_URL_REGEX, url) is not None
    except Exception:
        return False

async def fetch_with_retries(session, url, method='GET', headers=None, params=None, allow_redirects=True):
    for attempt in range(MAX_RETRIES):
        try:
            async with session.request(
                method,
                url,
                headers=headers or get_headers(),
                params=params,
                allow_redirects=allow_redirects,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            ) as response:
                if response.status in [403, 429, 502, 503]:
                    logger.warning(f"Retryable status {response.status}, attempt {attempt+1}")
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
                    continue
                response.raise_for_status()
                return await response.text()
        except (aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError) as e:
            logger.warning(f"Connection error on attempt {attempt+1}: {str(e)}")
            await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
        except Exception as e:
            logger.error(f"Request failed on attempt {attempt+1}: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))
    raise Exception(f"All {MAX_RETRIES} attempts failed")

async def extract_tokens(html):
    # Multiple extraction methods
    js_token = re.search(r'fn\(["\']([a-zA-Z0-9]+)["\']\)', html)
    if js_token:
        js_token = js_token.group(1)
    else:
        js_token = re.search(r'jsToken\s*=\s*["\']([a-zA-Z0-9]+)["\']', html)
        js_token = js_token.group(1) if js_token else None

    log_id = re.search(r'dp-logid=([a-zA-Z0-9]+)', html)
    if log_id:
        log_id = log_id.group(1)
    else:
        log_id = re.search(r'dplogid\s*=\s*["\']([a-zA-Z0-9]+)["\']', html)
        log_id = log_id.group(1) if log_id else None

    if not js_token or not log_id:
        raise Exception("Token extraction failed")

    return js_token, log_id

async def get_surl(response_url):
    parsed = urlparse(response_url)
    query = parse_qs(parsed.query)
    surl = query.get('surl', [None])[0]
    
    if not surl:
        path_parts = parsed.path.split('/')
        if 's' in path_parts:
            s_index = path_parts.index('s')
            if len(path_parts) > s_index + 1:
                surl = path_parts[s_index + 1]
    
    if not surl:
        raise Exception("Could not extract surl from URL")
    
    return surl

async def fetch_file_list(session, api_url, params):
    for _ in range(3):  # Try multiple API versions
        try:
            params['ver'] = params.get('ver', 4)  # Start with latest version
            async with session.get(api_url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                if 'list' in data and data['list']:
                    return data['list']
                # Try older version
                params['ver'] = params['ver'] - 1 if params['ver'] > 1 else 4
        except Exception as e:
            logger.warning(f"API request failed: {str(e)}")
            await asyncio.sleep(1)
    raise Exception("All API versions failed")

async def process_terabox_url(url):
    async with aiohttp.ClientSession(cookies=COOKIES) as session:
        # Step 1: Fetch initial page
        html = await fetch_with_retries(session, url)
        
        # Step 2: Extract tokens
        js_token, log_id = await extract_tokens(html)
        
        # Step 3: Get surl
        surl = await get_surl(url)
        
        # Step 4: Prepare API request
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
            'site_referer': url,
            'shorturl': surl,
            'root': '1',
            'ver': 4  # Latest API version
        }
        
        # Step 5: Fetch file list
        file_list = await fetch_file_list(session, 'https://www.1024tera.com/api/share/list', params)
        
        # Step 6: Handle directories
        if file_list and file_list[0].get('isdir') == "1":
            dir_params = params.copy()
            dir_params.update({
                'dir': file_list[0]['path'],
                'order': 'asc',
                'by': 'name'
            })
            dir_params.pop('desc', None)
            dir_params.pop('root', None)
            file_list = await fetch_file_list(session, 'https://www.1024tera.com/api/share/list', dir_params)
        
        # Step 7: Process files
        results = []
        for file in file_list:
            dlink = file.get('dlink')
            if not dlink:
                continue
                
            # Get direct download link
            try:
                async with session.head(dlink, allow_redirects=False) as response:
                    if 300 <= response.status < 400:
                        dlink = response.headers.get('Location', dlink)
            except Exception:
                pass
            
            # Format size
            size_bytes = file.get('size', 0)
            size_str = "Unknown"
            if size_bytes:
                try:
                    size_bytes = int(size_bytes)
                    if size_bytes >= 1024**3:  # GB
                        size_str = f"{size_bytes / (1024**3):.2f} GB"
                    elif size_bytes >= 1024**2:  # MB
                        size_str = f"{size_bytes / (1024**2):.2f} MB"
                    elif size_bytes >= 1024:  # KB
                        size_str = f"{size_bytes / 1024:.2f} KB"
                    else:
                        size_str = f"{size_bytes} bytes"
                except Exception:
                    pass
            
            results.append({
                "file_name": file.get("server_filename", "Unknown"),
                "size": size_str,
                "size_bytes": size_bytes,
                "download_url": file.get('dlink', ''),
                "direct_download_url": dlink,
                "is_directory": file.get("isdir", "0") == "1",
                "modify_time": file.get("server_mtime", 0),
                "thumbnails": file.get("thumbs", {})
            })
        
        return results

@app.route('/api', methods=['GET'])
async def api_handler():
    start_time = time.time()
    url = request.args.get('url')
    if not url:
        return jsonify({
            "status": "error",
            "message": "URL parameter is required",
            "usage": "/api?url=TERABOX_SHARE_URL"
        }), 400
    
    if not validate_terabox_url(url):
        return jsonify({
            "status": "error",
            "message": "Invalid Terabox URL format",
            "supported_domains": SUPPORTED_DOMAINS,
            "url": url
        }), 400
    
    try:
        logger.info(f"Processing URL: {url}")
        files = await process_terabox_url(url)
        
        if not files:
            return jsonify({
                "status": "error",
                "message": "No files found or link is empty",
                "url": url
            }), 404
        
        return jsonify({
            "status": "success",
            "url": url,
            "files": files,
            "processing_time": f"{time.time() - start_time:.2f}s",
            "file_count": len(files),
            "cookies": "valid"
        })
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Service error: {str(e)}",
            "solution": "Try again later or contact support",
            "url": url,
            "developer": "@Farooq_is_king"
        }), 500

@app.route('/')
def home():
    return jsonify({
        "status": "API Running",
        "developer": "@Farooq_is_king",
        "usage": "/api?url=TERABOX_SHARE_URL",
        "supported_domains": SUPPORTED_DOMAINS,
        "cookie_status": "valid"
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    logger.info(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True)
