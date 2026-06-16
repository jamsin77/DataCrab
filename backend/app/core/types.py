"""数据库类型兼容层 - 支持PostgreSQL和SQLite"""

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSON as PG_JSON

# 使用PostgreSQL类型（SQLite下SQLAlchemy会自动降级处理）
# 对于UUID，SQLite下用String(36)替代
# 对于JSON，SQLite下用Text替代

try:
    from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
    # SQLAlchemy 2.0+ SQLite支持JSON
    JSONType = PG_JSON
except ImportError:
    JSONType = Text

# UUID类型 - PostgreSQL用原生UUID，SQLite用String
UUIDType = PG_UUID
