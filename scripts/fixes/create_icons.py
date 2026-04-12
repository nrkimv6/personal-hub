"""PWA 아이콘 생성 스크립트"""
from PIL import Image, ImageDraw, ImageFont
import os

# 색상 정의
bg_color = (59, 130, 246)  # #3b82f6 (blue-500)
text_color = (255, 255, 255)  # white

def create_icon(size, filename, maskable=False):
    img = Image.new('RGB', (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    # 텍스트 'M' 그리기
    font_size = int(size * 0.6)

    try:
        font = ImageFont.truetype('arial.ttf', font_size)
    except:
        font = ImageFont.load_default()

    text = 'M'

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (size - text_width) // 2
    y = (size - text_height) // 2 - bbox[1]

    draw.text((x, y), text, fill=text_color, font=font)

    img.save(filename, 'PNG')
    print(f'Created: {filename}')

if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    icons_dir = os.path.join(project_root, 'frontend', 'static', 'icons')

    os.makedirs(icons_dir, exist_ok=True)

    create_icon(192, os.path.join(icons_dir, 'icon-192.png'))
    create_icon(512, os.path.join(icons_dir, 'icon-512.png'))
    create_icon(512, os.path.join(icons_dir, 'icon-maskable.png'), maskable=True)

    print('All icons created successfully!')
