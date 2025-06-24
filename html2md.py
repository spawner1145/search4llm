import asyncio
from bs4 import BeautifulSoup
import html2text
import re

"""
必要的库:
pip install beautifulsoup4 html2text
可选(性能更好):
pip install lxml
如果安装了 lxml, 可以将下面 BeautifulSoup(..., 'html.parser') 改为 BeautifulSoup(..., 'lxml')
"""

async def html_to_markdown_combined(html_string: str, preprocess: bool = True) -> str:
    try:
        processed_html = html_string
        soup = None

        # 使用 BeautifulSoup 进行可选的预处理
        if preprocess:
            print("bs4正在处理中")
            await asyncio.sleep(0)

            soup = BeautifulSoup(html_string, 'html.parser')
            # soup = BeautifulSoup(html_string, 'lxml') # 如果安装了 lxml 推荐使用这个

            # 在这里添加你的 BeautifulSoup 预处理逻辑
            # 示例 1: 移除所有的 <script> 和 <style> 标签
            count_removed = 0
            for unwanted_tag in soup(["script", "style"]):
                unwanted_tag.decompose()
                count_removed += 1
            if count_removed > 0:
                print(f"已移除 {count_removed}个 <script>/<style> 标签")

            # 示例 2: 可以修改特定标签，比如移除所有图片的 'width' 和 'height' 属性 (仅作演示)
            # for img in soup.find_all('img'):
            #     if 'width' in img.attrs:
            #         del img.attrs['width']
            #     if 'height' in img.attrs:
            #         del img.attrs['height']
            #     print("Processed img tag attributes.")

            # 示例 3: 通常只处理 <body> 部分的内容 (如果存在)
            body_content = soup.body
            if body_content:
                print("获取到 <body> 标签")
                processed_html = str(body_content)
            else:
                # 如果没有 body 标签，尝试处理整个文档结构
                print("没有 <body> 标签，处理整个文档结构")
                processed_html = str(soup)

            await asyncio.sleep(0)
            print("bs4处理完成")

        # html2text进行Markdown转换
        print("正在 html2text 转换")
        h = html2text.HTML2Text()

        # 配置 html2text 选项
        h.body_width = 0
        h.ignore_links = False
        h.ignore_images = False
        h.ignore_emphasis = False
        h.ignore_tables = False
        h.mark_code = True

        await asyncio.sleep(0)

        # 初始转换结果
        markdown_string = h.handle(processed_html)

        await asyncio.sleep(0)
        print("html2text 转换完成")

        # 正则表达式后处理步骤 (Workaround)
        # 这是为了处理 html2text 意外输出 [code]...[/code] 的情况
        print("正在进行正则替换 [code] -> ```")
        markdown_string = re.sub(r'^\s*\[code\]\s*', '```\n', markdown_string, flags=re.IGNORECASE | re.MULTILINE)
        markdown_string = re.sub(r'\s*\[/code\]\s*$', '\n```', markdown_string, flags=re.IGNORECASE | re.MULTILINE)
        print("正则替换完成")

        # 步骤 4: 可选的进一步清理 (合并多余空行)
        # print("Running Final Cleanup")
        # markdown_string = re.sub(r'\n{3,}', '\n\n', markdown_string) # 合并3个以上换行为2个

        # 最终去除首尾空白
        final_markdown = markdown_string.strip()

        return final_markdown

    except Exception as e:
        # 调整错误阶段判断
        stage = "Unknown"
        if preprocess and soup is None:
             stage = "Preprocessing (BeautifulSoup Init/Parse)"
        elif preprocess and 'processed_html' not in locals():
             stage = "Preprocessing (BeautifulSoup Post Process)"
        elif 'markdown_string' not in locals():
             stage = "Conversion (html2text)"
        else:
             stage = "Postprocessing (Regex/Cleanup)"

        print(f"HTML to Markdown (Combined) 在 [{stage}] 阶段转换出错: {e}")
        # import traceback
        # traceback.print_exc()
        return f"Error during conversion in {stage}: {e}"

# 示例用法
async def main():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>示例页面</title>
        <meta charset="UTF-8">
        <script>console.log('js去除');</script>
        <style>body { font-family: sans-serif; /* css去除 */ }</style>
    </head>
    <body>
        <h1>主标题 H1</h1>
        <p>这是一个段落，包含 <strong>粗体文本</strong> 和 <em>斜体文本</em>。
        同时还有一个行内代码示例： <code>print("114514")</code>。</p>
        <hr>
        <h2>副标题 H2</h2>
        <p>下面是一个无序列表:</p>
        <ul>
            <li>项目 1</li>
            <li>项目 2 (包含 <a href="https://example.com">链接</a>)</li>
            <li>嵌套列表:
                <ul>
                    <li>嵌套项 A</li>
                    <li>嵌套项 B with <code>114514</code></li>
                </ul>
            </li>
        </ul>
        <h3>有序列表 H3</h3>
        <ol>
            <li>第一项</li>
            <li>第二项</li>
        </ol>
        <h4>图片 H4</h4>
        <p>下面是一个图片：</p>
        <img src="logo.png" alt="示例图片 Alt Text" width="50" height="50">

        <h5>代码块 H5</h5>
        <p>Python 代码示例:</p>
        <pre><code class="language-python">import os

def list_files(directory):
    # List all files in the given directory
    print(f"Files in {directory}:")
    for filename in os.listdir(directory):
        if os.path.isfile(os.path.join(directory, filename)):
            print(f"- {filename}")

list_files('.')</code></pre>

        <p>无特定语言的代码块:</p>
        <pre><code>This is a plain code block.
It spans multiple lines.</code></pre>

        <h6>引用 H6</h6>
        <blockquote>
        这是一个引用块。<br>
        这是引用的第二行（使用了 br 标签）。
        <p>引用块内也可以有段落。</p>
        </blockquote>

        <p>包含不想要的脚本<script>alert('应该移除');</script>标签。</p>
    </body>
    </html>
    """

    print("="*20 + " 输入 HTML " + "="*20)
    # 预览 HTML
    preview_html = sample_html
    try:
        temp_soup = BeautifulSoup(sample_html, 'html.parser')
        if temp_soup.body:
            preview_html = str(temp_soup.body)
    except:
        pass
    print(preview_html[:1000] + "...\n" if len(preview_html) > 1000 else preview_html)


    # 调用函数 (启用预处理)
    print("\n" + "="*20 + " 开始转换 (启用预处理) " + "="*20)
    markdown_output = await html_to_markdown_combined(sample_html, preprocess=True)
    print("\n" + "="*20 + " 输出 Markdown " + "="*20)
    print(markdown_output)

    # 测试禁用预处理
    # print("\n" + "="*20 + " 开始转换 (禁用预处理) " + "="*20)
    # markdown_output_direct = await html_to_markdown_combined(sample_html, preprocess=False)
    # print("\n" + "="*20 + " 输出 Markdown (无预处理) " + "="*20)
    # print(markdown_output_direct)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n操作被用户中断。")
