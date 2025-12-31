import sqlite3
conn = sqlite3.connect("data/monitor.db")
cur = conn.cursor()

# Check google_search_history schema
cur.execute("PRAGMA table_info(google_search_history)")
print("google_search_history schema:", cur.fetchall())

# Check google_search_results schema
cur.execute("PRAGMA table_info(google_search_results)")
print("\ngoogle_search_results schema:", cur.fetchall())

# Check google_search_history
cur.execute("SELECT * FROM google_search_history ORDER BY id DESC LIMIT 5")
print("\nGoogle search history:", cur.fetchall())

# Check google_search_results
cur.execute("SELECT COUNT(*) FROM google_search_results")
print("\nGoogle search result count:", cur.fetchone()[0])
cur.execute("SELECT * FROM google_search_results ORDER BY id DESC LIMIT 5")
print("Recent results:", cur.fetchall())

conn.close()
