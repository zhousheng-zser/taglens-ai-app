#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MinIO 存储客户端
- 提供文件上传和下载功能
- 提供图片上传和下载功能
- 提供 FastAPI 接口
"""
import os
import io
from pathlib import Path
from typing import Optional
from minio import Minio
from minio.error import S3Error
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import Response
import mimetypes


# MinIO 配置
MINIO_ENDPOINT = "192.168.1.117:9000"
MINIO_BUCKET = "bucket-taglens"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "3edcVFR$")
MINIO_SECURE = False
MINIO_SKIP_BUCKET_CHECK = os.getenv("MINIO_SKIP_BUCKET_CHECK", "false").lower() == "true"


class MinIOStorageClient:
    """MinIO 存储客户端类"""
    
    def __init__(self, skip_bucket_check: bool = None):
        self.client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE
        )
        self.bucket = MINIO_BUCKET
        
        if skip_bucket_check is None:
            skip_bucket_check = MINIO_SKIP_BUCKET_CHECK
        
        if not skip_bucket_check:
            self._ensure_bucket_exists()
    
    def _ensure_bucket_exists(self):
        """确保存储桶存在，如果不存在则创建"""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as e:
            raise
    
    def upload_file(
        self,
        file_path: str,
        object_name: str,
        content_type: Optional[str] = None
    ) -> bool:
        """上传文件到 MinIO"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        if content_type is None:
            content_type, _ = mimetypes.guess_type(file_path)
            if content_type is None:
                content_type = "application/octet-stream"
        
        self.client.fput_object(
            self.bucket,
            object_name,
            file_path,
            content_type=content_type
        )
        return True
    
    def upload_file_data(
        self,
        file_data: bytes,
        object_name: str,
        content_type: Optional[str] = None
    ) -> bool:
        """从内存数据上传文件到 MinIO"""
        if content_type is None:
            content_type = "application/octet-stream"
        file_obj = io.BytesIO(file_data)
        self.client.put_object(
            self.bucket,
            object_name,
            file_obj,
            length=len(file_data),
            content_type=content_type
        )
        return True
    
    def download_file(
        self,
        object_name: str,
        output_path: Optional[str] = None
    ) -> str:
        """从 MinIO 下载文件"""
        if output_path is None:
            output_path = os.path.join(
                os.path.dirname(__file__),
                os.path.basename(object_name)
            )
        
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        self.client.fget_object(self.bucket, object_name, output_path)
        return output_path
    
    def download_file_data(self, object_name: str) -> bytes:
        """从 MinIO 下载文件数据到内存"""
        response = self.client.get_object(self.bucket, object_name)
        file_data = response.read()
        response.close()
        response.release_conn()
        return file_data
    
    def upload_image(self, file_path: str, object_name: str) -> bool:
        """上传图片到 MinIO"""
        return self.upload_file(file_path, object_name)
    
    def download_image(
        self,
        object_name: str,
        output_path: Optional[str] = None
    ) -> str:
        """从 MinIO 下载图片"""
        return self.download_file(object_name, output_path)
    
    def delete_file(self, object_name: str) -> bool:
        """删除 MinIO 中的文件"""
        self.client.remove_object(self.bucket, object_name)
        return True
    
    def file_exists(self, object_name: str) -> bool:
        """检查文件是否存在"""
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error:
            return False


# 创建全局客户端实例
_storage_client = None

def get_storage_client(skip_bucket_check: bool = None) -> MinIOStorageClient:
    """获取存储客户端实例（单例模式）"""
    global _storage_client
    if _storage_client is None:
        _storage_client = MinIOStorageClient(skip_bucket_check=skip_bucket_check)
    return _storage_client


# ==================== FastAPI 接口 ====================

