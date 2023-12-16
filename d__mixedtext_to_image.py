# 这个基本靠谱，可以使用这个。
import re
import os
import markdown
import imgkit
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

os.environ["PATH"] += ";C:\\GreenProgram\\wkhtmltox\\bin"


def is_html(content):
    try:
        soup = BeautifulSoup(content, 'html.parser')
        return True
    except:
        return False
def is_markdown_table(content):
    html = markdown.markdown(content, extensions=["tables"])
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("table") is not None

def is_markdown(content):
    markdown_pattern = r'[*_~`#>]|\[(.*?)\]\((.*?)\)'
    match = re.search(markdown_pattern, content)
    return bool(match)
def get_text_width2(html, font):
    html = html.encode("utf-8").decode("latin1")
    # html = re.sub(r'<[^>]*>', '\r\n', html)

    img = Image.new('RGB', (800, 1200), color='white')
    draw = ImageDraw.Draw(img)
    box = draw.textbbox((0, 0), html, font=font)
    # text_width, text_height = draw.textbbox((0, 0), html, font=font)
    x = (img.width - box[2])
    y = (img.height - box[3])

    print(f"get_text_width2:宽{x} - 高{y}",x, y)
    print(f"get_text_width2 box:{box}")
    width = box[2]
    return width if width < 800 else 800
def markdown_to_html(content):

    #content = "# 这是一个标题\n这是一段正文。"
    html_text = markdown.markdown(content, extensions=["tables"])
    print(html_text)
    return html_text


def html_to_image(html_content, output_path='output.png'):
    try:
        font = ImageFont.load_default()  # You can use a custom font if needed
        # 根据字体及大小计算文字占用的长宽
        # size = font.getbbox('test')
        # font_size = size[1]
        # print("font_size:", font_size)
        # # 根据字体及大小计算文字占用的长宽
        # font = ImageFont.truetype("yahei.ttf", 36)
        # size = font.getbbox('test')
        # font_size = size[1]
        # print("font_size2:", font_size)
        # 根据字体及大小计算文字占用的长宽
        text_width = get_text_width2(html_content, font)
        imgkit_options = {'width': text_width}

        # Convert HTML to an image
        imgkit.from_string(html_content, output_path, options=imgkit_options)
        return output_path
    except Exception as e:
        print(e)
        return None

def test():
    # Example usage:
    text_with_html = """html
    <table>
    <thead>
    <tr>
        <th>国家</th>
        <th>首都</th>
        <th>人口 (万人)</th>
        <th>面积 (km²)</th>
    </tr>
    </thead>
    <tbody>
    <tr>
        <td>中国</td>
        <td>北京</td>
        <td>14.1</td>
        <td>9,596,961123123123123423423234234234</td>
    </tr>
    <tr>
        <td>美国</td>
        <td>华盛顿特区</td>
        <td>3.3</td>
        <td>9,826,675</td>
    </tr>
    <tr>
        <td>印度</td>
        <td></td>
        <td>13.5</td>
        <td>3,287,263</td>
    </tr>
    <tr>
        <td>巴西</td>
        <td></td>
        <td></td>
        <td>1</td>
    </tr>
    <tr>
        <td></td>
        <td></td>
        <td></td>
        <td></td>
    </tr>
    <tr>
        <td></td>
        <td></td>
        <td></td>
        <td></td>
    </tr>
    </tbody>
    </table>
    <!-- 更多数据行... -->
    | 姓名 | 年龄 | 性别 |
    | ---- | ---- | ---- |
    | 张三 | 18   | 男   |
    | 李四 | 19   | 女   |
    | 王五 | 20   | 男   |
    """
    text_without_html = "This is plain text content."

    if is_html(text_with_html):
        html_to_image(text_with_html)
    else:
        print("No HTML content to convert.")

test_in = """
@Akun~~~
以下是根据您提供的信息从网页中提取的数据并以表格形式组织的HTML：



| 国家 | 首 都 | 人口 (万) | 面积 (km²) |
| :--: | :--: | :--: | :--: |
| 中国 | 北京 | 14.11 | 963.78 |
| 美国 | 华盛顿特区 | 3302.37 | 983623.78 |
| 俄罗斯 | 莫斯科 | 1447.3 | 1709827.4 |
| 印度 | 新德里 | 14687.4 | 3285636.47 |
| 巴西 | 巴西利亚 | 22235.4 | 854724.39 |
| 加拿大 | 渥太华 | 38,995,077 (估计) | 9,984,670.57 (预计) |

请注意，上述数据仅为示例，并不一定代表该网页所展示的所有信息。为了获取准确的国家和城市数据，您可能需要手动检查该网页的源代码或使用更高级的网页抓取工具。
"""

def mixed_text_to_image(content):
    img_file = os.path.join(os.path.dirname(__file__),'saved') 
    img_file = os.path.join(img_file,'output.png')
    
    if is_markdown_table(content) :
        content = markdown_to_html(content)
        return html_to_image(content,img_file)
    if is_html(content):
        return html_to_image(content,img_file)
    return None;
    
def markdown_table_to_image(tb_content):
    img_file = os.path.join(os.path.dirname(__file__),'saved') 
    img_file = os.path.join(img_file,f'md_table_{date()}.png')
    
    if is_markdown_table(tb_content) :
        content = markdown_to_html(content)
        return html_to_image(content,img_file)
    return None;
def split_tables():
    text = """
    # 这是一个标题
    这是一段正文。

    | 姓名 | 年龄 | 性别 |
    | ---- | ---- | ---- |
    | 张三 | 18   | 男   |
    | 李四 | 19   | 女   |
    | 王五 | 20   | 男   |
    """
    # 定义一个正则表达式，匹配以 | 开头和结尾的行
    pattern = r"^\|.*\|$"
    # 使用 re.findall 方法，找出所有匹配的行，返回一个列表
    table_list = re.findall(pattern, text, re.M)
    # 使用 join 方法，将列表中的元素连接成一个字符串，作为表格内容
    table_text = "\n".join(table_list)
    # 使用 re.sub 方法，将匹配的行替换为空字符串，作为非表格内容
    non_table_text = re.sub(pattern, "", text, flags=re.M)
    # 输出结果
    print("表格内容2：")
    print(table_text)
    print("非表格内容4：")
    print(non_table_text)

split_tables()
#test()
#mixd_text_to_image(test_in)