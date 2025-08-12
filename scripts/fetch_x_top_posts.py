import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

# --- 從 GitHub Secrets 讀取秘密 ---
APPS_SCRIPT_URL = os.getenv('APPS_SCRIPT_URL')
X_APPS_SCRIPT_SECRET = os.getenv('X_APPS_SCRIPT_SECRET')
AUTH_JSON_CONTENT = os.getenv('AUTH_JSON_CONTENT') # 我們會從 Secret 讀取 auth.json 的內容

# --- 抓取配置 ---
SEARCH_KEYWORD = "#ブラダス2"
TARGET_URL = f"https://x.com/search?q={SEARCH_KEYWORD}&src=typed_query&f=top"
MAX_POSTS = 20 # 希望抓取的文章筆數

def main():
    if not all([APPS_SCRIPT_URL, X_APPS_SCRIPT_SECRET, AUTH_JSON_CONTENT]):
        print("❌ Missing required environment variables. Aborting.")
        return

    # 將從 Secret 讀取的 JSON 字串寫入暫存檔案
    with open("auth.json", "w") as f:
        f.write(AUTH_JSON_CONTENT)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # 在伺服器上執行需設為 True
        # 載入登入狀態
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()

        try:
            print(f"Navigating to: {TARGET_URL}")
            page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
            time.sleep(5) # 等待動態內容（例如圖片）載入

            # 等待推文的容器出現
            page.wait_for_selector('article[data-testid="tweet"]', timeout=30000)
            
            # 從頁面中抓取所有推文元素
            tweet_elements = page.locator('article[data-testid="tweet"]').all()
            print(f"Found {len(tweet_elements)} potential tweets on the page.")

            all_posts = []
            for i, tweet in enumerate(tweet_elements[:MAX_POSTS]):
                try:
                    # X 的 HTML 結構很複雜，這裡的 selector 可能需要依實際情況調整
                    # 這是最脆弱的部分
                    title_text = tweet.locator('div[data-testid="tweetText"]').inner_text()
                    author_name = tweet.locator('div[data-testid="User-Name"] a').first.inner_text()
                    author_handle_element = tweet.locator('div[data-testid="User-Name"] span').filter(has_text="@").first
                    author_handle = author_handle_element.inner_text()
                    
                    # 取得文章連結
                    post_link = ""
                    link_element = tweet.locator('a[href*="/status/"]').first
                    if link_element:
                        href = link_element.get_attribute('href')
                        if href:
                             post_link = f"https://x.com{href}"

                    # 取得圖片
                    image_url = ""
                    image_element = tweet.locator('div[data-testid="tweetPhoto"] img').first
                    if image_element:
                        image_url = image_element.get_attribute('src')
                    
                    # 取得Hashtag
                    hashtags_elements = tweet.locator('a[href*="/hashtag/"]').all()
                    hashtags = " ".join([h.inner_text() for h in hashtags_elements])

                    post_data = {
                        "Title": title_text,
                        "Link": post_link,
                        "Image": image_url,
                        "Thumbnail": image_url, # 直接用大圖作為縮圖
                        "Author": author_name,
                        "AuthorProfile": f"https://x.com/{author_handle.replace('@', '')}",
                        "Hashtag": hashtags,
                        "Time": "" # 從頁面抓時間較複雜，可暫時留空或後續再優化
                    }
                    all_posts.append(post_data)

                except Exception as e:
                    print(f"Skipping a tweet due to parsing error: {e}")
            
            print(f"✅ Successfully parsed {len(all_posts)} top tweets.")

            # --- 後續發送到 Apps Script 的邏輯 (與您現有的完全相同) ---
            if all_posts:
                payload = {"secret": X_APPS_SCRIPT_SECRET, "data": all_posts}
                headers = {"Content-Type": "application/json"}
                print(f"Posting {len(all_posts)} posts to Apps Script...")
                response = requests.post(APPS_SCRIPT_URL, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers)
                response.raise_for_status()
                print(f"✅ Successfully posted data. Response: {response.text}")

        except Exception as e:
            print(f"❌ An error occurred during scraping: {e}")
            # 發生錯誤時截圖，方便除錯
            page.screenshot(path="error_screenshot.png")
            raise e
        finally:
            browser.close()

if __name__ == "__main__":
    main()
