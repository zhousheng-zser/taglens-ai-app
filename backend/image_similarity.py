# -*- coding: utf-8 -*-
"""
图片相似度检测模块 - 使用 OpenCV 传统算法
支持多种相似度算法：直方图比较、模板匹配、感知哈希等
"""
import cv2
import numpy as np
from typing import Tuple, Optional, Dict, Any
from pathlib import Path
import base64
from io import BytesIO
from PIL import Image
import logging

# 配置日志 - 使用 print 输出到控制台，方便查看
class SimpleLogger:
    """简单的日志记录器，直接输出到控制台"""
    def info(self, msg):
        print(msg)
    
    def warning(self, msg):
        print(f"WARNING: {msg}")
    
    def error(self, msg):
        print(f"ERROR: {msg}")

logger = SimpleLogger()


def decode_base64_image(data_uri: str) -> np.ndarray:
    """
    从 base64 data URI 解码图片为 OpenCV 格式
    
    参数:
        data_uri: base64 编码的图片 data URI (格式: data:image/jpeg;base64,...)
    
    返回:
        np.ndarray: OpenCV 格式的图片 (BGR)
    """
    # 提取 base64 数据
    if ',' in data_uri:
        header, base64_data = data_uri.split(',', 1)
    else:
        base64_data = data_uri
    
    # 解码 base64
    image_data = base64.b64decode(base64_data)
    
    # 转换为 numpy 数组
    nparr = np.frombuffer(image_data, np.uint8)
    
    # 解码为 OpenCV 格式 (BGR)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        raise ValueError("无法解码图片数据")
    
    return img


def load_image_from_path(file_path: str) -> np.ndarray:
    """
    从文件路径加载图片
    
    参数:
        file_path: 图片文件路径
    
    返回:
        np.ndarray: OpenCV 格式的图片 (BGR)
    """
    img = cv2.imread(file_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法加载图片: {file_path}")
    return img


def resize_image(img: np.ndarray, max_size: int = 512) -> np.ndarray:
    """
    调整图片大小，保持宽高比
    
    参数:
        img: 输入图片
        max_size: 最大尺寸（宽或高的最大值）
    
    返回:
        np.ndarray: 调整后的图片
    """
    h, w = img.shape[:2]
    if max(h, w) <= max_size:
        return img
    
    if h > w:
        new_h = max_size
        new_w = int(w * max_size / h)
    else:
        new_w = max_size
        new_h = int(h * max_size / w)
    
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)


def extract_histogram_vector(img: np.ndarray) -> bytes:
    """
    提取图片的直方图向量（归一化后的直方图）
    
    参数:
        img: 输入图片 (BGR)
    
    返回:
        bytes: 归一化后的直方图向量（float32格式的BLOB）
    """
    # 调整图片大小
    img_resized = resize_image(img, 256)
    
    # 转换为 HSV 颜色空间
    hsv = cv2.cvtColor(img_resized, cv2.COLOR_BGR2HSV)
    
    # 计算直方图
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [50, 60, 60], [0, 180, 0, 256, 0, 256])
    
    # 归一化直方图
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    
    # 转换为float32并序列化为bytes
    hist_flat = hist.flatten().astype(np.float32)
    return hist_flat.tobytes()


