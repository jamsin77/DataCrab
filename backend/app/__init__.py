"""DataCrab 后端应用"""

# ChromaDB 要求 sqlite3 >= 3.35.0，系统自带版本可能过低（如 3.26.0）
# 用 pysqlite3-binary 替换标准库 sqlite3，必须在 chromadb 等依赖 import 前完成
try:
    import pysqlite3
    import sys

    if pysqlite3.sqlite_version_info >= (3, 35, 0):
        sys.modules["sqlite3"] = pysqlite3
        sys.modules["sqlite3.dbapi2"] = pysqlite3
except ImportError:
    pass
