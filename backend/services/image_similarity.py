# -*- coding: utf-8 -*-
"""
图片相似度检测模块 - 空间分块直方图向量提取
用于 Faiss 索引的图片特征向量提取
"""
import cv2
import base64
import numpy as np
from PIL import Image


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
    if hasattr(img, 'size') and not hasattr(img, 'shape'):
        img = np.array(img)
        # PIL RGB -> OpenCV BGR
        if len(img.shape) == 3 and img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

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


def extract_spatial_histogram_vector(img: np.ndarray, grid_size: int = 3, bins: tuple = (10, 10, 10)) -> np.ndarray:
    """
    提取图片的空间分块直方图向量（用于 Faiss LSH）
    
    参数:
        img: 输入图片 (BGR格式)
        grid_size: 网格大小，3x3=9块
        bins: 每个通道的bin数量 (H, S, V)，默认(10, 10, 10) = 1000维/块
    
    返回:
    返回:
        np.ndarray: 归一化后的特征向量（float32，9000维）
    """
    if hasattr(img, 'size') and not hasattr(img, 'shape'):
        img = np.array(img)
         # PIL RGB -> OpenCV BGR
        if len(img.shape) == 3 and img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    # 调整图片大小（统一尺寸以便分块）
    img_resized = resize_image(img, max_size=256)
    h, w = img_resized.shape[:2]
    
    # 转换为 HSV 颜色空间
    hsv = cv2.cvtColor(img_resized, cv2.COLOR_BGR2HSV)
    
    # 计算每个块的大小
    block_h = h // grid_size
    block_w = w // grid_size
    
    # 存储所有块的特征向量
    all_features = []
    
    # 遍历每个网格块
    for i in range(grid_size):
        for j in range(grid_size):
            # 计算块的边界
            y_start = i * block_h
            y_end = (i + 1) * block_h if i < grid_size - 1 else h
            x_start = j * block_w
            x_end = (j + 1) * block_w if j < grid_size - 1 else w
            
            # 提取当前块
            block = hsv[y_start:y_end, x_start:x_end]
            
            # 计算当前块的直方图 [10, 10, 10]
            hist = cv2.calcHist(
                [block], 
                [0, 1, 2],  # H, S, V三个通道
                None, 
                bins,  # [10, 10, 10]
                [0, 180, 0, 256, 0, 256]
            )
            
            # 归一化直方图
            cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
            
            # 展平为1维数组并添加到总特征
            hist_flat = hist.flatten()
            all_features.append(hist_flat)
    
    # 合并所有块的特征向量
    combined_features = np.concatenate(all_features).astype(np.float32)
    
    return combined_features
