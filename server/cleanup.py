import sqlite3
conn = sqlite3.connect('/opt/hanshuang/hanshuang.db')
c = conn.cursor()
c.execute('DROP TABLE IF EXISTS users')
conn.commit()
conn.close()
print('users table dropped')
