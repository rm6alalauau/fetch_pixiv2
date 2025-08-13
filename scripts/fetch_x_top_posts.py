import os
import json
import time
import requests
from playwright.sync_api import sync_playwright, Page
import urllib.parse

# --- 從 GitHub Secrets 讀取秘密 ---
APPS_SCRIPT_URL = os.getenv('APPS_SCRIPT_URL')
X_APPS_SCRIPT_SECRET = os.getenv('X_APPS_SCRIPT_SECRET')
AUTH_JSON_CONTENT = os.getenv('AUTH_JSON_CONTENT')

# --- 抓取配置 ---
SEARCH_KEYWORD = "#ブラダス2"
TARGET_URL = f"https://x.com/search?q={urllib.parse.quote(SEARCH_KEYWORD)}&src=typed_query&f=top"
MAX_POSTS = 20
MAX_SCROLL_ATTEMPTS = 30

# --- 【最終版】輔助函式，能夠同時處理圖片和影片 ---
def parse_and_add_tweets(page: Page, all_posts: list, seen_tweet_links: set):
    new_tweets_found = 0
    tweet_elements = page.locator('article[data-testid="tweet"]').all()

    for tweet in tweet_elements:
        if len(all_posts) >= MAX_POSTS:
            break

        post_data = {}
        try:
            post_link = ""
            link_element = tweet.locator('a[href*="/status/"]').first
            if link_element.count() > 0:
                href = link_element.get_attribute('href')
                if href:
                     post_link = f"https://x.com{href}"
            
            if not post_link or post_link in seen_tweet_links:
                continue

            post_data["Link"] = post_link
            post_data["Title"] = tweet.locator('div[data-testid="tweetText"]').first.inner_text(timeout=5000)
            post_data["Author"] = tweet.locator('div[data-testid="User-Name"] a span').first.inner_text(timeout=5000)
            
            handle_element = tweet.locator('div[data-testid="User-Name"] a > div > span').first
            author_handle = handle_element.inner_text(timeout=5000) if handle_element.count() > 0 else ""
            post_data["AuthorProfile"] = f"https://x.com/{author_handle.replace('@', '')}"
            
            # 【核心修改】智能圖片/影片預覽圖抓取邏輯
            image_url = ""
            # 1. 首先，嘗試尋找常規圖片
            photo_locator = tweet.locator('div[data-testid="tweetPhoto"] img').first
            if photo_locator.count() > 0:
                image_url = photo_locator.get_attribute('src', timeout=5000)
            else:
                # 2. 如果找不到常規圖片，再嘗試尋找影片的預覽圖
                # 影片預覽圖通常在一個不同的容器裡
                video_thumb_locator = tweet.locator('div[data-testid="videoPlayer"] img[src*="pbs.twimg.com"]').first
                if video_thumb_locator.count() > 0:
                    image_url = video_thumb_locator.get_attribute('src', timeout=5000)
                    print(f"  - INFO: Found a video thumbnail for post: {post_link}")
            
            post_data["Image"] = image_url
            post_data["Thumbnail"] = image_url

            hashtags_elements = tweet.locator('a[href*="/hashtag/"]').all()
            post_data["Hashtag"] = " ".join([h.inner_text(timeout=2000) for h in hashtags_elements])
            post_data["Time"] = ""

            all_posts.append(post_data)
            seen_tweet_links.add(post_link)
            new_tweets_found += 1

        except Exception as e:
            print(f"  - WARN: Skipping one tweet due to parsing error: {e}")
            
    return new_tweets_found

# --- 主函式 (維持不變) ---
def main():
    if not all([APPS_SCRIPT_URL, X_APPS_SCRIPT_SECRET, AUTH_JSON_CONTENT]):
        print("❌ Missing required environment variables. Aborting.")
        return

    with open("auth.json", "w") as f:
        f.write(AUTH_JSON_CONTENT)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()

        try:
            print(f"Navigating to: {TARGET_URL}")
            page.goto(TARGET_URL, timeout=90000)
            page.wait_for_selector('article[data-testid="tweet"]', timeout=60000)
            
            print("Initial page loaded. Giving it a moment to settle...")
            time.sleep(5) 

            all_posts = []
            seen_tweet_links = set()
            scroll_attempts_left = MAX_SCROLL_ATTEMPTS
            
            print("\n--- Starting intelligent scroll-and-parse loop ---")
            while len(all_posts) < MAX_POSTS and scroll_attempts_left > 0:
                print(f"Current state: {len(all_posts)}/{MAX_POSTS} posts. Parsing visible tweets...")
                
                newly_found_count = parse_and_add_tweets(page, all_posts, seen_tweet_links)
                print(f"  - Found {newly_found_count} new tweets in this iteration.")

                if len(all_posts) >= MAX_POSTS:
                    print(f"Target of {MAX_POSTS} posts reached. Finishing.")
                    break
                
                last_tweet_on_page = page.locator('article[data-testid="tweet"]').last
                if last_tweet_on_page.count() > 0:
                    print("  - Scrolling to the last found tweet to load more...")
                    last_tweet_on_page.scroll_into_view_if_needed()
                    scroll_attempts_left -= 1
                    time.sleep(3)
                else:
                    print("  - No more tweets found on page. Stopping.")
                    break

            print(f"\n✅ Finished scraping process. Total unique tweets found: {len(all_posts)}")

            if all_posts:
                payload = {"secret": X_APPS_SCRIPT_SECRET, "data": all_posts}
                headers = {"Content-Type": "application/json"}
                print(f"Posting {len(all_posts)} posts to Apps Script...")
                response = requests.post(APPS_SCRIPT_URL, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers)
                response.raise_for_status()
                print(f"✅ Successfully posted data. Response: {response.text}")

        except Exception as e:
            print(f"❌ An critical error occurred during scraping: {e}")
            page.screenshot(path="error_screenshot.png")
            print("📸 An error screenshot has been saved.")
            raise e
        finally:
            browser.close()

if __name__ == "__main__":
    main()
