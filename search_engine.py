"""
这里定义了三个异步函数
searx_search: 使用searx(可能搜索结果比较少)
baidu_search: 使用百度搜索引擎进行搜索(出来的网址全都需要重定向)
edge_search: 使用edge搜索引擎进行搜索(恶心的反爬机制导致我只能用playwright,速度肯定更慢)
都是异步的,所以前面都要await,接受参数query和top_n(默认10),返回结果列表和url列表
"""
import httpx
import asyncio
from bs4 import BeautifulSoup
import time
from urllib.parse import quote
from playwright.async_api import async_playwright
import random
import re

async def fetch_url(url, headers, proxy=None):
    proxies = {"http://": proxy, "https://": proxy} if proxy else None
    async with httpx.AsyncClient(proxies=proxies) as client:
        response = await client.get(url, headers=headers)
        return response.text

def extract_div_contents(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    result_op_divs = soup.find_all('div', class_='result-op c-container new-pmd')
    result_xpath_log_divs = soup.find_all('div', class_='result c-container xpath-log new-pmd')
    
    entries = []
    
    for div in result_op_divs + result_xpath_log_divs:
        title_tag = div.find('h3')
        title = title_tag.get_text(strip=True) if title_tag else "无标题"
        link_tag = div.find('a', href=True)
        link = link_tag['href'] if link_tag else "无链接"
        
        all_texts = [text for text in div.stripped_strings if text != title]
        content = ' '.join(all_texts)
        
        content = re.sub(r'UTC\+8(\d{5}:\d{2}:\d{2})', lambda x: 'UTC+8 ' + ':'.join([x.group(1)[i:i+2] for i in range(0, len(x.group(1)), 2)]).lstrip(':'), content)
        content = re.sub(r'(\d{2}:\d{2})(\d{4}-\d{2}-\d{2})', r'\1 \2', content)
        content = re.sub(r'(\d{2}) (\d{2}) : (\d{2}) (\d{2}) : (\d{2}) (\d{2})', r'\1:\3:\5', content)
        
        entries.append({
            'title': title,
            'link': link,
            'content': content
        })
    
    return entries

async def searx_search(query, top_n=20, proxy=None):
    url = 'https://searx.bndkt.io/search'
    current_timestamp = int(time.time())
    
    params = {
        'q': query,
        'categories': 'general',
        'language': 'zh-CN',
        'time_range': '',
        'safesearch': '0',
        'theme': 'simple',
        'pageno': 1
    }

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": "_pk_id.3.9c95=99d38b3e33bd1ecf.1738772334.; _pk_ses.3.9c95=1",
        "DNT": "1",
        "Host": "searx.bndkt.io",
        "Origin": "null",
        "Sec-Ch-Ua": "\"Not A(Brand\";v=\"8\", \"Chromium\";v=\"132\", \"Microsoft Edge\";v=\"132\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": "\"Windows\"",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "X-Custom-Time": str(current_timestamp),
    }

    results = []
    urls = []
    page = 1
    max_retries = 10

    proxies = {"http://": proxy, "https://": proxy} if proxy else None
    async with httpx.AsyncClient(proxies=proxies) as client:
        while len(urls) < top_n:
            retry_count = 0
            articles = None
            
            while retry_count < max_retries:
                try:
                    params['pageno'] = page
                    response = await client.get(url, params=params, headers=headers)
                    response.raise_for_status()

                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.find_all('article', class_='result result-default category-general')

                    if articles:
                        break
                    
                    retry_count += 1
                    print(f"第 {page} 页无内容，第 {retry_count} 次重试...")
                    await asyncio.sleep(1)

                except httpx.HTTPStatusError as exc:
                    print(f"HTTP错误: {exc}")
                    print(f"响应内容: {exc.response.text}")
                    return f"搜索失败: {str(exc)}", []
                except httpx.RequestError as exc:
                    print(f"请求错误: {exc}")
                    return f"请求失败: {str(exc)}", []
                except Exception as e:
                    print(f"未知错误: {e}")
                    return f"发生未知错误: {str(e)}", []

            if not articles:
                print(f"第 {page} 页重试 {max_retries} 次后仍无内容，结束搜索")
                break

            for article in articles:
                title_tag = article.find('h3')
                title = title_tag.get_text(strip=True) if title_tag else '无标题'

                a_tag = article.find('a', class_='url_header')
                link = a_tag['href'] if a_tag and 'href' in a_tag.attrs else '无链接'

                content_tag = article.find('p', class_='content')
                content = content_tag.get_text(strip=True) if content_tag else '无内容'

                results.append(f"标题: {title}\n链接: {link}\n内容: {content}\n{'-'*20}")
                if link != '无链接' and link.startswith(('http://', 'https://')):
                    urls.append(link)

                if len(urls) >= top_n:
                    break

            page += 1

    final = "searx搜索结果:\n" + "\n".join(results)
    return final, urls[:top_n]

