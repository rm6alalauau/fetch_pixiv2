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
# 【修改點 1】確保關鍵字被正確編碼到 URL 中
TARGET_URL = f"https://x.com/search?q={urllib.parse.quote(SEARCH_KEYWORD)}&src=typed_query&f=top"
MAX_POSTS = 20

def main():
    if not all([APPS_SCRIPT_URL, X_APPS_SCRIPT_SECRET, AUTH_JSON_CONTENT]):
        print("❌ Missing required environment variables. Aborting.")
        return

    # 將從 Secret 讀取的 JSON 字串寫入暫存檔案
    with open("auth.json", "w") as f:
        f.write(AUTH_JSON_CONTENT)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()

        try:
            print(f"Navigating to: {TARGET_URL}")
            # 【修改點 2】放寬 goto 的等待條件，但增加總超時時間到 90 秒
            page.goto(TARGET_URL, timeout=90000)

            # 【修改點 3】這是最關鍵的修改！明確等待推文容器出現，而不是等網路靜止
            print("Waiting for tweet container to appear...")
            page.wait_for_selector('article[data-testid="tweet"]', timeout=60000)
            print("Tweet container found. Parsing tweets...")
            
            # 給頁面一點額外時間渲染動態內容
            time.sleep(3)

            tweet_elements = page.locator('article[data-testid="tweet"]').all()
            print(f"Found {len(tweet_elements)} potential tweets on the page.")

            all_posts = []
            for i, tweet in enumerate(tweet_elements[:MAX_POSTS]):
                post_data = {}
                try:
                    # 【修改點 4】對每個欄位的抓取進行更細緻的錯誤處理
                    post_data["Title"] = tweet.locator('div[data-testid="tweetText"]').inner_text(timeout=5000)
                    
                    author_name_element = tweet.locator('div[data-testid="User-Name"] a span').first
                    post_data["Author"] = author_name_element.inner_text(timeout=5000)
                    
                    author_handle = ""
                    handle_element = tweet.locator('div[data-testid="User-Name"] a > div > span').first
                    if handle_element:
                        author_handle = handle_element.inner_text(timeout=5000)
                    post_data["AuthorProfile"] = f"https://x.com/{author_handle.replace('@', '')}" if author_handle else ""
                    
                    post_link = ""
                    link_element = tweet.locator('a[href*="/status/"]').first
                    if link_element:
                        href = link_element.get_attribute('href')
                        if href:
                             post_link = f"https://x.com{href}"
                    post_data["Link"] = post_link

                    image_url = ""
                    image_element = tweet.locator('div[data-testid="tweetPhoto"] img').first
                    if image_element:
                        image_url = image_element.get_attribute('src', timeout=5000)
                    post_data["Image"] = image_url
                    post_data["Thumbnail"] = image_url

                    hashtags_elements = tweet.locator('a[href*="/hashtag/"]').all()
                    post_data["Hashtag"] = " ".join([h.inner_text(timeout=2000) for h in hashtags_elements])
                    
                    post_data["Time"] = "" # 時間依然較難抓取，暫時留空

                    all_posts.append(post_data)
                    print(f"  - Parsed tweet #{i+1}: {post_data['Title'][:30]}...")

                except Exception as e:
                    print(f"  - WARN: Skipping a tweet at index {i} due to parsing error: {e}")
            
            print(f"\n✅ Successfully parsed {len(all_posts)} top tweets.")

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
