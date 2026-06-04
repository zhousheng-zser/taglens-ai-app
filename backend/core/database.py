# -*- coding: utf-8 -*-
"""
数据库模块 - 使用 MySQL taglens_taglens 存储图片标签和元数据
"""
import json
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymysql
import pymysql.cursors
import pymysql.err
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BACKUP_DIR = Path(__file__).parent.parent.parent / "data" / "backup"
BACKUP_KEEP_DAYS = int(os.getenv("DB_BACKUP_KEEP_DAYS", "7"))
_backup_checked = False


def _mysql_connect_kwargs() -> Dict[str, Any]:
    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_TAGLENS_DATABASE", "taglens_taglens"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
    }


def _ensure_column(cursor, table: str, column: str, definition: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    if int(cursor.fetchone()["cnt"]) == 0:
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")
        print(f"已添加 {column} 字段到 {table} 表")


def _backup_db_if_needed() -> None:
    """按天 mysqldump 备份 MySQL taglens_taglens，并清理过期 .sql 备份（保留原有 .db 文件）。"""
    global _backup_checked
    if _backup_checked:
        return
    _backup_checked = True

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        backup_path = BACKUP_DIR / f"taglens.{today}.sql"
        db_name = os.getenv("MYSQL_TAGLENS_DATABASE", "taglens_taglens")

        if not backup_path.exists():
            kwargs = _mysql_connect_kwargs()
            cmd = [
                "mysqldump",
                f"-h{kwargs['host']}",
                f"-P{kwargs['port']}",
                f"-u{kwargs['user']}",
                f"-p{kwargs['password']}",
                "--single-transaction",
                "--quick",
                "--set-gtid-purged=OFF",
                db_name,
            ]
            with open(backup_path, "w", encoding="utf-8") as outfile:
                subprocess.run(cmd, stdout=outfile, stderr=subprocess.PIPE, check=True)
            print(f"已创建本地数据库 MySQL 备份: {backup_path}")

        now_ts = time.time()
        keep_seconds = BACKUP_KEEP_DAYS * 24 * 60 * 60
        for path in list(BACKUP_DIR.glob("taglens.*.sql")) + list(BACKUP_DIR.glob("taglens.*.sql.gz")):
            try:
                if now_ts - path.stat().st_mtime > keep_seconds:
                    path.unlink()
                    print(f"已删除过期数据库备份: {path.name}")
            except Exception as e:
                print(f"删除过期备份失败: {path} err={e}")
    except Exception as e:
        print(f"数据库备份检查失败(忽略): {e}")


@contextmanager
def get_db_connection():
    """获取 MySQL 数据库连接的上下文管理器。"""
    _backup_db_if_needed()
    conn = pymysql.connect(
        **_mysql_connect_kwargs(),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """初始化数据库，创建表结构。"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                uuid VARCHAR(128) NOT NULL,
                file_path TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                file_name VARCHAR(512) NULL,
                camera_id VARCHAR(128) NULL,
                sz_name VARCHAR(512) NULL,
                sz_tag_ref_json LONGTEXT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                UNIQUE KEY uk_images_uuid (uuid),
                KEY idx_images_uuid (uuid),
                KEY idx_images_created_at (created_at),
                KEY idx_images_relative_path (relative_path(255))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                image_id INT NOT NULL,
                tag VARCHAR(512) NOT NULL,
                tag_type VARCHAR(32) NOT NULL,
                UNIQUE KEY uk_tags_image_tag_type (image_id, tag(191), tag_type),
                KEY idx_tags_image_id (image_id),
                KEY idx_tags_tag (tag(191)),
                KEY idx_tags_type (tag_type),
                CONSTRAINT fk_tags_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                image_id INT NOT NULL,
                description LONGTEXT NOT NULL,
                keywords_json LONGTEXT NOT NULL,
                qwen_captions_json LONGTEXT NOT NULL,
                yolo_objects_json LONGTEXT NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                UNIQUE KEY uk_analysis_image_id (image_id),
                KEY idx_analysis_image_id (image_id),
                CONSTRAINT fk_analysis_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS keyword_embeddings (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                image_id INT NOT NULL,
                keyword VARCHAR(512) NOT NULL,
                embedding LONGBLOB NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                UNIQUE KEY uk_keyword_embeddings_image_keyword (image_id, keyword(191)),
                KEY idx_keyword_embeddings_image_id (image_id),
                KEY idx_keyword_embeddings_keyword (keyword(191)),
                CONSTRAINT fk_keyword_embeddings_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        _ensure_column(cursor, "analysis_results", "qwen_captions_json", "LONGTEXT NOT NULL DEFAULT '[]'")
        for col, definition in (
            ("camera_id", "VARCHAR(128) NULL"),
            ("sz_name", "VARCHAR(512) NULL"),
            ("sz_tag_ref_json", "LONGTEXT NULL"),
        ):
            _ensure_column(cursor, "images", col, definition)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id VARCHAR(128) NOT NULL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                script_path TEXT NOT NULL,
                schedule_enabled TINYINT DEFAULT 0,
                schedule_interval INT DEFAULT 1,
                last_run VARCHAR(64) NULL,
                created_at VARCHAR(64) NOT NULL,
                status VARCHAR(32) DEFAULT 'idle',
                ai_model VARCHAR(64) DEFAULT 'gemini',
                api_probability DOUBLE DEFAULT 1.0,
                last_stopped_at VARCHAR(64) NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        _ensure_column(cursor, "projects", "ai_model", "VARCHAR(64) DEFAULT 'gemini'")
        _ensure_column(cursor, "projects", "api_probability", "DOUBLE DEFAULT 1.0")
        _ensure_column(cursor, "projects", "last_stopped_at", "VARCHAR(64) NULL")


def _sz_tag_refs_from_db_value(sz_tag_ref_json: Optional[str]) -> List[str]:
    """将 images.sz_tag_ref_json 解析为字符串列表。"""
    if not sz_tag_ref_json or not str(sz_tag_ref_json).strip():
        return []
    try:
        data = json.loads(sz_tag_ref_json)
        if isinstance(data, list):
            return [str(x) for x in data if x is not None and str(x).strip() != ""]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def save_image_to_db(
    image_uuid: str,
    file_path: str,
    relative_path: str,
    file_name: Optional[str],
    tags: List[str],
    keywords: List[str],
    description: str,
    qwen_captions: List[str],
    yolo_objects: List[str],
    keyword_embeddings: Optional[List[tuple[str, bytes]]] = None,  # List of (keyword, embedding_bytes) tuples
    camera_id: Optional[str] = None,
    sz_name: Optional[str] = None,
    sz_tag_ref_json: Optional[str] = None,
) -> int:
    """
    保存图片信息到数据库
    
    返回: 图片记录的 ID
    """
    now = datetime.now().isoformat()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 插入图片记录
        cursor.execute("""
            INSERT INTO images (
                uuid, file_path, relative_path, file_name,
                camera_id, sz_name, sz_tag_ref_json,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            image_uuid, file_path, relative_path, file_name,
            camera_id, sz_name, sz_tag_ref_json,
            now, now,
        ))
        
        image_id = cursor.lastrowid
        
        # 插入标签 - 先插入 keywords
        for keyword in keywords:
            try:
                cursor.execute("""
                    INSERT INTO tags (image_id, tag, tag_type)
                    VALUES (%s, %s, %s)
                """, (image_id, keyword, 'keyword'))
            except pymysql.err.IntegrityError:
                # 如果标签已存在，忽略
                pass
        
        # 再插入 yolo_objects
        for yolo_obj in yolo_objects:
            try:
                cursor.execute("""
                    INSERT INTO tags (image_id, tag, tag_type)
                    VALUES (%s, %s, %s)
                """, (image_id, yolo_obj, 'yolo_object'))
            except pymysql.err.IntegrityError:
                # 如果标签已存在，忽略
                pass
        
        # 插入分析结果
        cursor.execute("""
            INSERT INTO analysis_results (
                image_id, description, keywords_json, 
                qwen_captions_json, yolo_objects_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            image_id,
            description,
            json.dumps(keywords, ensure_ascii=False),
            json.dumps(qwen_captions, ensure_ascii=False),
            json.dumps(yolo_objects, ensure_ascii=False),
            now
        ))
        
        # 插入keyword向量（每个keyword一个向量）
        if keyword_embeddings:
            for keyword, embedding_bytes in keyword_embeddings:
                try:
                    cursor.execute("""
                        INSERT INTO keyword_embeddings (image_id, keyword, embedding, created_at)
                        VALUES (%s, %s, %s, %s)
                    """, (image_id, keyword, embedding_bytes, now))
                except pymysql.err.IntegrityError:
                    # 如果keyword向量已存在，更新它
                    cursor.execute("""
                        UPDATE keyword_embeddings 
                        SET embedding = %s, created_at = %s
                        WHERE image_id = %s AND keyword = %s
                    """, (embedding_bytes, now, image_id, keyword))
        
        return image_id


def search_images(
    query: str, 
    limit: int = 100,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    camera_name: Optional[str] = None,
    biz_category: Optional[str] = None,
    query_embedding: Optional[bytes] = None,  # 单个查询文本的向量化结果（向后兼容）
    query_embeddings: Optional[List[bytes]] = None,  # 多个查询文本的向量化结果列表
    query_weights: Optional[List[float]] = None,  # 每个查询标签的权重列表
    similarity_threshold: float = 0.3,  # 相似度阈值
    page: Optional[int] = None,  # 分页：页码（从1开始）
    page_size: Optional[int] = None  # 分页：每页数量
) -> tuple[List[Dict[str, Any]], int]:
    """
    从数据库搜索图片（使用向量相似度搜索）
    
    参数:
        query: 搜索关键词
        limit: 返回结果数量限制
        start_date: 开始日期 (ISO 格式，例如: "2025-01-01T00:00:00")
        end_date: 结束日期 (ISO 格式，例如: "2025-12-31T23:59:59")
        query_embedding: 查询文本的向量化结果（bytes格式）
        similarity_threshold: 相似度阈值（0-1之间）
    
    返回: 图片信息列表（包含similarity字段）
    """
    import numpy as np
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 构建 WHERE 条件
        where_conditions = []
        params = []

        # 是否使用向量搜索（由调用方传入向量决定）
        use_vector_search = (query_embeddings is not None and len(query_embeddings) > 0) or (query_embedding is not None)
        
        # 时间范围条件
        if start_date:
            where_conditions.append("i.created_at >= %s")
            params.append(start_date)
        
        if end_date:
            where_conditions.append("i.created_at <= %s")
            params.append(end_date)

        if camera_name:
            where_conditions.append("i.sz_name LIKE %s")
            params.append(f"%{camera_name}%")

        if biz_category:
            where_conditions.append("i.sz_tag_ref_json LIKE %s")
            params.append(f"%{biz_category}%")

        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        # 先计算总数（用于分页显示）
        count_sql = f"""
            SELECT COUNT(DISTINCT i.id) AS cnt
            FROM images i
            LEFT JOIN analysis_results ar ON i.id = ar.image_id
            WHERE {where_clause}
        """
        cursor.execute(count_sql, params)
        total_count = int(cursor.fetchone()['cnt'])
        
        # 查询符合条件的图片（根据是否使用向量搜索决定是否一次性查询所有）
        sql = f"""
            SELECT DISTINCT
                i.id,
                i.uuid,
                i.file_path,
                i.relative_path,
                i.file_name,
                i.camera_id,
                i.sz_name,
                i.sz_tag_ref_json,
                i.created_at,
                ar.description,
                ar.keywords_json,
                ar.qwen_captions_json,
                ar.yolo_objects_json
            FROM images i
            LEFT JOIN analysis_results ar ON i.id = ar.image_id
            WHERE {where_clause}
        """
        # use_vector_search 已在上方确定
        
        # 如果不使用向量搜索，直接在 SQL 层面分页（更高效）
        if not use_vector_search:
            # 不使用向量搜索，按时间范围查询，直接在 SQL 层面分页
            if page is not None and page_size is not None:
                # 有分页参数，在 SQL 层面分页
                sql += " ORDER BY i.created_at DESC LIMIT %s OFFSET %s"
                offset = (page - 1) * page_size
                cursor.execute(sql, params + [page_size, offset])
            else:
                # 没有分页参数，使用 limit（向后兼容）
                sql += f" ORDER BY i.created_at DESC LIMIT {limit}"
                cursor.execute(sql, params)
            
            rows = cursor.fetchall()
            
            # 直接构建结果，不需要向量计算
            results = []
            for row in rows:
                # 获取该图片的所有标签
                cursor.execute("""
                    SELECT tag, tag_type FROM tags WHERE image_id = %s
                """, (row['id'],))
                
                tags = []
                keywords = []
                yolo_objects = []
                
                for tag_row in cursor.fetchall():
                    tag = tag_row['tag']
                    tag_type = tag_row['tag_type']
                    tags.append(tag)
                    if tag_type == 'keyword':
                        keywords.append(tag)
                    else:
                        yolo_objects.append(tag)
                
                # 解析 JSON 字段
                keywords_json = json.loads(row['keywords_json'] or '[]')
                qwen_captions = json.loads(row['qwen_captions_json'] or '[]')
                yolo_objects_json = json.loads(row['yolo_objects_json'] or '[]')
                
                results.append({
                    'id': row['id'],
                    'uuid': row['uuid'],
                    'filePath': row['relative_path'],
                    'fileName': row['file_name'],
                    'cameraId': row['camera_id'],
                    'szName': row['sz_name'],
                    'szTagRefs': _sz_tag_refs_from_db_value(row['sz_tag_ref_json']),
                    'createdAt': row['created_at'],
                    'description': row['description'],
                    'keywords': keywords_json,
                    'tags': tags,
                    'qwenCaptions': qwen_captions,
                    'yoloObjects': yolo_objects_json,
                })
            
            # 返回结果（total_count 已经在上面通过 COUNT 查询计算过了）
            return results, total_count
        
        # 以下是向量搜索的逻辑（标签搜索页面使用）
        # 如果使用向量搜索，需要查询所有数据来计算相似度
        if page is not None and page_size is not None:
            # 即使有分页参数，向量搜索也需要先查询所有数据来计算相似度
            cursor.execute(sql, params)
        else:
            # 没有分页参数，查询所有数据
            cursor.execute(sql, params)
        
        rows = cursor.fetchall()
        
        # 确定使用的查询向量列表（优先使用query_embeddings，否则使用query_embedding）
        query_embeddings_list = []
        if query_embeddings is not None and len(query_embeddings) > 0:
            query_embeddings_list = query_embeddings
        elif query_embedding is not None:
            query_embeddings_list = [query_embedding]
        
        # 确定权重列表
        weights_list = []
        if query_weights is not None and len(query_weights) > 0:
            weights_list = query_weights
        elif query_embeddings_list:
            # 如果没有提供权重，平均分配
            weights_list = [1.0 / len(query_embeddings_list)] * len(query_embeddings_list)
        
        # 使用向量搜索，计算相似度并过滤
        if query_embeddings_list:
            # 归一化所有查询向量
            query_vecs = []
            for emb in query_embeddings_list:
                vec = np.frombuffer(emb, dtype=np.float32)
                vec = vec / np.linalg.norm(vec)  # 归一化
                query_vecs.append(vec)
            
            num_queries = len(query_vecs)
            print(f"多标签搜索: 共 {num_queries} 个查询标签，权重: {weights_list}")
            
            results_with_similarity = []
            rows_with_keywords = 0
            rows_without_keywords = 0
            
            for row in rows:
                # 获取该图片的所有keyword向量
                cursor.execute("""
                    SELECT keyword, embedding
                    FROM keyword_embeddings
                    WHERE image_id = %s
                """, (row['id'],))
                
                keyword_vectors = cursor.fetchall()
                
                if not keyword_vectors:
                    rows_without_keywords += 1
                    continue
                
                rows_with_keywords += 1
                
                try:
                    # 对每个查询标签，计算与该图片所有keyword的最大相似度
                    query_similarities = []  # 存储每个查询标签的最大相似度
                    
                    for query_vec in query_vecs:
                        # 计算与每个keyword向量的相似度，取最大值
                        max_similarity_for_query = -1.0
                        
                        for kw_row in keyword_vectors:
                            keyword = kw_row['keyword']
                            embedding_bytes = kw_row['embedding']
                            
                            if embedding_bytes is None:
                                continue
                            
                            # 从BLOB读取向量
                            kw_vec = np.frombuffer(embedding_bytes, dtype=np.float32)
                            
                            # 检查向量维度是否正确（应该是768维）
                            if len(kw_vec) != 768:
                                print(f"警告: 图片ID {row['id']} 的keyword '{keyword}' 向量维度不正确: {len(kw_vec)}, 期望768")
                                continue
                            
                            kw_vec = kw_vec / np.linalg.norm(kw_vec)  # 归一化
                            
                            # 计算余弦相似度
                            similarity = float(np.dot(query_vec, kw_vec))
                            
                            # 更新最大相似度
                            if similarity > max_similarity_for_query:
                                max_similarity_for_query = similarity
                        
                        # 如果该查询标签的最大相似度有效，添加到列表
                        if max_similarity_for_query >= 0:
                            query_similarities.append(max_similarity_for_query)
                    
                    # 计算加权平均相似度 = 标签1相似度*标签1权重 + 标签2相似度*标签2权重 + ...
                    if query_similarities and len(query_similarities) == len(weights_list):
                        weighted_similarity = sum(
                            sim * weight for sim, weight in zip(query_similarities, weights_list)
                        )
                        
                        # 如果加权相似度达到阈值，添加到结果
                        if weighted_similarity >= similarity_threshold:
                            results_with_similarity.append((weighted_similarity, row, query_similarities))
                except Exception as e:
                    print(f"处理图片ID {row['id']} 的keyword向量时出错: {e}")
                    continue
            
            print(f"向量搜索统计: 总记录数={len(rows)}, 有关键词向量={rows_with_keywords}, 无关键词向量={rows_without_keywords}, 匹配数={len(results_with_similarity)}, 阈值={similarity_threshold}")
            
            if rows_with_keywords == 0:
                print("警告: 数据库中没有找到任何keyword向量数据！请确保图片已保存并生成了keyword向量。")
            
            # 按相似度降序排序
            results_with_similarity.sort(key=lambda x: x[0], reverse=True)
            
            # 限制结果数量
            results_with_similarity = results_with_similarity[:limit]
            
            # 构建结果列表
            results = []
            for similarity, row, query_similarities in results_with_similarity:
                # 获取该图片的所有标签
                cursor.execute("""
                    SELECT tag, tag_type FROM tags WHERE image_id = %s
                """, (row['id'],))
                
                tags = []
                keywords = []
                yolo_objects = []
                
                for tag_row in cursor.fetchall():
                    tag = tag_row['tag']
                    tag_type = tag_row['tag_type']
                    tags.append(tag)
                    if tag_type == 'keyword':
                        keywords.append(tag)
                    else:
                        yolo_objects.append(tag)
                
                # 解析 JSON 字段
                keywords_json = json.loads(row['keywords_json'] or '[]')
                qwen_captions = json.loads(row['qwen_captions_json'] or '[]')
                yolo_objects_json = json.loads(row['yolo_objects_json'] or '[]')
                
                results.append({
                    'id': row['id'],
                    'uuid': row['uuid'],
                    'filePath': row['relative_path'],
                    'fileName': row['file_name'],
                    'cameraId': row['camera_id'],
                    'szName': row['sz_name'],
                    'szTagRefs': _sz_tag_refs_from_db_value(row['sz_tag_ref_json']),
                    'createdAt': row['created_at'],
                    'description': row['description'],
                    'keywords': keywords_json,
                    'tags': tags,
                    'qwenCaptions': qwen_captions,
                    'yoloObjects': yolo_objects_json,
                    'similarity': similarity,  # 添加相似度字段
                })
        else:
            # 不使用向量搜索，按创建时间排序
            # 注意：如果指定了分页，rows 已经在 SQL 层面分页了
            # 如果没有分页参数，需要手动排序和限制
            if page is None or page_size is None:
                # 没有分页参数，使用原来的逻辑（向后兼容）
                sorted_rows = sorted(rows, key=lambda x: x['created_at'], reverse=True)[:limit]
                rows = sorted_rows
            
            results = []
            for row in rows:
                # 获取该图片的所有标签
                cursor.execute("""
                    SELECT tag, tag_type FROM tags WHERE image_id = %s
                """, (row['id'],))
                
                tags = []
                keywords = []
                yolo_objects = []
                
                for tag_row in cursor.fetchall():
                    tag = tag_row['tag']
                    tag_type = tag_row['tag_type']
                    tags.append(tag)
                    if tag_type == 'keyword':
                        keywords.append(tag)
                    else:
                        yolo_objects.append(tag)
                
                # 解析 JSON 字段
                keywords_json = json.loads(row['keywords_json'] or '[]')
                qwen_captions = json.loads(row['qwen_captions_json'] or '[]')
                yolo_objects_json = json.loads(row['yolo_objects_json'] or '[]')
                
                results.append({
                    'id': row['id'],
                    'uuid': row['uuid'],
                    'filePath': row['relative_path'],
                    'fileName': row['file_name'],
                    'cameraId': row['camera_id'],
                    'szName': row['sz_name'],
                    'szTagRefs': _sz_tag_refs_from_db_value(row['sz_tag_ref_json']),
                    'createdAt': row['created_at'],
                    'description': row['description'],
                    'keywords': keywords_json,
                    'tags': tags,
                    'qwenCaptions': qwen_captions,
                    'yoloObjects': yolo_objects_json,
                })
        
        # 对于向量搜索的情况，需要重新计算总数（因为过滤了相似度）
        if query_embeddings_list:
            # 向量搜索的结果总数是过滤后的数量
            total_count = len(results)
            
            # 如果需要分页，进行分页处理（向量搜索的结果已经在内存中）
            if page is not None and page_size is not None:
                # 页码从1开始，转换为索引从0开始
                start_idx = (page - 1) * page_size
                end_idx = start_idx + page_size
                results = results[start_idx:end_idx]
        # 对于非向量搜索的情况，total_count 已经在上面通过 COUNT 查询计算过了
        # 如果指定了分页，rows 已经在 SQL 层面分页了，不需要再次分页
        
        return results, total_count


def get_all_images(limit: int = 100) -> List[Dict[str, Any]]:
    """获取所有图片"""
    results, _ = search_images('', limit)
    return results


def get_image_by_uuid(image_uuid: str) -> Optional[Dict[str, Any]]:
    """根据 UUID 获取图片信息"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                i.id,
                i.uuid,
                i.file_path,
                i.relative_path,
                i.file_name,
                i.camera_id,
                i.sz_name,
                i.sz_tag_ref_json,
                i.created_at,
                ar.description,
                ar.keywords_json,
                ar.qwen_captions_json,
                ar.yolo_objects_json
            FROM images i
            LEFT JOIN analysis_results ar ON i.id = ar.image_id
            WHERE i.uuid = %s
        """, (image_uuid,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        # 获取标签
        cursor.execute("""
            SELECT tag, tag_type FROM tags WHERE image_id = %s
        """, (row['id'],))
        
        tags = []
        keywords = []
        yolo_objects = []
        
        for tag_row in cursor.fetchall():
            tag = tag_row['tag']
            tag_type = tag_row['tag_type']
            tags.append(tag)
            if tag_type == 'keyword':
                keywords.append(tag)
            else:
                yolo_objects.append(tag)
        
        keywords_json = json.loads(row['keywords_json'] or '[]')
        qwen_captions = json.loads(row['qwen_captions_json'] or '[]')
        yolo_objects_json = json.loads(row['yolo_objects_json'] or '[]')
        return {
            "uuid": row['uuid'],
            "file_path": row['file_path'],
            "file_name": row['file_name'],
            "camera_id": row['camera_id'],
            "sz_name": row['sz_name'],
            "sz_tag_refs": _sz_tag_refs_from_db_value(row['sz_tag_ref_json']),
            "created_at": row['created_at'],
            "description": row['description'],
            "tags": tags,
            "keywords": keywords, # 从 tags 表聚合
            "qwen_captions": qwen_captions,
            "yolo_objects": yolo_objects,   # 从 tags 表聚合
            "raw_keywords": keywords_json,
            "raw_yolo_objects": yolo_objects_json
        }


# --- 项目管理 ---
def upsert_analysis_results_and_tags_no_vectors(
    image_id: int,
    description: str,
    keywords: List[str],
    qwen_captions: Any,
    yolo_objects: List[str],
) -> None:
    """
    仅更新 analysis_results + tags，不生成/更新 keyword_embeddings，不触碰 Faiss。
    用于已有图片“补齐缺失标签”的场景。
    """
    now = datetime.now().isoformat()
    keywords = [k for k in (keywords or []) if k]
    yolo_objects = [o for o in (yolo_objects or []) if o]

    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM analysis_results WHERE image_id = %s", (image_id,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
                UPDATE analysis_results
                SET description = %s, keywords_json = %s, qwen_captions_json = %s, yolo_objects_json = %s, created_at = %s
                WHERE image_id = %s
            """, (
                description or "",
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(qwen_captions or [], ensure_ascii=False),
                json.dumps(yolo_objects, ensure_ascii=False),
                now,
                image_id
            ))
        else:
            cursor.execute("""
                INSERT INTO analysis_results (image_id, description, keywords_json, qwen_captions_json, yolo_objects_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                image_id,
                description or "",
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(qwen_captions or [], ensure_ascii=False),
                json.dumps(yolo_objects, ensure_ascii=False),
                now
            ))

        # 重建 tags（避免旧的空/脏数据）
        cursor.execute("DELETE FROM tags WHERE image_id = %s", (image_id,))
        for k in keywords:
            try:
                cursor.execute(
                    "INSERT INTO tags (image_id, tag, tag_type) VALUES (%s, %s, %s)",
                    (image_id, k, "keyword"),
                )
            except pymysql.err.IntegrityError:
                pass
        for o in yolo_objects:
            try:
                cursor.execute(
                    "INSERT INTO tags (image_id, tag, tag_type) VALUES (%s, %s, %s)",
                    (image_id, o, "yolo_object"),
                )
            except pymysql.err.IntegrityError:
                pass


def get_images_missing_keywords(limit: int = 2000) -> List[Dict[str, Any]]:
    """查询 keywords_json 为空的最新图片列表。"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                i.id,
                i.uuid,
                i.relative_path,
                i.file_name,
                i.created_at,
                i.camera_id,
                ar.keywords_json
            FROM images i
            LEFT JOIN analysis_results ar ON i.id = ar.image_id
            WHERE ar.keywords_json IS NULL OR TRIM(ar.keywords_json) = '[]'
            ORDER BY i.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def update_image_analysis_with_embeddings(
    image_id: int,
    description: str,
    keywords: List[str],
    qwen_captions: Any,
    yolo_objects: List[str],
    keyword_embeddings: List[tuple[str, bytes]],
) -> Dict[str, Any]:
    """
    更新 analysis_results、tags、keyword_embeddings。
    返回 images 表字段供调用方上传 MinIO JSON。
    """
    if not keyword_embeddings:
        raise ValueError("keyword_embeddings 不能为空")

    now = datetime.now().isoformat()
    keywords = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    yolo_objects = [str(o).strip() for o in (yolo_objects or []) if str(o).strip()]

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT relative_path, uuid, file_name FROM images WHERE id = %s",
            (image_id,),
        )
        img_row = cursor.fetchone()
        if not img_row:
            raise ValueError(f"图片 ID {image_id} 不存在于数据库中")

        cursor.execute("SELECT id FROM analysis_results WHERE image_id = %s", (image_id,))
        existing = cursor.fetchone()
        keywords_json_str = json.dumps(keywords, ensure_ascii=False)
        qwen_captions_json_str = json.dumps(qwen_captions or [], ensure_ascii=False)
        yolo_objects_json_str = json.dumps(yolo_objects, ensure_ascii=False)

        if existing:
            cursor.execute(
                """
                UPDATE analysis_results
                SET description = %s, keywords_json = %s, qwen_captions_json = %s,
                    yolo_objects_json = %s, created_at = %s
                WHERE image_id = %s
                """,
                (
                    description or "",
                    keywords_json_str,
                    qwen_captions_json_str,
                    yolo_objects_json_str,
                    now,
                    image_id,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO analysis_results
                (image_id, description, keywords_json, qwen_captions_json, yolo_objects_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    image_id,
                    description or "",
                    keywords_json_str,
                    qwen_captions_json_str,
                    yolo_objects_json_str,
                    now,
                ),
            )

        cursor.execute("DELETE FROM keyword_embeddings WHERE image_id = %s", (image_id,))
        for keyword, embedding_bytes in keyword_embeddings:
            cursor.execute(
                """
                INSERT INTO keyword_embeddings (image_id, keyword, embedding, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (image_id, keyword, embedding_bytes, now),
            )

        cursor.execute("DELETE FROM tags WHERE image_id = %s", (image_id,))
        for k in keywords:
            try:
                cursor.execute(
                    "INSERT INTO tags (image_id, tag, tag_type) VALUES (%s, %s, %s)",
                    (image_id, k, "keyword"),
                )
            except pymysql.err.IntegrityError:
                pass
        for o in yolo_objects:
            try:
                cursor.execute(
                    "INSERT INTO tags (image_id, tag, tag_type) VALUES (%s, %s, %s)",
                    (image_id, o, "yolo_object"),
                )
            except pymysql.err.IntegrityError:
                pass

        return {
            "relative_path": img_row["relative_path"],
            "uuid": img_row["uuid"],
            "file_name": img_row["file_name"],
            "created_at": now,
        }


def get_all_projects_db() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]

def add_project_db(project_id: str, name: str, script_path: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        created_at = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO projects (id, name, script_path, created_at, status, ai_model) VALUES (%s, %s, %s, %s, %s, %s)",
            (project_id, name, script_path, created_at, 'idle', 'gemini')
        )

def update_project_model_db(project_id: str, model: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET ai_model = %s WHERE id = %s", (model, project_id))
        
def update_project_probability_db(project_id: str, prob: float):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET api_probability = %s WHERE id = %s", (prob, project_id))

def update_project_stop_time_db(project_name_or_script: str):
    """Update last_stopped_at for a project based on script path match"""
    # Note: frontend passes script_path to stop api, so we might need to find project by script_path
    # Or simplified: pass script_path, find project, update.
    script_name = os.path.basename(project_name_or_script)
    now_str = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Like operator to match partial path if needed, but safer to match basename if stored as full path
        # Assuming script_path column changes. 
        # Actually simplest is to fuzzy match script_path.
        cursor.execute(
            "UPDATE projects SET last_stopped_at = %s, status = 'idle' WHERE script_path LIKE %s",
            (now_str, f"%{script_name}"),
        )


def update_project_status_by_script_db(script_path: str, status: str):
    """按脚本路径更新 projects.status（running / idle）。"""
    script_name = os.path.basename(script_path)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE projects SET status = %s WHERE script_path LIKE %s",
            (status, f"%{script_name}"),
        )

def delete_project_db(project_id: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))

def update_project_db(project_id: str, updates: Dict[str, Any]):
    # columns: name, schedule_enabled, schedule_interval, last_run, status, script_path
    allowed_cols = {'name', 'schedule_enabled', 'schedule_interval', 'last_run', 'status', 'script_path'}
    
    set_clauses = []
    values = []
    for col, val in updates.items():
        if col in allowed_cols:
            set_clauses.append(f"{col} = %s")
            values.append(int(val) if isinstance(val, bool) else val)
            
    if not set_clauses:
        return
        
    values.append(project_id)
    sql = f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = %s"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, values)

def delete_image_by_uuid(image_uuid: str) -> bool:
    """根据 UUID 删除图片及其关联记录。"""
    started_at = time.time()
    print(f"[delete_image_by_uuid] start uuid={image_uuid}")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        t0 = time.time()
        cursor.execute("SELECT id FROM images WHERE uuid = %s", (image_uuid,))
        row = cursor.fetchone()
        print(f"[delete_image_by_uuid] select image id cost={time.time()-t0:.3f}s")
        if not row:
            print(f"[delete_image_by_uuid] uuid not found uuid={image_uuid}")
            return False
        image_id = int(row["id"])
        print(f"[delete_image_by_uuid] image_id={image_id}")

        t1 = time.time()
        cursor.execute("DELETE FROM tags WHERE image_id = %s", (image_id,))
        print(f"[delete_image_by_uuid] delete tags affected={cursor.rowcount} cost={time.time()-t1:.3f}s")

        t2 = time.time()
        cursor.execute("DELETE FROM keyword_embeddings WHERE image_id = %s", (image_id,))
        print(f"[delete_image_by_uuid] delete keyword_embeddings affected={cursor.rowcount} cost={time.time()-t2:.3f}s")

        t3 = time.time()
        cursor.execute("DELETE FROM analysis_results WHERE image_id = %s", (image_id,))
        print(f"[delete_image_by_uuid] delete analysis_results affected={cursor.rowcount} cost={time.time()-t3:.3f}s")

        t4 = time.time()
        cursor.execute("DELETE FROM images WHERE id = %s", (image_id,))
        affected = cursor.rowcount
        print(f"[delete_image_by_uuid] delete images affected={affected} cost={time.time()-t4:.3f}s")
        print(f"[delete_image_by_uuid] done uuid={image_uuid} total_cost={time.time()-started_at:.3f}s")
        return affected > 0

def get_images_by_path_prefix(prefix: str) -> List[Dict[str, Any]]:
    """获取指定路径前缀的所有图片"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 注意：这里的 relative_path 可能不包含 prefix 的全部（比如 prefix 是 'foo/', relative_path 是 'foo/bar.jpg'）
        # 但我们通常根据 relative_path 来匹配
        cursor.execute("""
            SELECT id, uuid, relative_path, file_name, created_at, file_path
            FROM images 
            WHERE relative_path LIKE %s
        """, (f"{prefix}%",))
        
        return [dict(row) for row in cursor.fetchall()]

def get_all_image_uuids() -> List[str]:
    """获取所有图片的 UUID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT uuid FROM images")
        return [row['uuid'] for row in cursor.fetchall()]

def check_keyword_vector_exists(image_id: int) -> bool:
    """检查图片是否存在 keyword 向量 (DB中)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM keyword_embeddings WHERE image_id = %s", (image_id,))
        count = int(cursor.fetchone()['cnt'])
        return count > 0