def compare_histogram_vectors(hist1_bytes: bytes, hist2_bytes: bytes) -> Dict[str, float]:
    """
    比较两个直方图向量（从数据库读取的）
    
    参数:
        hist1_bytes: 第一个直方图向量（bytes格式）
        hist2_bytes: 第二个直方图向量（bytes格式）
    
    返回:
        Dict[str, float]: 包含多种直方图比较方法的相似度分数 (0-1, 1表示完全相同)
    """
    # 从bytes恢复直方图
    hist1_flat = np.frombuffer(hist1_bytes, dtype=np.float32)
    hist2_flat = np.frombuffer(hist2_bytes, dtype=np.float32)
    
    # 恢复为3D形状 [50, 60, 60]
    hist1 = hist1_flat.reshape(50, 60, 60)
    hist2 = hist2_flat.reshape(50, 60, 60)
    
    # 使用多种方法比较直方图
    correlation = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    chi_square = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CHISQR)
    intersection = cv2.compareHist(hist1, hist2, cv2.HISTCMP_INTERSECT)
    bhattacharyya = cv2.compareHist(hist1, hist2, cv2.HISTCMP_BHATTACHARYYA)
    
    # 归一化结果到 0-1 范围（与compare_histograms相同的逻辑）
    if np.isnan(correlation) or np.isinf(correlation):
        correlation_normalized = 0.0
    else:
        correlation_normalized = float((correlation + 1.0) / 2.0)
        correlation_normalized = max(0.0, min(1.0, correlation_normalized))
    
    if np.isnan(chi_square) or np.isinf(chi_square):
        chi_square_normalized = 0.0
    else:
        chi_square_normalized = float(1.0 / (1.0 + chi_square / 1000.0))
        chi_square_normalized = max(0.0, min(1.0, chi_square_normalized))
    
    if np.isnan(intersection) or np.isinf(intersection):
        intersection_normalized = 0.0
    else:
        intersection_normalized = float(min(1.0, intersection))
        intersection_normalized = max(0.0, min(1.0, intersection_normalized))
    
    if np.isnan(bhattacharyya) or np.isinf(bhattacharyya):
        bhattacharyya_similarity = 0.0
    else:
        bhattacharyya_similarity = float(1.0 - bhattacharyya)
        bhattacharyya_similarity = max(0.0, min(1.0, bhattacharyya_similarity))
    
    # 计算平均值
    valid_scores = []
    if not np.isnan(correlation_normalized):
        valid_scores.append(correlation_normalized)
    if not np.isnan(chi_square_normalized):
        valid_scores.append(chi_square_normalized)
    if not np.isnan(intersection_normalized):
        valid_scores.append(intersection_normalized)
    if not np.isnan(bhattacharyya_similarity):
        valid_scores.append(bhattacharyya_similarity)
    
    if valid_scores:
        average = float(np.mean(valid_scores))
    else:
        average = 0.0
    
    result = {
        'correlation': float(correlation_normalized),
        'chi_square': float(chi_square_normalized),
        'intersection': float(intersection_normalized),
        'bhattacharyya': float(bhattacharyya_similarity),
        'average': average
    }
    
    # 打印日志
    logger.info(f"[直方图比较] CORREL={correlation:.4f}→{correlation_normalized:.4f}, "
                f"CHISQR={chi_square:.4f}→{chi_square_normalized:.4f}, "
                f"INTERSECT={intersection:.4f}→{intersection_normalized:.4f}, "
                f"BHATTACHARYYA={bhattacharyya:.4f}→{bhattacharyya_similarity:.4f}, "
                f"平均={average:.4f}")
    
    return result


def compare_histograms(img1: np.ndarray, img2: np.ndarray) -> Dict[str, float]:
    """
    使用直方图比较两张图片的相似度
    
    参数:
        img1: 第一张图片 (BGR)
        img2: 第二张图片 (BGR)
    
    返回:
        Dict[str, float]: 包含多种直方图比较方法的相似度分数 (0-1, 1表示完全相同)
    """
    # 调整图片大小一致
    img1_resized = resize_image(img1, 256)
    img2_resized = resize_image(img2, 256)
    
    # 转换为 HSV 颜色空间
    hsv1 = cv2.cvtColor(img1_resized, cv2.COLOR_BGR2HSV)
    hsv2 = cv2.cvtColor(img2_resized, cv2.COLOR_BGR2HSV)
    
    # 计算直方图
    hist1 = cv2.calcHist([hsv1], [0, 1, 2], None, [50, 60, 60], [0, 180, 0, 256, 0, 256])
    hist2 = cv2.calcHist([hsv2], [0, 1, 2], None, [50, 60, 60], [0, 180, 0, 256, 0, 256])
    
    # 归一化直方图
    cv2.normalize(hist1, hist1, 0, 1, cv2.NORM_MINMAX)
    cv2.normalize(hist2, hist2, 0, 1, cv2.NORM_MINMAX)
    
    # 使用多种方法比较直方图
    correlation = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    chi_square = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CHISQR)
    intersection = cv2.compareHist(hist1, hist2, cv2.HISTCMP_INTERSECT)
    bhattacharyya = cv2.compareHist(hist1, hist2, cv2.HISTCMP_BHATTACHARYYA)
    
    # 归一化结果到 0-1 范围
    # CORREL: [-1, 1] 或 nan，越大越相似，需要归一化到 [0, 1]
    # CHISQR: [0, ∞)，越小越相似，需要归一化
    # INTERSECT: [0, 1]（如果直方图已归一化），但实际可能更大，需要归一化
    # BHATTACHARYYA: [0, 1]，越小越相似，需要转换为相似度
    
    # 处理 CORREL: 从 [-1, 1] 归一化到 [0, 1]，处理 nan
    if np.isnan(correlation) or np.isinf(correlation):
        correlation_normalized = 0.0  # nan 或 inf 时设为0（不相似）
    else:
        # 将 [-1, 1] 映射到 [0, 1]: (correlation + 1) / 2
        correlation_normalized = float((correlation + 1.0) / 2.0)
        correlation_normalized = max(0.0, min(1.0, correlation_normalized))  # 确保在 [0, 1] 范围内
    
    # 处理 CHISQR: 归一化到 [0, 1]
    if np.isnan(chi_square) or np.isinf(chi_square):
        chi_square_normalized = 0.0
    else:
        chi_square_normalized = float(1.0 / (1.0 + chi_square / 1000.0))
        chi_square_normalized = max(0.0, min(1.0, chi_square_normalized))
    
    # 处理 INTERSECT: 归一化到 [0, 1]
    # INTERSECT 返回的是所有bin的最小值之和，理论上如果直方图已归一化，最大值应该是1
    # 但实际可能更大，所以需要归一化
    if np.isnan(intersection) or np.isinf(intersection):
        intersection_normalized = 0.0
    else:
        # 使用 min(1.0, intersection) 来限制最大值，或者除以理论最大值
        intersection_normalized = float(min(1.0, intersection))
        intersection_normalized = max(0.0, min(1.0, intersection_normalized))
    
    # 处理 BHATTACHARYYA: 转换为相似度 [0, 1]
    if np.isnan(bhattacharyya) or np.isinf(bhattacharyya):
        bhattacharyya_similarity = 0.0
    else:
        bhattacharyya_similarity = float(1.0 - bhattacharyya)
        bhattacharyya_similarity = max(0.0, min(1.0, bhattacharyya_similarity))
    
    # 计算平均值（只使用有效的相似度值）
    valid_scores = []
    if not np.isnan(correlation_normalized):
        valid_scores.append(correlation_normalized)
    if not np.isnan(chi_square_normalized):
        valid_scores.append(chi_square_normalized)
    if not np.isnan(intersection_normalized):
        valid_scores.append(intersection_normalized)
    if not np.isnan(bhattacharyya_similarity):
        valid_scores.append(bhattacharyya_similarity)
    
    if valid_scores:
        average = float(np.mean(valid_scores))
    else:
        average = 0.0
    
    result = {
        'correlation': float(correlation_normalized),  # 返回归一化后的值
        'chi_square': float(chi_square_normalized),
        'intersection': float(intersection_normalized),  # 返回归一化后的值
        'bhattacharyya': float(bhattacharyya_similarity),
        'average': average
    }
    
    # 打印日志（显示原始值和归一化后的值）
    logger.info(f"[直方图比较] CORREL={correlation:.4f}→{correlation_normalized:.4f}, "
                f"CHISQR={chi_square:.4f}→{chi_square_normalized:.4f}, "
                f"INTERSECT={intersection:.4f}→{intersection_normalized:.4f}, "
                f"BHATTACHARYYA={bhattacharyya:.4f}→{bhattacharyya_similarity:.4f}, "
                f"平均={average:.4f}")
    
    return result


