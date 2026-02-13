import sqlite3

conn = sqlite3.connect('data/image_classifier.db')

print('=== folder_mappings 상태 ===')
cursor = conn.execute('SELECT COUNT(*) FROM folder_mappings')
print(f'전체 폴더 수: {cursor.fetchone()[0]}')

cursor = conn.execute('SELECT folder_status, COUNT(*) FROM folder_mappings GROUP BY folder_status')
print('\n상태별 분포:')
for row in cursor:
    print(f'  {row[0]}: {row[1]}개')

print('\n=== file_classifications 상태 ===')
cursor = conn.execute('SELECT COUNT(*) FROM file_classifications')
print(f'전체 파일 수: {cursor.fetchone()[0]}')

print('\n=== 샘플 폴더 (상위 10개) ===')
cursor = conn.execute('SELECT id, folder_path, file_count, folder_status FROM folder_mappings LIMIT 10')
for row in cursor:
    print(f'  [{row[0]}] {row[1]} - {row[2]}개 파일 - 상태: {row[3]}')

conn.close()