def create_minio_app() -> FastAPI:
    """创建 MinIO 存储相关的 FastAPI 应用"""
    app = FastAPI(title="MinIO Storage API", version="1.0.0")
    
    @app.post("/api/minio/upload/file")
    async def upload_file_api(
        file: UploadFile = File(...),
        object_name: str = Query(..., description="MinIO 中的对象名称（路径）")
    ):
        try:
            client = get_storage_client()
            file_data = await file.read()
            content_type = file.content_type or "application/octet-stream"
            client.upload_file_data(file_data, object_name, content_type)
            
            return {
                "success": True,
                "message": "文件上传成功",
                "object_name": object_name,
                "file_name": file.filename,
                "file_size": len(file_data),
                "content_type": content_type
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")
    
    @app.post("/api/minio/upload/image")
    async def upload_image_api(
        file: UploadFile = File(...),
        object_name: str = Query(..., description="MinIO 中的对象名称（路径）")
    ):
        try:
            if not file.content_type or not file.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="文件必须是图片类型")
            
            client = get_storage_client()
            file_data = await file.read()
            client.upload_file_data(file_data, object_name, file.content_type)
            
            return {
                "success": True,
                "message": "图片上传成功",
                "object_name": object_name,
                "file_name": file.filename,
                "file_size": len(file_data),
                "content_type": file.content_type
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")
    
    @app.get("/api/minio/download/file")
    async def download_file_api(
        object_name: str = Query(..., description="MinIO 中的对象名称（路径）")
    ):
        try:
            client = get_storage_client()
            if not client.file_exists(object_name):
                raise HTTPException(status_code=404, detail="文件不存在")
            
            file_data = client.download_file_data(object_name)
            filename = os.path.basename(object_name)
            content_type, _ = mimetypes.guess_type(object_name)
            if content_type is None:
                content_type = "application/octet-stream"
            
            return Response(
                content=file_data,
                media_type=content_type,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")
    
    @app.get("/api/minio/download/image")
    async def download_image_api(
        object_name: str = Query(..., description="MinIO 中的对象名称（路径）")
    ):
        try:
            client = get_storage_client()
            if not client.file_exists(object_name):
                raise HTTPException(status_code=404, detail="图片不存在")
            
            file_data = client.download_file_data(object_name)
            filename = os.path.basename(object_name)
            content_type, _ = mimetypes.guess_type(object_name)
            if content_type is None or not content_type.startswith("image/"):
                content_type = "image/jpeg"
            
            return Response(
                content=file_data,
                media_type=content_type,
                headers={"Content-Disposition": f'inline; filename="{filename}"'}
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")
    
    @app.delete("/api/minio/delete/file")
    async def delete_file_api(
        object_name: str = Query(..., description="MinIO 中的对象名称（路径）")
    ):
        try:
            client = get_storage_client()
            if not client.file_exists(object_name):
                raise HTTPException(status_code=404, detail="文件不存在")
            
            client.delete_file(object_name)
            return {
                "success": True,
                "message": "文件删除成功",
                "object_name": object_name
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    
    @app.get("/api/minio/exists/file")
    async def file_exists_api(
        object_name: str = Query(..., description="MinIO 中的对象名称（路径）")
    ):
        try:
            client = get_storage_client()
            exists = client.file_exists(object_name)
            return {
                "success": True,
                "exists": exists,
                "object_name": object_name
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")
    
    return app


# ==================== 命令行测试代码 ====================

if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).parent.parent
    BACKEND_DIR = Path(__file__).parent
    DATA_DIR = PROJECT_ROOT / "data"
    
    TEST_FILES = [
        {
            "name": "B.jpg",
            "type": "图片文件",
            "local_path": BACKEND_DIR / "test" / "B.jpg",
            "object_name": "test/images/B.jpg",
            "download_path": None
        },
        {
            "name": "2026-01-09_10_05 (bulk_import json)",
            "type": "JSON文件",
            "local_path": DATA_DIR / "bulk_import" / "2026-01-09_10_05" / "2007588251504533506_big.jpg.json",
            "object_name": "test/bulk_import/2026-01-09_10_05/2007588251504533506_big.jpg.json",
            "download_path": None
        },
        {
            "name": "taglens.db",
            "type": "数据库文件",
            "local_path": DATA_DIR / "taglens.db",
            "object_name": "test/database/taglens.db",
            "download_path": None
        },
        {
            "name": "faiss_spatial_histogram.index",
            "type": "FAISS索引文件",
            "local_path": DATA_DIR / "faiss_spatial_histogram.index",
            "object_name": "test/faiss/faiss_spatial_histogram.index",
            "download_path": None
        },
        {
            "name": "faiss_uuid_map.json",
            "type": "JSON文件",
            "local_path": DATA_DIR / "faiss_uuid_map.json",
            "object_name": "test/faiss/faiss_uuid_map.json",
            "download_path": None
        }
    ]
    
    try:
        client = get_storage_client(skip_bucket_check=True)
        
        # 上传文件
        uploaded_count = 0
        for file_info in TEST_FILES:
            local_path = file_info['local_path']
            if not local_path.exists():
                continue
            
            try:
                if file_info['type'] == "图片文件":
                    client.upload_image(str(local_path), file_info['object_name'])
                else:
                    client.upload_file(str(local_path), file_info['object_name'])
                uploaded_count += 1
            except Exception:
                pass
        
        # 下载文件
        downloaded_count = 0
        for file_info in TEST_FILES:
            if not client.file_exists(file_info['object_name']):
                continue
            
            try:
                if file_info['download_path'] is None:
                    download_dir = BACKEND_DIR / "test_downloads"
                    download_dir.mkdir(exist_ok=True)
                    filename = os.path.basename(file_info['object_name'])
                    download_path = str(download_dir / filename)
                else:
                    download_path = file_info['download_path']
                
                if file_info['type'] == "图片文件":
                    client.download_image(file_info['object_name'], download_path)
                else:
                    client.download_file(file_info['object_name'], download_path)
                downloaded_count += 1
            except Exception:
                pass
        
        print(f"上传: {uploaded_count}/{len(TEST_FILES)}, 下载: {downloaded_count}/{len(TEST_FILES)}")
        
    except Exception as e:
        print(f"错误: {e}")
        exit(1)
