import os
import re
import requests
from urllib.parse import urlparse
import instaloader
from typing import Optional, Tuple, List  # اضافه کردن این خط
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Updater, CommandHandler, MessageHandler, filters, CallbackContext
import logging

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
        """ورود به حساب اینستاگرام"""
        try:
            self.loader.context.login(username, password)
            logger.info("با موفقیت به اینستاگرام وارد شدیم")
            return True
        except Exception as e:
            logger.error(f"خطا در ورود به اینستاگرام: {e}")
            return False

    def sanitize_filename(self, filename: str) -> str:
        """پاکسازی نام فایل برای ذخیره سازی"""
        return re.sub(r'[\\/*?:"<>|]', '', filename)

    def download_media(self, url: str, filename: str = None) -> Optional[str]:
        """دانلود مدیا از URL"""
        try:
            response = self.session.get(url, headers=self.headers, stream=True, timeout=60)
            response.raise_for_status()

            if not filename:
                filename = os.path.basename(urlparse(url).path)

            filename = self.sanitize_filename(filename)
            
            if not os.path.splitext(filename)[1]:
                if 'image' in response.headers.get('content-type', ''):
                    filename += '.jpg'
                elif 'video' in response.headers.get('content-type', ''):
                    filename += '.mp4'

            os.makedirs('downloads', exist_ok=True)
            save_path = os.path.join('downloads', filename)

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)

            logger.info(f"مدیا با موفقیت دانلود شد: {save_path}")
            return save_path
        except Exception as e:
            logger.error(f"خطا در دانلود مدیا: {e}")
            return None

    def get_post_info(self, url: str) -> Tuple[List[Tuple[str, str, str]], str]:
        """دریافت اطلاعات پست"""
        try:
            shortcode = self.get_shortcode(url)
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
            
            media_list = []
            caption = post.caption if post.caption else ""
            
            if post.typename == 'GraphSidecar':
                for idx, node in enumerate(post.get_sidecar_nodes(), start=1):
                    if node.is_video:
                        media_url = node.video_url
                        media_type = 'video'
                        ext = '.mp4'
                    else:
                        media_url = node.display_url
                        media_type = 'photo'
                        ext = '.jpg'
                    
                    filename = f"{post.owner_username}_post_{post.shortcode}_{idx}{ext}"
                    media_list.append((media_url, media_type, filename))
            else:
                if post.is_video:
                    media_url = post.video_url
                    media_type = 'video'
                    ext = '.mp4'
                else:
                    media_url = post.url
                    media_type = 'photo'
                    ext = '.jpg'
                
                filename = f"{post.owner_username}_post_{post.shortcode}{ext}"
                media_list.append((media_url, media_type, filename))
            
            return media_list, caption
        except Exception as e:
            logger.error(f"خطا در دریافت اطلاعات پست: {e}")
            return [], ""

    def get_shortcode(self, url: str) -> str:
        """استخراج shortcode از URL"""
        pattern = r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv)/([^/?#&]+)'
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        raise ValueError("لینک اینستاگرام نامعتبر است.")

class TelegramBot:
    def __init__(self, token: str, insta_downloader: InstagramDownloader):
        self.token = token
        self.insta_downloader = insta_downloader
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        # ثبت هندلرها
        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(MessageHandler(filters.text & (~filters.command), self.handle_message))

    def start(self, update: Update, context: CallbackContext):
        """هندلر دستور /start"""
        welcome_message = """
        🤖 ربات دانلودر اینستاگرام 🤖

        لطفا لینک پست، ریلس، یا IGTV اینستاگرام را ارسال کنید.

        نکات:
        - لینک باید مستقیم از اینستاگرام باشد
        - برای پست‌های خصوصی، ربات باید با حساب اینستاگرام شما لاگین کرده باشد
        """
        update.message.reply_text(welcome_message)

    def handle_message(self, update: Update, context: CallbackContext):
        """هندلر پیام‌های کاربر"""
        text = update.message.text
        chat_id = update.message.chat_id
        
        if not self.is_valid_instagram_url(text):
            update.message.reply_text("لطفا یک لینک معتبر اینستاگرام ارسال کنید.")
            return
        
        try:
            update.message.reply_text("در حال پردازش لینک... لطفا صبر کنید.")
            
            if '/reel/' in text or '/reels/' in text:
                self.handle_reel(update, text)
            elif '/tv/' in text:
                self.handle_igtv(update, text)
            elif '/p/' in text:
                self.handle_post(update, text)
            else:
                update.message.reply_text("این نوع لینک پشتیبانی نمی‌شود.")
        
        except Exception as e:
            logger.error(f"خطا در پردازش لینک: {e}")
            update.message.reply_text(f"خطا در پردازش لینک: {str(e)}")

    def is_valid_instagram_url(self, url: str) -> bool:
        """بررسی معتبر بودن URL اینستاگرام"""
        patterns = [
            r'https?://(www\.)?instagram\.com/p/',
            r'https?://(www\.)?instagram\.com/reel/',
            r'https?://(www\.)?instagram\.com/tv/',
            r'https?://(www\.)?instagram\.com/reels/'
        ]
        return any(re.search(pattern, url) for pattern in patterns)

    def handle_post(self, update: Update, post_url: str):
        """پردازش پست اینستاگرام"""
        media_list, caption = self.insta_downloader.get_post_info(post_url)
        
        if not media_list:
            update.message.reply_text("خطا در دریافت پست. ممکن است پست خصوصی باشد.")
            return
        
        try:
            downloaded_files = []
            for media_url, media_type, filename in media_list:
                file_path = self.insta_downloader.download_media(media_url, filename)
                if file_path:
                    downloaded_files.append((file_path, media_type))
            
            if not downloaded_files:
                update.message.reply_text("خطا در دانلود محتوا")
                return
            
            self.send_media(update, downloaded_files, caption)
            
        finally:
            self.cleanup_files(downloaded_files)

    def handle_reel(self, update: Update, reel_url: str):
        """پردازش ریلس"""
        media_list, caption = self.insta_downloader.get_post_info(reel_url)  # IGTV و ریلس همانند پست پردازش می‌شوند
        
        if not media_list:
            update.message.reply_text("خطا در دریافت ریلس. ممکن است محتوا خصوصی باشد.")
            return
        
        try:
            downloaded_files = []
            for media_url, media_type, filename in media_list:
                file_path = self.insta_downloader.download_media(media_url, filename)
                if file_path:
                    downloaded_files.append((file_path, media_type))
            
            if not downloaded_files:
                update.message.reply_text("خطا در دانلود ریلس")
                return
            
            self.send_media(update, downloaded_files, caption)
            
        finally:
            self.cleanup_files(downloaded_files)

    def handle_igtv(self, update: Update, igtv_url: str):
        """پردازش IGTV"""
        self.handle_reel(update, igtv_url)  # پردازش همانند ریلس

    def send_media(self, update: Update, files: List[Tuple[str, str]], caption: str = ""):
        """ارسال مدیا به کاربر"""
        if len(files) == 1:
            file_path, media_type = files[0]
            try:
                with open(file_path, 'rb') as media_file:
                    if media_type == 'photo':
                        update.message.reply_photo(
                            photo=media_file,
                            caption=caption[:1000] if caption else None
                        )
                    else:
                        update.message.reply_video(
                            video=media_file,
                            caption=caption[:1000] if caption else None,
                            supports_streaming=True
                        )
            except Exception as e:
                logger.error(f"خطا در ارسال مدیا: {e}")
                update.message.reply_text("خطا در ارسال محتوا")
        else:
            media_group = []
            for idx, (file_path, media_type) in enumerate(files):
                try:
                    with open(file_path, 'rb') as media_file:
                        if media_type == 'photo':
                            media = InputMediaPhoto(
                                media=media_file,
                                caption=caption[:1000] if idx == 0 and caption else None
                            )
                        else:
                            media = InputMediaVideo(
                                media=media_file,
                                caption=caption[:1000] if idx == 0 and caption else None
                            )
                        media_group.append(media)
                except Exception as e:
                    logger.error(f"خطا در آماده‌سازی مدیا گروهی: {e}")
                    continue
            
            if media_group:
                try:
                    update.message.reply_media_group(media=media_group)
                except Exception as e:
                    logger.error(f"خطا در ارسال مدیا گروهی: {e}")
                    update.message.reply_text("خطا در ارسال محتوای چندگانه")

    def cleanup_files(self, files: List[Tuple[str, str]]):
        """پاکسازی فایل‌های موقت"""
        for file_path, _ in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"خطا در حذف فایل موقت: {e}")

    def start_bot(self):
        """شروع کار بات"""
        logger.info("ربات در حال اجرا...")
        self.updater.start_polling()
        self.updater.idle()

def main():
    # تنظیمات
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    INSTA_USERNAME = None  # اگر نیاز به لاگین باشد
    INSTA_PASSWORD = None  # اگر نیاز به لاگین باشد
    
    # ایجاد دانلودر اینستاگرام
    insta_downloader = InstagramDownloader()
    
    # اگر اطلاعات ورود اینستاگرام وجود دارد، لاگین کن
    if INSTA_USERNAME and INSTA_PASSWORD:
        if not insta_downloader.login(INSTA_USERNAME, INSTA_PASSWORD):
            logger.warning("نمی‌توان با اطلاعات ورود ارائه شده وارد شد. ادامه بدون لاگین...")
    
    # ایجاد و شروع بات تلگرام
    telegram_bot = TelegramBot(TELEGRAM_TOKEN, insta_downloader)
    telegram_bot.start_bot()

if __name__ == '__main__':
    main()
