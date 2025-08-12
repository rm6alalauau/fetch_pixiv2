import os
import json
import time
import requests
from playwright.sync_api import sync_playwright
import urllib.parse

# --- 從 GitHub Secrets 讀取秘密 ---
APPS_SCRIPT_URL = os.getenv('APPS_SCRIPT_URL')
X_APPS_SCRIPT_SECRET = os.getenv('X_APPS_SCRIPT_SECRET')
AUTH_JSON_CONTENT = os.getenv('AUTH_JSON_CONTENT')

# --- 抓取配置 ---
SEARCH_KEYWORD = "#ブラダス2"
TARGET_URL = f"https://x.com/search?q={urllib.parse.quote(SEARCH_KEYWORD)}&src=typed_query&f=top"
MAX_POSTS = 20
SCROLL_ATTEMPTS = 15 # 【新設定】定義要向下滾動幾次來載入更多內容

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
            print("Initial page loaded. Starting to scroll down to load more content...")

            # 【核心修改 1】加入滾動迴圈
            for i in range(SCROLL_ATTEMPTS):
                print(f"  - Scrolling down... (Attempt {i + 1}/{SCROLL_ATTEMPTS})")
                # 執行 JS 來滾動到頁面底部
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                # 等待 2-3 秒讓新內容載入
                time.sleep(3)
            
            print("\nFinished scrolling. Now parsing all found tweets...")

            tweet_elements = page.locator('article[data-testid="tweet"]').all()
            print(f"Found {len(tweet_elements)} potential tweets on the page after scrolling.")

            all_posts = []
            seen_tweet_links = set() # 【核心修改 2】用於防止重複

            for i, tweet in enumerate(tweet_elements):
                if len(all_posts) >= MAX_POSTS:
                    print(f"Reached target of {MAX_POSTS} posts. Stopping parse.")
                    break
                
                post_data = {}
                try:
                    # 首先嘗試獲取獨一無二的連結來判斷是否重複
                    post_link = ""
                    link_element = tweet.locator('a[href*="/status/"]').first
                    if link_element.count() > 0:
                        href = link_element.get_attribute('href')
                        if href:
                             post_link = f"https://x.com{href}"
                    
                    if not post_link or post_link in seen_tweet_links:
                        continue # 如果沒有連結或已處理過，則跳過

                    # 解析其他內容
                    post_data["Link"] = post_link
                    post_data["Title"] = tweet.locator('div[data-testid="tweetText"]').inner_text(timeout=5000)
                    post_data["Author"] = tweet.locator('div[data-testid="User-Name"] a span').first.inner_text(timeout=5000)
                    
                    handle_element = tweet.locator('div[data-testid="User-Name"] a > div > span').first
                    author_handle = handle_element.inner_text(timeout=5000) if handle_element.count() > 0 else ""
                    post_data["AuthorProfile"] = f"https://x.com/{author_handle.replace('@', '')}"
                    
                    # 【核心修改 3】更穩健的圖片處理
                    image_url = ""
                    image_locator = tweet.locator('div[data-testid="tweetPhoto"] img').first
                    if image_locator.count() > 0: # 先判斷元素是否存在
                        image_url = image_locator.get_attribute('src', timeout=5000)
                    post_data["Image"] = image_url
                    post_data["Thumbnail"] = image_url

                    hashtags_elements = tweet.locator('a[href*="/hashtag/"]').all()
                    post_data["Hashtag"] = " ".join([h.inner_text(timeout=2000) for h in hashtags_elements])
                    post_data["Time"] = ""

                    all_posts.append(post_data)
                    seen_tweet_links.add(post_link) # 標記為已處理
                    print(f"  - Parsed tweet #{len(all_posts)}: {post_data['Title'][:30]}...")

                except Exception as e:
                    print(f"  - WARN: Skipping a tweet at index {i} due to parsing error: {e}")
            
            print(f"\n✅ Successfully parsed {len(all_posts)} unique top tweets.")

            if all_posts:
                # 後續邏輯不變
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
