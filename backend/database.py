# -*- coding: utf-8 -*-
"""
数据库模块 - 使用 SQLite 存储图片标签和元数据
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

# 数据库文件路径
DB_PATH = Path(__file__).parent.parent / "data" / "taglens.db"


def get_db_path() -> Path:
    """获取数据库文件路径，确保目录存在"""
    db_path = DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


@contextmanager
def get_db_connection():
    """获取数据库连接的上下文管理器"""
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """初始化数据库，创建表结构"""
    db_path = get_db_path()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 创建图片表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                file_path TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                file_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # 创建标签表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                tag_type TEXT NOT NULL,  -- 'keyword' 或 'yolo_object'
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
                UNIQUE(image_id, tag, tag_type)
            )
        """)
        
        # 创建分析结果表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER NOT NULL UNIQUE,
                description TEXT NOT NULL,
                keywords_json TEXT NOT NULL,  -- JSON 格式的关键词数组
                clip_captions_json TEXT NOT NULL,  -- JSON 格式的 CLIP 描述数组
                qwen_captions_json TEXT NOT NULL,  -- JSON 格式的 Qwen 描述数组
                yolo_objects_json TEXT NOT NULL,  -- JSON 格式的 YOLO 对象数组
                created_at TEXT NOT NULL,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            )
        """)
        
        # 创建keyword向量表（每个keyword对应一个向量）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS keyword_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                embedding BLOB NOT NULL,  -- BGE向量化后的768维float32向量（BLOB格式）
                created_at TEXT NOT NULL,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
                UNIQUE(image_id, keyword)
            )
        """)
        
        # 如果表已存在但没有某些字段，则添加该字段
        try:
            cursor.execute("ALTER TABLE analysis_results ADD COLUMN qwen_captions_json TEXT DEFAULT '[]'")
            print("已添加 qwen_captions_json 字段到 analysis_results 表")
        except Exception:
            # 字段已存在，忽略错误
            pass
        
        # 创建索引以提高搜索性能
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_images_uuid ON images(uuid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_images_created_at ON images(created_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_image_id ON tags(image_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_type ON tags(tag_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_analysis_image_id ON analysis_results(image_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_keyword_embeddings_image_id ON keyword_embeddings(image_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_keyword_embeddings_keyword ON keyword_embeddings(keyword)
        """)
        
        print(f"数据库初始化完成: {db_path}")


def save_image_to_db(
    image_uuid: str,
    file_path: str,
    relative_path: str,
    file_name: Optional[str],
    tags: List[str],
    keywords: List[str],
    description: str,
    clip_captions: List[str],
    qwen_captions: List[str],
    yolo_objects: List[str],
    keyword_embeddings: Optional[List[tuple[str, bytes]]] = None  # List of (keyword, embedding_bytes) tuples
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
            INSERT INTO images (uuid, file_path, relative_path, file_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (image_uuid, file_path, relative_path, file_name, now, now))
        
        image_id = cursor.lastrowid
        
        # 插入标签 - 先插入 keywords
        for keyword in keywords:
            try:
                cursor.execute("""
                    INSERT INTO tags (image_id, tag, tag_type)
                    VALUES (?, ?, ?)
                """, (image_id, keyword, 'keyword'))
            except sqlite3.IntegrityError:
                # 如果标签已存在，忽略
                pass
        
        # 再插入 yolo_objects
        for yolo_obj in yolo_objects:
            try:
                cursor.execute("""
                    INSERT INTO tags (image_id, tag, tag_type)
                    VALUES (?, ?, ?)
                """, (image_id, yolo_obj, 'yolo_object'))
            except sqlite3.IntegrityError:
                # 如果标签已存在，忽略
                pass
        
        # 插入分析结果
        cursor.execute("""
            INSERT INTO analysis_results (
                image_id, description, keywords_json, 
                clip_captions_json, qwen_captions_json, yolo_objects_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            image_id,
            description,
            json.dumps(keywords, ensure_ascii=False),
            json.dumps(clip_captions, ensure_ascii=False),
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
                        VALUES (?, ?, ?, ?)
                    """, (image_id, keyword, embedding_bytes, now))
                except sqlite3.IntegrityError:
                    # 如果keyword向量已存在，更新它
                    cursor.execute("""
                        UPDATE keyword_embeddings 
                        SET embedding = ?, created_at = ?
                        WHERE image_id = ? AND keyword = ?
                    """, (embedding_bytes, now, image_id, keyword))
        
        return image_id


def search_images(
    query: str, 
    limit: int = 100,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    query_embedding: Optional[bytes] = None,  # 查询文本的向量化结果
    similarity_threshold: float = 0.3  # 相似度阈值
) -> List[Dict[str, Any]]:
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
        
        # 时间范围条件
        if start_date:
            where_conditions.append("i.created_at >= ?")
            params.append(start_date)
        
        if end_date:
            where_conditions.append("i.created_at <= ?")
            params.append(end_date)
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        # 查询所有符合条件的图片
        sql = f"""
            SELECT DISTINCT
                i.id,
                i.uuid,
                i.file_path,
                i.relative_path,
                i.file_name,
                i.created_at,
                ar.description,
                ar.keywords_json,
                ar.clip_captions_json,
                ar.qwen_captions_json,
                ar.yolo_objects_json
            FROM images i
            LEFT JOIN analysis_results ar ON i.id = ar.image_id
            WHERE {where_clause}
        """
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        # 如果使用向量搜索，计算相似度并过滤
        if query_embedding is not None:
            query_vec = np.frombuffer(query_embedding, dtype=np.float32)
            query_vec = query_vec / np.linalg.norm(query_vec)  # 归一化
            
            results_with_similarity = []
            rows_with_keywords = 0
            rows_without_keywords = 0
            
            for row in rows:
                # 获取该图片的所有keyword向量
                cursor.execute("""
                    SELECT keyword, embedding
                    FROM keyword_embeddings
                    WHERE image_id = ?
                """, (row['id'],))
                
                keyword_vectors = cursor.fetchall()
                
                if not keyword_vectors:
                    rows_without_keywords += 1
                    continue
                
                rows_with_keywords += 1
                
                try:
                    # 计算与每个keyword向量的相似度，取最大值
                    max_similarity = -1.0
                    best_keyword = None
                    
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
                        if similarity > max_similarity:
                            max_similarity = similarity
                            best_keyword = keyword
                    
                    # 如果最大相似度达到阈值，添加到结果
                    if max_similarity >= similarity_threshold:
                        results_with_similarity.append((max_similarity, row, best_keyword))
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
            for similarity, row, best_keyword in results_with_similarity:
                # 获取该图片的所有标签
                cursor.execute("""
                    SELECT tag, tag_type FROM tags WHERE image_id = ?
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
                clip_captions = json.loads(row['clip_captions_json'] or '[]')
                qwen_captions = json.loads(row['qwen_captions_json'] or '[]')
                yolo_objects_json = json.loads(row['yolo_objects_json'] or '[]')
                
                results.append({
                    'id': row['id'],
                    'uuid': row['uuid'],
                    'filePath': row['relative_path'],
                    'fileName': row['file_name'],
                    'createdAt': row['created_at'],
                    'description': row['description'],
                    'keywords': keywords_json,
                    'tags': tags,
                    'clipCaptions': clip_captions,
                    'qwenCaptions': qwen_captions,
                    'yoloObjects': yolo_objects_json,
                    'similarity': similarity,  # 添加相似度字段
                })
        else:
            # 不使用向量搜索，按创建时间排序
            results = []
            sorted_rows = sorted(rows, key=lambda x: x['created_at'], reverse=True)[:limit]
            
            for row in sorted_rows:
                # 获取该图片的所有标签
                cursor.execute("""
                    SELECT tag, tag_type FROM tags WHERE image_id = ?
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
                clip_captions = json.loads(row['clip_captions_json'] or '[]')
                qwen_captions = json.loads(row['qwen_captions_json'] or '[]')
                yolo_objects_json = json.loads(row['yolo_objects_json'] or '[]')
                
                results.append({
                    'id': row['id'],
                    'uuid': row['uuid'],
                    'filePath': row['relative_path'],
                    'fileName': row['file_name'],
                    'createdAt': row['created_at'],
                    'description': row['description'],
                    'keywords': keywords_json,
                    'tags': tags,
                    'clipCaptions': clip_captions,
                    'qwenCaptions': qwen_captions,
                    'yoloObjects': yolo_objects_json,
                })
        
        return results


def get_all_images(limit: int = 100) -> List[Dict[str, Any]]:
    """获取所有图片"""
    return search_images('', limit)


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
                i.created_at,
                ar.description,
                ar.keywords_json,
                ar.clip_captions_json,
                ar.qwen_captions_json,
                ar.yolo_objects_json
            FROM images i
            LEFT JOIN analysis_results ar ON i.id = ar.image_id
            WHERE i.uuid = ?
        """, (image_uuid,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        # 获取标签
        cursor.execute("""
            SELECT tag, tag_type FROM tags WHERE image_id = ?
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
        clip_captions = json.loads(row['clip_captions_json'] or '[]')
        qwen_captions = json.loads(row['qwen_captions_json'] or '[]')
        yolo_objects_json = json.loads(row['yolo_objects_json'] or '[]')
        
        return {
            'id': row['id'],
            'uuid': row['uuid'],
            'filePath': row['relative_path'],
            'fileName': row['file_name'],
            'createdAt': row['created_at'],
            'description': row['description'],
            'keywords': keywords_json,
            'tags': tags,
            'clipCaptions': clip_captions,
            'qwenCaptions': qwen_captions,
            'yoloObjects': yolo_objects_json,
        }
