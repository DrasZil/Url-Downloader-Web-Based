from flask import Flask, render_template, request, jsonify, Response
import yt_dlp
import os
import subprocess
from selenium import webdriver
import time
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager  .chrome import ChromeDriverManager
from threading import Lock
import json
import threading

app = Flask(__name__, static_folder='static', template_folder='templates')

DEFAULT_DOWNLOAD_FOLDER = "D:\\PythonURLDownloader"
COOKIES_FILE = "cookies.txt"
progress_bars = {}
progress_lock = Lock()
# Dictionary to store progress
progress_data = {"status": "Starting...", "progress": 0}

if not os.path.exists(DEFAULT_DOWNLOAD_FOLDER):
    os.makedirs(DEFAULT_DOWNLOAD_FOLDER)

def get_chrome_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    service = Service("/usr/local/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def playwright_extract_video_url(url):
    try:
        from playwright.sync_api import sync_playwright
        import re

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded")
            html = page.content()

            video_candidates = re.findall(r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)(?:\?[^"\'>]*)?', html)
            filtered = [v for v in video_candidates if not any(x in v.lower() for x in ['trailer', 'preview', 'teaser', 'promo'])]

            if filtered:
                return filtered[0]
            elif video_candidates:
                return video_candidates[0]

            browser.close()
    except Exception as e:
        print(f"[PLAYWRIGHT ERROR] {e}")
    return None


def smart_extract_real_video_url(url):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    import re

    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.page_load_strategy = 'eager'

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        html = driver.page_source

        # Try <video> or <source> src from page source
        video_candidates = re.findall(r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)(?:\?[^"\'>]*)?', html)
        filtered = [v for v in video_candidates if not any(x in v.lower() for x in ['trailer', 'preview', 'teaser', 'promo'])]

        if filtered:
            return filtered[0]
        elif video_candidates:
            return video_candidates[0]

        # Try <video> tag directly
        try:
            video = wait.until(EC.presence_of_element_located((By.TAG_NAME, "video")))
            src = video.get_attribute("src")
            if src and "blob:" not in src:
                return src
            try:
                source = video.find_element(By.TAG_NAME, "source")
                src = source.get_attribute("src")
                if src:
                    return src
            except:
                pass
        except:
            pass

        # Check iframe sources
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                src = iframe.get_attribute("src")
                if src and any(ext in src for ext in [".mp4", ".m3u8", "stream", "embed"]):
                    return src
        except:
            pass

        # Regex fallback
        m3u8_match = re.search(r'https?:\/\/[^\s"\']+\.m3u8', html)
        mp4_match = re.search(r'https?:\/\/[^\s"\']+\.mp4', html)
        if m3u8_match:
            return m3u8_match.group(0)
        if mp4_match:
            return mp4_match.group(0)

    except Exception as e:
        print(f"[SELENIUM ERROR] {e}")
    finally:
        driver.quit()

    # ✅ Fallback to Playwright if nothing found
    print("[FALLBACK] Using Playwright...")
    return playwright_extract_video_url(url)


def progress_hook(d):
    """ Callback function to update download progress """
    global progress_data
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '0%').strip()
        progress_data = {"status": "Downloading...", "progress": percent}
    elif d['status'] == 'finished':
        progress_data = {"status": "Download complete!", "progress": "100%"}

def match_filter(info_dict):
    title = info_dict.get('title', '').lower()
    if 'trailer' in title or 'teaser' in title or 'promo' in title:
        return "Filtered out trailer content."
    return None


def get_video_formats(url):
    """Fetch available video and audio formats."""
    ydl_opts = {
        "quiet": True,
        "cookiefile": COOKIES_FILE,
        "nocheckcertificate": True,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "referer": url,
        "format": "bestvideo+bestaudio/best",
        "no_warnings": True,
        "simulate": True,
        "match_filter": match_filter,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            video_info = ydl.extract_info(url, download=False)
            formats = {
                "combined": [],
                "video": [],
                "audio": [],
            }

            best_audio = None
            for fmt in video_info.get("formats", []):
                if fmt.get("acodec", "none") != "none" and fmt.get("vcodec") == "none":
                    if best_audio is None or fmt.get("abr", 0) > best_audio.get("abr", 0):
                        best_audio = fmt

            for fmt in video_info.get("formats", []):
                format_id = fmt.get("format_id")
                height = fmt.get("height")
                width = fmt.get("width")
                if height and width:
                    resolution = f"{width}x{height}"
                else:
                    resolution = fmt.get("format_note", "Unknown")
                filesize = fmt.get("filesize") or fmt.get("filesize_approx")
                size_info = f"{filesize / (1024 * 1024):.2f} MB" if filesize else "Unknown size"
                vcodec = fmt.get("vcodec", "none")
                acodec = fmt.get("acodec", "none")

                # Only add formats that are either:
                # 1. Already combined (have both video and audio)
                # 2. Video-only formats that can be merged with best audio
                if vcodec != "none" and acodec != "none":
                    formats["combined"].append({
                        "format_id": format_id,
                        "resolution": resolution,
                        "size": size_info
                    })
                elif vcodec != "none" and best_audio:
                    # For video-only formats, create a combined format ID
                    combined_format_id = f"{format_id}+{best_audio['format_id']}"
                    formats["video"].append({
                        "format_id": combined_format_id,
                        "resolution": resolution,
                        "size": size_info
                    })

            thumbnail_url = video_info.get("thumbnail", "")

            return formats, video_info, thumbnail_url

    except Exception as e:
        print(f"❌ Error fetching video formats: {e}")
        return {"combined": [], "video": [], "audio": []}, None, None


@app.route("/")
def index():
    return render_template("DL_Web.html")


@app.route("/get_formats", methods=["POST"])
def get_formats():
    url = request.json.get("url")

    try:
        # try-except to catch errors from get_video_formats
        formats, video_info, thumbnail_url = get_video_formats(url)
    except Exception as e:
        print(f"❌ Error in get_video_formats: {e}")
        return jsonify({"error": "❌ Failed to extract video formats. The link may be invalid or unsupported."}), 400

    # Check if formats is valid
    if not formats or not isinstance(formats, dict):
        return jsonify({"error": "❌ Invalid formats received."}), 400

    # Ensure all keys exist in formats
    if not formats.get("audio"):
        formats["audio"] = []
    if not formats.get("video"):
        formats["video"] = []
    if not formats.get("combined"):
        formats["combined"] = []

    # Force download flag
    force_download = False
    if not formats["combined"] and not formats["video"] and not formats["audio"]:
        force_download = True
        print("⚡ Force download mode activated")

    if not formats["audio"]:
        # If no audio formats detected, create a pseudo option for MP3 conversion
        formats["audio"].append({
            "format_id": "convert_to_mp3",
            "resolution": "MP3 (converted)",
            "size": "To be generated"
        })

    # Ensure the response includes the force_download flag if it's true
    response = {
        "video": formats,
        "thumbnail": thumbnail_url,
        "force_download": force_download
    }

    # Check if video_info is not None before calling .get
    if video_info:
        duration = video_info.get("duration")
        print(f"📺 Video Duration: {duration} seconds")

        if duration and duration < 180:  # 3 minutes
            print("⚠️ Detected short video (likely trailer). Consider forcing smart extraction or fallback.")
    else:
        print("⚠️ No video_info found — possible unsupported URL or failed extraction.")

    # Debugging Output:
    print(f"🔍 Formats Found: {formats}")
    print(f"🖼️ Thumbnail URL: {thumbnail_url}")

    return jsonify(response)



def smart_fallback_download(url):
    try:
        output_path = os.path.join(DEFAULT_DOWNLOAD_FOLDER, f"stream_{int(time.time())}.mp4")
        print(f"[FALLBACK] Attempting direct download to: {output_path}")

        subprocess.run([
            "ffmpeg", "-y", "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            output_path
        ], check=True)

        return True, output_path
    except Exception as e:
        print(f"[FALLBACK ERROR] {e}")
        return False, str(e)


@app.route("/download", methods=["POST"])
def download():
    global progress_data
    data = request.json
    url = data.get("url")
    format_id = data.get("format_id")
    force_download = data.get("force_download", False)  # Force fallback
    output_template = os.path.join(DEFAULT_DOWNLOAD_FOLDER, "%(title)s.%(ext)s")

    # Reset progress
    progress_data = {"status": "Starting...", "progress": 0}

    # Safely attempt to smart-extract the real video URL (with timeout)
    def try_smart_extract(original_url, result_container):
        try:
            result_container["url"] = smart_extract_real_video_url(original_url)
        except Exception as e:
            print(f"[SMART ERROR] {e}")
            result_container["url"] = None

    result = {}
    thread = threading.Thread(target=try_smart_extract, args=(url, result))
    thread.start()
    thread.join(timeout=10)  # Timeout in seconds

    real_url = result.get("url")
    if real_url:
        print(f"[SMART] Real stream URL found: {real_url}")
        url = real_url
    else:
        print("[SMART] Timeout or no better stream URL found, using original.")

    # Now, get video formats and ensure video_info is initialized
    formats, video_info, thumbnail_url = get_video_formats(url)

    # Check if video_info is None or if it's not valid
    if not video_info:
        return jsonify({"status": "error", "message": "❌ Unable to fetch video information."})

    # Access the video_info and its properties safely
    duration = video_info.get("duration")
    print(f"📺 Video Duration: {duration} seconds")

    if duration and duration < 180:  # 3 minutes
        print("⚠️ Detected short video (likely trailer). Consider forcing smart extraction or fallback.")

    # Check for trailer content
    if video_info and match_filter(video_info):  # Check if the video is a trailer
        return jsonify({"status": "error", "message": "❌ Trailer content detected. Try another video."})

    # Debugging Output:
    print(f"🔍 Formats Found: {formats}")
    print(f"🖼️ Thumbnail URL: {thumbnail_url}")

    if not formats["combined"] and not formats["video"] and not formats["audio"]:
        print("⚡ No valid formats found. Attempting force download as fallback.")
        force_download = True  # Trigger force download mode

    # Basic config
    ydl_opts = {
        'format': format_id if format_id else 'bestvideo+bestaudio/best',
        'progress_hooks': [progress_hook],
        'outtmpl': output_template,
        'socket_timeout': 10,
        'retries': 3,
        'merge_output_format': 'mp4',
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4'
        }],
        'postprocessor_args': [
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-strict', 'experimental'
        ]
    }

    # Try direct download
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return jsonify({"message": "✅ Download Complete!"})
    except Exception as e:
        print(f"[ERROR] {e}")
        if not force_download:
            return jsonify({"message": f"Error: {str(e)}"})

    # Fallbacks (only reached if exception occurs AND force_download is true)
    if force_download:
        try:
            ydl_opts['format'] = 'best'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return jsonify({"status": "success", "message": "✅ Forced default format download complete."})
        except Exception as e:
            print(f"[FORCE ERROR] {e}")
            # Final Fallback using ffmpeg if smart URL exists
            if real_url:
                print("🔁 Trying final ffmpeg fallback with real URL...")
                success, message = smart_fallback_download(real_url)
                if success:
                    return jsonify({"status": "success", "message": "✅ Smart fallback download complete!"})
                else:
                    return jsonify({"status": "error", "message": f"❌ Smart fallback failed: {message}"})

            return jsonify({"status": "error", "message": f"Force Download Failed: {str(e)}"})

    return jsonify({"status": "error", "message": "❌ Download failed. Try a different format or force download."})


@app.route('/progress')
def progress():
    """ Stream real-time download progress """
    def event_stream():
        while True:
            time.sleep(1)  # Send updates every 1 second
            yield f"data: {json.dumps(progress_data)}\n\n"

    return Response(event_stream(), content_type='text/event-stream')


def download_video(url, format_id):
    global pbar  # Define progress bar globally inside function

    if not format_id or format_id.lower() == "none":
        format_id = "best"  # Fallback to best available format

    ydl_opts = {
        "format": format_id if format_id and format_id.lower() != "none" else "bestvideo+bestaudio/best",  # Download selected format
        "outtmpl": os.path.join(DEFAULT_DOWNLOAD_FOLDER, "%(title)s.%(ext)s"),  # Save with video title
        "progress_hooks": [progress_hook],  # Attach progress hook
        "cookiefile": COOKIES_FILE,
        "cachedir": True,
        "merge_output_format": "mp4",
        "nocheckcertificate": True,
        "hls_prefer_native": True,
        "embed-metadata": True,
        "force_overwrites": True,
        "noplaylist": True,
        "retries": 50,
        "postprocessors": [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
        "force-ipv4": True,
        "buffer-size": "128M",
        "throttled-rate": None,
        "fragment-retries": 50,
        "concurrent-fragments": 32,
        "external_downloader": "aria2c",
        "external_downloader_args": ["-x", "64", "-s", "64", "-k", "8M"],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            print("✅ Download complete!\n")
            print(f"✅ Downloaded file saved at: {os.path.join(DEFAULT_DOWNLOAD_FOLDER, '%(title)s.%(ext)s')}")
            return jsonify({"status": "success", "message": "Download completed!"})


    except yt_dlp.utils.DownloadError:
        print("\n❌ yt-dlp failed! \n Trying streamlink as a backup...\n")
        return try_alternative_downloads(url)



def try_alternative_downloads(url):
    """Try backup download methods."""
    methods = [streamlink_download, ffmpeg_download, mpv_download, aria2c_download, detect_blob_video]

    for method in methods:
        if method(url):
            return True

    return False


def streamlink_download(url):
    """Try downloading via Streamlink."""
    output_path = os.path.join(DEFAULT_DOWNLOAD_FOLDER, "streamlink_output.mp4")
    cmd = f'streamlink {url} best -o "{output_path}"'
    return run_command(cmd, "Streamlink")


def ffmpeg_download(url):
    """Try downloading via FFmpeg."""
    output_path = os.path.join(DEFAULT_DOWNLOAD_FOLDER, "ffmpeg_output.mp4")
    cmd = f'ffmpeg -hwaccel auto -i "{url}" -c:v libx264 -preset ultrafast -crf 18 -c:a copy "{output_path}"'
    return run_command(cmd, "FFmpeg")


def mpv_download(url):
    """Try downloading via MPV."""
    output_path = os.path.join(DEFAULT_DOWNLOAD_FOLDER, "mpv_output.mp4")
    cmd = f'mpv "{url}" --stream-record="{output_path}"'
    return run_command(cmd, "MPV")


def aria2c_download(url):
    """Try downloading via Aria2c."""
    cmd = f'aria2c -x 16 -s 16 -d "{DEFAULT_DOWNLOAD_FOLDER}" "{url}"'
    return run_command(cmd, "Aria2c")


def detect_blob_video(url):
    """Try detecting and downloading blob videos."""
    print("🔍 Checking for Blob URLs...")
    options = Options()
    options.add_argument("--headless")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    driver.get(url)
    time.sleep(5)

    page_source = driver.page_source
    driver.quit()

    blob_url = extract_blob_url(page_source)
    if blob_url:
        return ffmpeg_download(blob_url)

    return False


def extract_blob_url(html):
    """Extract Blob URL from HTML."""
    import re
    match = re.search(r'blob:https?://[^\s"]+', html)
    return match.group(0) if match else None


def run_command(cmd, method_name):
    """Run a command and return success status."""
    try:
        subprocess.run(cmd, shell=True, check=True)
        print(f"✅ Downloaded using {method_name}.")
        return True
    except subprocess.CalledProcessError:
        print(f"❌ {method_name} failed.")
        return False

@app.route("/download_mp3", methods=["POST"])
def download_mp3():
    global progress_data
    data = request.json
    url = data.get("url")
    format_id = data.get("format_id")

    progress_data = {"status": "Starting MP3 download...", "progress": 0}

    # Temporary file path
    output_path = os.path.join(DEFAULT_DOWNLOAD_FOLDER, "temp_audio.mp4")

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'progress_hooks': [progress_hook],
        'cookiefile': COOKIES_FILE,
        'nocheckcertificate': True
    }

    try:
        # Step 1: Download the best audio/video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Step 2: Convert it to MP3 using ffmpeg
        mp3_path = os.path.join(DEFAULT_DOWNLOAD_FOLDER, "converted_audio.mp3")
        ffmpeg_cmd = f'ffmpeg -y -i "{output_path}" -vn -ab 192k -ar 44100 -f mp3 "{mp3_path}"'
        subprocess.run(ffmpeg_cmd, shell=True, check=True)

        # Step 3: Cleanup (optional)
        if os.path.exists(output_path):
            os.remove(output_path)

        progress_data = {"status": "MP3 Conversion Done!", "progress": "100%"}
        return jsonify({"message": "✅ MP3 download and conversion complete!"})


    except Exception as e:
        progress_data = {"status": "MP3 Conversion Failed", "progress": "0%"}
        print(f"❌ Error in MP3 conversion: {e}")
        return jsonify({"error": f"MP3 download/conversion failed: {str(e)}"})


@app.route('/shortener')
def shortener():
    return render_template('URL_Web_Shortener.html')

@app.route("/debug-static")
def debug_static():
    import os
    return "<br>".join(os.listdir("static"))

if __name__ == "__main__":
    app.run(debug=True)