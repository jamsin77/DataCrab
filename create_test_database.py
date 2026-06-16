"""创建SQLite测试数据库"""
import sqlite3
import os

db_path = "D:/DataCrab/test_database.db"

# 如果存在则删除
if os.path.exists(db_path):
    os.remove(db_path)

# 创建数据库
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 创建测试表
cursor.execute("""
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    price REAL,
    stock INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    quantity INTEGER,
    total_price REAL,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id)
)
""")

# 插入测试数据
products = [
    ("iPhone 15", "手机", 7999.0, 100),
    ("MacBook Pro", "电脑", 12999.0, 50),
    ("iPad Air", "平板", 4599.0, 80),
    ("AirPods Pro", "耳机", 1999.0, 200),
    ("Apple Watch", "手表", 2999.0, 150),
    ("小米14", "手机", 3999.0, 120),
    ("华为Mate60", "手机", 5999.0, 90),
    ("ThinkPad", "电脑", 8999.0, 60),
]

cursor.executemany(
    "INSERT INTO products (name, category, price, stock) VALUES (?, ?, ?, ?)",
    products
)

orders = [
    (1, 2, 15998.0),
    (2, 1, 12999.0),
    (3, 3, 13797.0),
    (4, 5, 9995.0),
    (1, 1, 7999.0),
    (6, 2, 7998.0),
    (7, 1, 5999.0),
    (8, 1, 8999.0),
]

cursor.executemany(
    "INSERT INTO orders (product_id, quantity, total_price) VALUES (?, ?, ?)",
    orders
)

conn.commit()

# 验证数据
cursor.execute("SELECT COUNT(*) FROM products")
product_count = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM orders")
order_count = cursor.fetchone()[0]

print(f"✅ SQLite测试数据库创建成功")
print(f"   路径: {db_path}")
print(f"   产品数: {product_count}")
print(f"   订单数: {order_count}")
print(f"\n表结构:")
print(f"   - products (产品表)")
print(f"   - orders (订单表)")

conn.close()