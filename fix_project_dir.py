import os
from pathlib import Path

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\core\manual_tasks.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Smarter get_project_dir implementation
new_logic = """def get_project_dir(plan_path: Path, base_dir: Path) -> Path:
    \"\"\"
    Plan 파일 경로로부터 프로젝트 루트 디렉토리를 유추합니다.
    \"\"\"
    if not plan_path.exists():
        return base_dir / \"common\"

    # 1. 파일 경로에 'docs/plan'이 포함되어 있다면 그 상위 부모가 프로젝트 루트임
    try:
        parts = plan_path.parts
        for i in range(len(parts) - 2):
            if parts[i] == 'docs' and parts[i+1] == 'plan':
                # parts[i-1]이 프로젝트 루트 폴더 이름임
                return Path(*parts[:i])
    except Exception:
        pass

    # 2. 만약 relative_to(base_dir)이 성공한다면 기존 로직 수행
    try:
        rel = plan_path.relative_to(base_dir)
        if len(rel.parts) >= 3 and rel.parts[0] == 'common' and rel.parts[1] == 'docs' and rel.parts[2] == 'plan':
            # common 프로젝트의 경우 파일 내 메타데이터 확인
            import re
            content = plan_path.read_text(encoding='utf-8', errors='ignore')
            meta_match = re.search(r'>\s*프로젝트\s*:\s*(.+)$', content, re.MULTILINE)
            if meta_match:
                project_name = meta_match.group(1).strip()
                project_path = base_dir / project_name
                if project_path.exists():
                    return project_path
            return base_dir / \"common\"
    except ValueError:
        pass

    # 3. 최후의 보루: docs 폴더를 찾을 때까지 위로 올라감
    current = plan_path.parent
    while current.parent != current:
        if (current / \".git\").exists() or (current / \"package.json\").exists():
            return current
        if current.name == \"plan\" and current.parent.name == \"docs\":
            return current.parent.parent
        current = current.parent

    return base_dir / \"common\""""

# Replace the existing function
import re
content = re.sub(r'def get_project_dir\(.*?\):.*?return base_dir / "common"', new_logic, content, flags=re.DOTALL)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("manual_tasks.py get_project_dir logic enhanced.")
