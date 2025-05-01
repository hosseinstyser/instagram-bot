import os
from dotenv import load_dotenv
load_dotenv()  # بارگذاری متغیرها
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')  # دریافت توکن
assert TELEGRAM_TOKEN, "لطفا TELEGRAM_TOKEN را در تنظیمات محیطی تنظیم کنید!"
import re
import logging
import requests
from urllib.parse import urlparse
import instaloader
from typing import List, Tuple, Optional
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

load_dotenv()
# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class InstagramDownloader:
    def __init__(self):
        self.loader = instaloader.Instaloader(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            request_timeout=60
        )
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-IG-App-ID': '936619743392459'
        }

    def login(self, username: str, password: str) -> bool:
        try:
            self.loader.context.login(username, password)
            logger.info("Login successful")
            return True
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    def get_post_info(self, url: str) -> Tuple[List[Tuple[str, str]], str]:
        try:
            shortcode = self.get_shortcode(url)
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
            
            media_list = []
            caption = post.caption if post.caption else ""
            
            if post.typename == 'GraphSidecar':
                for node in post.get_sidecar_nodes():
                    if node.is_video:
                        media_list.append((node.video_url, 'video'))
                    else:
                        media_list.append((node.display_url, 'photo'))
            else:
                if post.is_video:
                    media_list.append((post.video_url, 'video'))
                else:
                    media_list.append((post.url, 'photo'))
            
            return media_list, caption
        except Exception as e:
            logger.error(f"Error getting post info: {e}")
            return [], ""

    def get_shortcode(self, url: str) -> str:
        pattern = r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv)/([^/?#&]+)'
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        raise ValueError("Invalid Instagram URL")

    def download_media(self, url: str) -> Optional[bytes]:
        try:
            response = self.session.get(url, headers=self.headers, timeout=60)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None

class TelegramBot:
    def __init__(self, token: str, insta_downloader: InstagramDownloader):
        self.token = token
        self.insta_downloader = insta_downloader
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        # Register handlers
        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), self.handle_message))

    def start(self, update: Update, context: CallbackContext):
        update.message.reply_text(
            "🤖 Instagram Downloader Bot 🤖\n\n"
            "Send me an Instagram post/reel/IGTV link to download it."
        )

    def handle_message(self, update: Update, context: CallbackContext):
        url = update.message.text
        if not self.is_instagram_url(url):
            update.message.reply_text("Please send a valid Instagram URL")
            return

        update.message.reply_text("Processing...")
        
        try:
            media_list, caption = self.insta_downloader.get_post_info(url)
            if not media_list:
                update.message.reply_text("Failed to get media. The post might be private.")
                return

            downloaded_media = []
            for media_url, media_type in media_list:
                content = self.insta_downloader.download_media(media_url)
                if content:
                    downloaded_media.append((content, media_type))

            if not downloaded_media:
                update.message.reply_text("Failed to download media")
                return

            self.send_media(update, downloaded_media, caption)

        except Exception as e:
            logger.error(f"Error: {e}")
            update.message.reply_text(f"An error occurred: {str(e)}")

    def is_instagram_url(self, url: str) -> bool:
        patterns = [
            r'https?://(www\.)?instagram\.com/p/',
            r'https?://(www\.)?instagram\.com/reel/',
            r'https?://(www\.)?instagram\.com/tv/',
            r'https?://(www\.)?instagram\.com/reels/'
        ]
        return any(re.search(pattern, url) for pattern in patterns)

    def send_media(self, update: Update, media_list: List[Tuple[bytes, str]], caption: str):
        if len(media_list) == 1:
            content, media_type = media_list[0]
            try:
                if media_type == 'photo':
                    update.message.reply_photo(photo=content, caption=caption[:1000])
                else:
                    update.message.reply_video(video=content, caption=caption[:1000])
            except Exception as e:
                logger.error(f"Send media error: {e}")
        else:
            media_group = []
            for idx, (content, media_type) in enumerate(media_list):
                try:
                    if media_type == 'photo':
                        media = InputMediaPhoto(media=content, caption=caption[:1000] if idx == 0 else None)
                    else:
                        media = InputMediaVideo(media=content, caption=caption[:1000] if idx == 0 else None)
                    media_group.append(media)
                except Exception as e:
                    logger.error(f"Media group error: {e}")
                    continue

            if media_group:
                try:
                    update.message.reply_media_group(media=media_group)
                except Exception as e:
                    logger.error(f"Media group send error: {e}")

    def start_bot(self):
        logger.info("Bot started")
        self.updater.start_polling()
        self.updater.idle()

def main():
    # Get configuration from environment variables
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    INSTA_USERNAME = os.environ.get('INSTA_USERNAME')
    INSTA_PASSWORD = os.environ.get('INSTA_PASSWORD')

    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN environment variable is required!")
        return

    insta_downloader = InstagramDownloader()
    
    if INSTA_USERNAME and INSTA_PASSWORD:
        if not insta_downloader.login(INSTA_USERNAME, INSTA_PASSWORD):
            logger.warning("Instagram login failed. Continuing without login...")

    bot = TelegramBot(TELEGRAM_TOKEN, insta_downloader)
    bot.start_bot()

if __name__ == '__main__':
    main()
