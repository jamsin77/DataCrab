"""文件链接相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID


class FileLinkCreate(BaseModel):
    name: str = Field(..., max_length=200)
    path: str = Field(..., max_length=500)
    description: Optional[str] = None
    link_type: str = Field(default="file", pattern="^(file|directory)$")
    is_public: bool = False
    allowed_extensions: Optional[List[str]] = None


class FileLinkUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    path: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    is_public: Optional[bool] = None
    allowed_extensions: Optional[List[str]] = None
    is_active: Optional[bool] = None


class FileLinkResponse(BaseModel):
    id: UUID
    name: str
    path: str
    description: Optional[str] = None
    link_type: str
    is_public: bool
    allowed_extensions: Optional[List[str]] = None
    file_metadata: Optional[dict] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool

    class Config:
        from_attributes = True


class FileInfo(BaseModel):
    name: str
    path: str
    is_file: bool
    is_dir: bool
    size: Optional[int] = None
    modified_time: Optional[datetime] = None
    extension: Optional[str] = None


class DirectoryListing(BaseModel):
    path: str
    files: List[FileInfo]
    total: int


class FileWriteRequest(BaseModel):
    subpath: str = Field(..., max_length=1000, description="相对于链接根目录的文件路径")
    content: str = Field(..., description="要写入的文件内容")
    encoding: str = Field(default="utf-8", description="文件编码")