def compare_images(img1: np.ndarray, img2: np.ndarray, methods: Optional[list] = None, image_uuid: Optional[str] = None) -> Dict[str, Any]:
    """
    综合比较两张图片的相似度，使用多种算法
    
    参数:
        img1: 第一张图片
        img2: 第二张图片
        methods: 要使用的方法列表，None 表示使用所有方法
                可选值: ['histogram']
        image_uuid: 数据库图片的UUID，用于日志标识
    
    返回:
        Dict[str, Any]: 包含所有算法结果的字典
    """
    if methods is None:
        methods = ['histogram']
    
    uuid_str = f" (UUID: {image_uuid})" if image_uuid else ""
    logger.info(f"{'='*60}")
    logger.info(f"开始图片相似度比较{uuid_str}")
    logger.info(f"使用方法: {', '.join(methods)}")
    
    results = {}
    
    # 直方图比较
    if 'histogram' in methods:
        try:
            results['histogram'] = compare_histograms(img1, img2)
        except Exception as e:
            results['histogram'] = {'error': str(e)}
    
    # 计算综合相似度分数
    similarity_scores = []
    
    if 'histogram' in results and 'average' in results['histogram']:
        similarity_scores.append(results['histogram']['average'])
    
    if similarity_scores:
        results['overall_similarity'] = float(np.mean(similarity_scores))
        results['max_similarity'] = float(np.max(similarity_scores))
        results['min_similarity'] = float(np.min(similarity_scores))
    else:
        results['overall_similarity'] = 0.0
        results['max_similarity'] = 0.0
        results['min_similarity'] = 0.0
    
    # 打印综合结果
    logger.info(f"{'='*60}")
    logger.info(f"相似度比较结果{uuid_str}:")
    logger.info(f"  综合相似度: {results['overall_similarity']:.4f} ({results['overall_similarity']*100:.2f}%)")
    logger.info(f"  最大相似度: {results['max_similarity']:.4f} ({results['max_similarity']*100:.2f}%)")
    logger.info(f"  最小相似度: {results['min_similarity']:.4f} ({results['min_similarity']*100:.2f}%)")
    logger.info(f"{'='*60}")
    
    return results
