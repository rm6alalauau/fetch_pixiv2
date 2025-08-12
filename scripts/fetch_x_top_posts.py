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
MAX_SCROLL_ATTEMPTS = 20 # 設定一個滾動上限，防止無限迴圈

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
            print("Initial page loaded. Starting scrape-while-scrolling process...")

            all_posts = []
            seen_tweet_links = set()
            scroll_attempts_left = MAX_SCROLL_ATTEMPTS

            # 【核心修改】使用 while 迴圈，邊滾動邊抓取，直到滿足條件
            while len(all_posts) < MAX_POSTS and scroll_attempts_left > 0:
                print(f"\n--- Current state: {len(all_posts)}/{MAX_POSTS} posts found. {scroll_attempts_left} scroll attempts left. ---")
                
                # 1. 抓取當前頁面上所有可見的推文
                tweet_elements = page.locator('article[data-testid="tweet"]').all()
                new_tweets_found_this_scroll = 0

                for tweet in tweet_elements:
                    post_data = {}
                    try:
                        # 首先獲取連結來去重
                        post_link = ""
                        link_element = tweet.locator('a[href*="/status/"]').first
                        if link_element.count() > 0:
                            href = link_element.get_attribute('href')
                            if href:
                                 post_link = f"https://x.com{href}"
                        
                        if not post_link or post_link in seen_tweet_links:
                            continue # 跳過已處理的推文

                        # 如果是新推文，則解析詳細資料
                        # 【核心修改 2】使用 .first 來解決 strict mode violation
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
                        new_tweets_found_this_scroll += 1
                        
                        if len(all_posts) >= MAX_POSTS:
                            break # 如果已達標，立即跳出內層迴圈

                    except Exception as e:
                        print(f"  - WARN: Skipping one tweet due to parsing error: {e}")

                print(f"  - Parsed {new_tweets_found_this_scroll} new tweets in this iteration.")

                # 如果已達標，跳出主迴圈
                if len(all_posts) >= MAX_POSTS:
                    print(f"Target of {MAX_POSTS} posts reached. Finishing.")
                    break
                
                # 2. 如果未達標，則向下滾動一次
                print("  - Scrolling down to load more...")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                scroll_attempts_left -= 1
                time.sleep(3) # 等待新內容載入

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
