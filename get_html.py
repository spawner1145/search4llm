import asyncio
import httpx
from playwright.async_api import async_playwright
import logging
import random
import ssl

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
MAX_RETRIES = 2 # httpx 重试次数
HTTPX_TIMEOUT = 15

# httpx 使用的 Headers
HTTPX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

async def wait_with_backoff(attempt: int, base_delay: float = 0.5, max_delay: float = 5.0):
    """根据尝试次数进行指数退避等待，并加入随机抖动。"""
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    jitter = delay * random.uniform(0.1, 0.5)
    wait_time = delay + jitter
    logging.info(f"等待 {wait_time:.2f} 秒后重试...")
    await asyncio.sleep(wait_time)

async def get_html(url: str) -> str | None:
    logging.info(f"开始尝试获取 URL 的 HTML: {url}")
    html_code = None

    # httpx
    logging.info("--- 方法: httpx ---")
    try:
        async with httpx.AsyncClient(headers=HTTPX_HEADERS, follow_redirects=True, timeout=HTTPX_TIMEOUT, verify=ssl_context) as client:
            for attempt in range(1, MAX_RETRIES + 1):
                logging.info(f"httpx 第 {attempt}/{MAX_RETRIES} 次尝试...")
                try:
                    response = await client.get(url)
                    final_url = str(response.url)
                    logging.info(f"httpx 收到状态码: {response.status_code}, 最终 URL: {final_url}")

                    if response.is_success:
                        try:
                            content_type = response.headers.get('content-type', '').lower()
                            is_html = 'text/html' in content_type
                            is_json = 'application/json' in content_type
                            raw_text = response.text

                            valid_content = False
                            if is_html:
                                if raw_text and len(raw_text.strip()) > 150 and '<html' in raw_text.lower() and '</html>' in raw_text.lower():
                                    if '<script' in raw_text.lower() and ('loading' in raw_text.lower() or 'document.write' in raw_text.lower() or 'app-root' in raw_text):
                                        logging.warning(f"httpx 获取了 HTML，但似乎需要 JS 渲染。将尝试 Playwright。")
                                    else:
                                        valid_content = True
                                        logging.info(f"httpx 在第 {attempt} 次尝试成功获取有效 HTML。")
                                else:
                                    logging.warning(f"httpx 获取的 HTML 内容无效、过短或结构不完整。")
                            elif is_json:
                                if raw_text and len(raw_text.strip()) > 2:
                                    valid_content = True
                                    logging.info(f"httpx 在第 {attempt} 次尝试成功获取有效 JSON。")
                                else:
                                    logging.warning(f"httpx 获取的 JSON 内容无效或为空。")
                            elif raw_text and len(raw_text.strip()) > 50:
                                valid_content = True
                                logging.info(f"httpx 在第 {attempt} 次尝试成功获取到类型为 {content_type} 的非空内容。")
                            else:
                                logging.warning(f"httpx 获取的内容为空或过短 (类型: {content_type})。")

                            if valid_content:
                                html_code = raw_text
                            else:
                                html_code = None

                        except Exception as process_err:
                            logging.warning(f"httpx 处理响应内容时出错: {process_err}")
                            html_code = None
                    else:
                        logging.warning(f"httpx 第 {attempt} 次尝试失败，状态码: {response.status_code}")
                        html_code = None

                    if html_code is None and attempt < MAX_RETRIES:
                        await wait_with_backoff(attempt)
                    elif html_code is not None:
                        break

                except httpx.TimeoutException:
                    logging.warning(f"httpx 第 {attempt} 次尝试超时 (超过 {HTTPX_TIMEOUT} 秒)。")
                    html_code = None
                    if attempt < MAX_RETRIES: await wait_with_backoff(attempt)
                except httpx.RequestError as e:
                    logging.error(f"httpx 第 {attempt} 次尝试发生请求错误: {e}")
                    html_code = None
                    if attempt < MAX_RETRIES: await wait_with_backoff(attempt)
                except Exception as e:
                    logging.error(f"httpx 第 {attempt} 次尝试发生未知错误: {e}")
                    html_code = None
                    if attempt < MAX_RETRIES: await wait_with_backoff(attempt)

            if html_code: return html_code # 如果 httpx 成功了

    except Exception as client_init_err:
        logging.error(f"初始化 httpx 客户端时出错: {client_init_err}")

    logging.warning("httpx 方法未能获取有效 HTML 或内容。将使用 Playwright")
    html_code = None

    # Playwright
    logging.info("--- 方法: Playwright---")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        page = await context.new_page()

        async def log_request(request):
            print(f"Request: {request.url}")
        page.on("request", log_request)

        params = {"q": "test"}
        headers = {"User-Agent": "Mozilla/5.0"}
        await context.set_extra_http_headers(headers)

        full_url = f"{url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
        print(f"Visiting: {full_url}")

        response = await page.goto(full_url, wait_until="networkidle")

        content = await page.content()
        #print(content)

        final_url = page.url
        print(f"Final URL: {final_url}")

        await context.close()
        await browser.close()
        return content

async def main():
    test_urls = [
        "https://httpbin.org/html",
        "https://quotes.toscrape.com/js/",
        "https://httpbin.org/delay/5",
        "https://httpbin.org/redirect/3",
        "https://jigsaw.w3.org/HTTP/Basic/",
        "https://expired.badssl.com/",
        "https://dqxy.ahu.edu.cn/2023/0721/c6135a312651/page.htm"
    ]

    for test_url in test_urls:
        print(f"\n{'='*10} 测试 URL: {test_url} {'='*10}")
        html_content = await get_html(test_url)

        if html_content:
            print(f"成功获取 HTML 内容 (前 300 字符):")
            print(html_content[:300].strip() + "...")
        else:
            print(f"未能获取 URL 的 HTML 内容: {test_url}")
        print(f"{'='*30}\n")
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")