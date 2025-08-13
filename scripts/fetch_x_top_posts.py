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
MAX_SCROLL_ATTEMPTS = 60 # 保持較高的滾動次數

# --- 【新】輔助函式，專門用來解析當前可見的推文 ---
def parse_and_add_tweets(page: Page, all_posts: list, seen_tweet_links: set):
    """解析當前頁面上所有可見的、不重複的推文，並將其加入 all_posts 列表。"""
    new_tweets_found = 0
    tweet_elements = page.locator('article[data-testid="tweet"]').all()

    for tweet in tweet_elements:
        if len(all_posts) >= MAX_POSTS:
            break # 如果已達標，提前結束

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
            
            image_url = ""
            image_locator = tweet.locator('div[data-testid="tweetPhoto"] img').first
            if image_locator.count() > 0:
                image_url = image_locator.get_attribute('src', timeout=5000)
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

# --- 主函式重構 ---
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
            print("Initial page loaded.")

            all_posts = []
            seen_tweet_links = set()
            
            # 【核心修改 1】進行首次抓取，捕獲熱度最高的內容
            print("\n--- Performing Initial Parse (Before Scrolling) ---")
            initial_found_count = parse_and_add_tweets(page, all_posts, seen_tweet_links)
            print(f"  - Found {initial_found_count} initial tweets.")

            # 【核心修改 2】如果數量不夠，再開始滾動
            scroll_attempts_left = MAX_SCROLL_ATTEMPTS
            if len(all_posts) < MAX_POSTS:
                print("\n--- Starting Scroll-and-Parse Loop ---")
                
                while len(all_posts) < MAX_POSTS and scroll_attempts_left > 0:
                    print(f"Current state: {len(all_posts)}/{MAX_POSTS} posts. Scrolling down... ({scroll_attempts_left} attempts left)")
                    
                    # 1. 滾動
                    page.evaluate("window.scrollBy(0, window.innerHeight)") # 每次滾動一個螢幕的高度
                    scroll_attempts_left -= 1
                    time.sleep(3)

                    # 2. 抓取新載入的內容
                    newly_found_count = parse_and_add_tweets(page, all_posts, seen_tweet_links)
                    print(f"  - Found {newly_found_count} new tweets in this iteration.")

            # 迴圈結束後，進行總結
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