async def baidu_search(query, top_n=20, proxy=None):
    current_timestamp = int(time.time())
    base_url = "https://www.baidu.com/s"
    query_encoded = quote(query.encode('utf-8', 'ignore'))
    
    params = {
        'wd': query_encoded,
        'pn': 0,  # Baidu分页参数，从0开始，每页10条
        'ie': 'utf-8'
    }

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "identity",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Connection": "keep-alive",
        "Cookie": "BAIDUID_BFESS=A66237379B97E6A261B58CF57A599B36:FG=1; BAIDU_WISE_UID=wapp_1735376969138_24; ZFY=SAnc8iRNM:ANXuj2oLMz5qIRu8biHnpXnJWjpW7TDpqQ:C; __bid_n=19411378e1092166a470ad; BDUSS=hrYmdrV3J6YURhcXNVdmhEdzl6R285cXlUOEUxTjljVThOZFlPdkt1ck1PTHhuSVFBQUFBJCQAAAAAAAAAAAEAAAC8k8VDx-W0v7XE0MfQxzIwMDkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMynlGfMp5RnWm; BDUSS_BFESS=hrYmdrV3J6YURhcXNVdmhEdzl6R285cXlUOEUxTjljVThOZFlPdkt1ck1PTHhuSVFBQUFBJCQAAAAAAAAAAAEAAAC8k8VDx-W0v7XE0MfQxzIwMDkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMynlGfMp5RnWm; RT=\"z=1&dm=baidu.com&si=67fe5ea0-9903-498c-8a2c-caac8abb3423&ss=m6rr8uo8&sl=2&tt=6lh&bcn=https%3A%2F%2Ffclog.baidu.com%2Flog%2Fweirwood%3Ftype%3Dperf&ld=6js&ul=82y&hd=838\"; BIDUPSID=A66237379B97E6A261B58CF57A599B36; PSTM=1738765634; BDRCVFR[BIVAaPonX6T]=-_EV5wtlMr0mh-8uz4WUvY; H_PS_PSSID=61027_61672_61987; BD_UPN=12314753; BA_HECTOR=ak0h04a58k80a0a1a42h00a08krj591jq6ta41v; delPer=0; BD_CK_SAM=1; PSINO=3; BDORZ=FFFB88E999055A3F8A630C64834BD6D0; channel=bing; baikeVisitId=ed9be3e1-1a99-40db-ba9e-5fb15086499e; sugstore=1; H_PS_645EC=b0c8DXwu1zardcmOPhN4OqPWlhNdg5njr4BBu4r%2FG3omWhcYKkp9EBJovo73j%2BCbdzDizw7sKluo",
        "DNT": "1",
        "Host": "www.baidu.com",
        "Referer": f"https://www.baidu.com/s?wd={query_encoded}",
        "Sec-Ch-Ua": "\"Not A(Brand\";v=\"8\", \"Chromium\";v=\"132\", \"Microsoft Edge\";v=\"132\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": "\"Windows\"",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "X-Custom-Time": str(current_timestamp),
    }

    results = []
    urls = []
    page = 0
    max_retries = 10

    proxies = {"http://": proxy, "https://": proxy} if proxy else None
    async with httpx.AsyncClient(proxies=proxies) as client:
        while len(urls) < top_n:
            retry_count = 0
            entries = None
            
            while retry_count < max_retries:
                try:
                    params['pn'] = page * 10
                    url = f"{base_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
                    html_content = await fetch_url(url, headers, proxy)
                    entries = extract_div_contents(html_content)

                    if entries:
                        break
                    
                    retry_count += 1
                    print(f"第 {page + 1} 页无内容，第 {retry_count} 次重试...")
                    await asyncio.sleep(1)

                except httpx.HTTPStatusError as exc:
                    print(f"HTTP错误: {exc}")
                    return f"搜索失败: {str(exc)}", []
                except httpx.RequestError as exc:
                    print(f"请求错误: {exc}")
                    return f"请求失败: {str(exc)}", []
                except Exception as e:
                    print(f"未知错误: {e}")
                    return f"发生未知错误: {str(e)}", []

            if not entries:
                print(f"第 {page + 1} 页重试 {max_retries} 次后仍无内容，结束搜索")
                break

            for entry in entries:
                results.append(f"标题: {entry['title']}\n链接: {entry['link']}\n内容: {entry['content']}\n{'-'*20}")
                if entry['link'] != '无链接' and entry['link'].startswith(('http://', 'https://')):
                    urls.append(entry['link'])

                if len(urls) >= top_n:
                    break

            page += 1

    output = "baidu搜索结果:\n" + "\n".join(results)
    return output, urls[:top_n]

