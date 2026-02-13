import os
from pathlib import Path

archive_path = Path(r"D:\Archive")

# 이미지 확장자
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic', '.tiff'}

print(f"D:\\Archive 폴더 검사 중...")
print(f"폴더 존재: {archive_path.exists()}")

if not archive_path.exists():
    print("폴더가 존재하지 않습니다!")
else:
    # 샘플 파일 찾기
    image_files = []
    folder_count = 0

    for root, dirs, files in os.walk(archive_path):
        folder_count += 1
        for file in files:
            ext = Path(file).suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                image_files.append(os.path.join(root, file))
                if len(image_files) >= 10:
                    break
        if len(image_files) >= 10:
            break

    print(f"\n폴더 수: {folder_count}개")
    print(f"이미지 파일 샘플 ({len(image_files)}개):")
    for f in image_files[:10]:
        print(f"  - {f}")
