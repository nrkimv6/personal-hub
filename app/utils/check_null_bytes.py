import os
import sys

def find_null_bytes():
    null_files = []
    
    # 현재 디렉토리부터 시작해서 모든 파이썬 파일 검사
    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith('.py'):
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, 'rb') as f:
                        content = f.read()
                        if b'\x00' in content:
                            null_files.append(full_path)
                            # 추가로 null 바이트의 위치와 주변 내용을 출력
                            pos = content.find(b'\x00')
                            start = max(0, pos - 20)
                            end = min(len(content), pos + 20)
                            context = content[start:end]
                            print(f"파일: {full_path}, 위치: {pos}")
                            print(f"Null 바이트 주변 내용(hex): {context.hex()}")
                except Exception as e:
                    print(f"오류: {full_path} 파일 읽는 중 오류 발생: {e}")
    
    if null_files:
        print("\nNull 바이트가 포함된 파일 목록:")
        for file in null_files:
            print(f"- {file}")
    else:
        print("Null 바이트가 포함된 파이썬 파일이 없습니다.")
    
    return null_files

if __name__ == "__main__":
    print("파이썬 파일에서 null 바이트 검색 중...")
    find_null_bytes() 