async def edge_search(query, top_n=20, proxy=None):
    results = []
    url_ls = []
    page_num = 1
    max_retries = 10
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled'],
            proxy={"server": proxy} if proxy else None
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="en-US"
        )
        page = await context.new_page()
        
        await page.evaluate("() => { Object.defineProperty(navigator, 'webdriver', { get: () => false }); }")
        
        while len(url_ls) < top_n:
            search_url = f"https://www.cn.bing.com/search?q={query}&first={(page_num - 1) * 10 + 1}&FORM=PERE"
            print(f"正在访问第 {page_num} 页: {search_url}")
            
            retry_count = 0
            page_results_found = False
            
            while retry_count < max_retries and not page_results_found:
                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_selector('li.b_algo', timeout=10000)
                    html = await page.content()
                    soup = BeautifulSoup(html, 'html.parser')
                    search_results = soup.select('li.b_algo')
                    
                    if not search_results:
                        print(f"第 {page_num} 页无结果，重试 {retry_count + 1}/{max_retries}")
                        retry_count += 1
                        continue
                    
                    page_results_found = True
                    
                    for result in search_results:
                        if len(url_ls) >= top_n:
                            break
                            
                        try:
                            title_elem = result.find('h2')
                            title = title_elem.get_text().strip() if title_elem else "无标题"
                            link_elem = result.find('a')
                            link = link_elem['href'] if link_elem and 'href' in link_elem.attrs else "无链接"
                            
                            summary_elem = result.select_one('.b_caption p') or result.select_one('.b_algoSlug')
                            summary = summary_elem.get_text().strip() if summary_elem else "无摘要"
                            summary = summary[:200]
                            
                            formatted_result = f"标题: {title}\n链接: {link}\n内容: {summary}\n{'-'*20}"
                            results.append(formatted_result)
                            if link != "无链接" and link.startswith(('http://', 'https://')):
                                url_ls.append(link)
                            
                        except Exception as e:
                            print(f"处理第 {page_num} 页单个结果时出错: {str(e)}")
                            continue
                    
                except Exception as e:
                    print(f"第 {page_num} 页加载失败: {str(e)}，重试 {retry_count + 1}/{max_retries}")
                    retry_count += 1
                    await asyncio.sleep(random.uniform(1.0, 3.0))
            
            if not page_results_found:
                print(f"第 {page_num} 页重试 {max_retries} 次仍无结果，停止搜索")
                break
                
            page_num += 1
            if len(url_ls) < top_n:
                print(f"已获取 {len(url_ls)} 个结果，继续下一页")
        
        await browser.close()
    
    return "\n".join(results), url_ls[:top_n]
        
async def main():
    proxy = "http://127.0.0.1:7890"
    # proxy = None  # 默认无代理

    while True:
        try:
            query = input("请输入搜索关键词：")
                
            results, urls = await edge_search(query, proxy=proxy)
            
            print(results)
            print("有效链接列表：")
            print("\n".join(urls))
            
        except KeyboardInterrupt:
            print("\n检测到强制退出（Ctrl+C），退出程序...")
            break
        except Exception as e:
            print(f"发生未知错误: {str(e)}")
            print("请稍后重试或检查输入内容")

if __name__ == "__main__":
    asyncio.run(main())