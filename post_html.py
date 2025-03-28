import asyncio
import httpx
from playwright.async_api import async_playwright
import logging
import random
import ssl

# 配置日志格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 创建并配置 SSL 上下文，忽略证书验证
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

async def wait_with_backoff(attempt, base_delay=0.5, max_delay=5.0):
    """根据尝试次数进行指数退避等待，并加入随机抖动"""
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    jitter = delay * random.uniform(0.1, 0.5)
    wait_time = delay + jitter
    logging.info(f"等待 {wait_time:.2f} 秒后重试...")
    await asyncio.sleep(wait_time)

async def is_cloudflare_response(response):
    """检测响应是否为 Cloudflare 防护页面"""
    # 检查响应头
    headers = response.headers
    if 'server' in headers and 'cloudflare' in headers['server'].lower():
        logging.info("检测到 Cloudflare 防护（基于 Server 头）。")
        return True
    if 'cf-ray' in headers:
        logging.info("检测到 Cloudflare 防护（基于 cf-ray 头）。")
        return True

    # 检查响应内容
    content = response.text.lower()
    if 'cloudflare' in content or 'access denied' in content or 'cf-ray' in content:
        logging.info("检测到 Cloudflare 防护（基于内容）。")
        return True

    return False

async def post_html(url, payload=None, proxy=None, headers=None, skip_httpx=False, timeout=30, httpx_retries=2):
    """使用 POST 请求获取响应内容，支持传入 payload，默认先尝试 httpx，若检测到 CF 或 JS 反爬则使用 Playwright"""
    logging.info(f"开始尝试通过 POST 获取 URL 的响应: {url}")
    response_content = None

    # 默认的 httpx 请求头
    default_httpx_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # 如果传入了 headers，则合并默认 headers 和自定义 headers，自定义 headers 优先
    httpx_headers = default_httpx_headers.copy()
    if headers:
        httpx_headers.update(headers)

    # 如果 skip_httpx 为 False，先尝试 httpx
    if not skip_httpx:
        logging.info("--- 方法: httpx (POST) ---")
        try:
            proxies = {"http://": proxy, "https://": proxy} if proxy else None
            async with httpx.AsyncClient(
                headers=httpx_headers,
                follow_redirects=True,
                timeout=timeout,
                verify=ssl_context,
                proxies=proxies
            ) as client:
                for attempt in range(1, httpx_retries + 1):
                    logging.info(f"httpx 第 {attempt}/{httpx_retries} 次尝试 (POST)...")
                    try:
                        # 使用 POST 请求，传入 payload
                        response = await client.post(url, data=payload if payload else {})
                        final_url = str(response.url)
                        logging.info(f"httpx 收到状态码: {response.status_code}, 最终 URL: {final_url}")

                        # 检测是否为 Cloudflare 防护页面
                        if await is_cloudflare_response(response):
                            logging.info("检测到 Cloudflare 防护，切换到 Playwright。")
                            break  # 跳出 httpx 重试循环，直接进入 Playwright

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
                                            logging.warning(f"httpx 获取了 HTML，但检测到 JS 渲染特征（例如 'loading' 或 'document.write'）。将尝试 Playwright。")
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
                                    response_content = raw_text
                                else:
                                    response_content = None

                            except Exception as process_err:
                                logging.warning(f"httpx 处理响应内容时出错: {process_err}")
                                response_content = None
                        else:
                            logging.warning(f"httpx 第 {attempt} 次尝试失败，状态码: {response.status_code}")
                            response_content = None

                        if response_content is None and attempt < httpx_retries:
                            await wait_with_backoff(attempt)
                        elif response_content is not None:
                            break

                    except httpx.TimeoutException:
                        logging.warning(f"httpx 第 {attempt} 次尝试超时 (超过 {timeout} 秒)。")
                        response_content = None
                        if attempt < httpx_retries: await wait_with_backoff(attempt)
                    except httpx.RequestError as e:
                        logging.error(f"httpx 第 {attempt} 次尝试发生请求错误: {e}")
                        response_content = None
                        if attempt < httpx_retries: await wait_with_backoff(attempt)
                    except Exception as e:
                        logging.error(f"httpx 第 {attempt} 次尝试发生未知错误: {e}")
                        response_content = None
                        if attempt < httpx_retries: await wait_with_backoff(attempt)

                if response_content: return response_content  # 如果 httpx 成功，返回响应内容

        except Exception as client_init_err:
            logging.error(f"初始化 httpx 客户端时出错: {client_init_err}")

        logging.warning("httpx 方法未能获取有效响应或检测到反爬机制。将使用 Playwright")
        response_content = None

    # Playwright 方法（如果 skip_httpx=True 或 httpx 失败/检测到 CF）
    logging.info("--- 方法: Playwright (POST) ---")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            proxy={"server": proxy} if proxy else None
        )
        default_playwright_headers = {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        playwright_headers = headers if headers else default_playwright_headers
        context = await browser.new_context(
            user_agent=playwright_headers.get("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"),
            extra_http_headers=playwright_headers,
            ignore_https_errors=True
        )
        page = await context.new_page()

        async def log_request(request):
            print(f"请求: {request.url}")
        page.on("request", log_request)

        print(f"正在通过 POST 访问: {url}")
        response = await page.request.post(url, data=payload if payload else {}, headers=playwright_headers)
        response_content = await response.text()
        final_url = response.url
        print(f"最终 URL: {final_url}")

        await context.close()
        await browser.close()
        return response_content

async def main():
    """主函数，测试多个 URL 的 POST 响应获取"""
    test_urls = [
        "https://httpbin.org/post",
        "https://postman-echo.com/post",
        "https://reqres.in/api/users",
        "https://luxmix.top/",  # 添加一个可能有 CF 防护的 URL 用于测试
    ]

    proxy = "http://127.0.0.1:7890"
    test_payload = {
        "username": "test_user",
        "password": "123456"
    }
    test_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
        "Custom-Header": "Test-Value"
    }

    for test_url in test_urls:
        print(f"\n{'='*10} 测试 URL: {test_url} {'='*10}")
        response_content = await post_html(test_url, payload=test_payload, proxy=proxy, headers=test_headers)
        if response_content:
            print(f"成功获取响应内容 (前 300 字符):")
            print(response_content[:300].strip() + "...")
        else:
            print(f"未能获取 URL 的响应内容: {test_url}")
        print(f"{'='*30}\n")
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")