# -*- coding: utf-8 -*-
"""
Faiss LSH 索引测试程序（汉明距离）
测试图片相似度搜索功能：
1. 将 A.jpg 使用 LSH 索引入库
2. 使用 B.jpg 搜索相似图片
"""
import sys
from pathlib import Path

# 添加父目录到路径，以便导入模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from faiss_index_manager import FaissIndexManager
from image_similarity import load_image_from_path, extract_spatial_histogram_vector
import uuid


def main():
    """主测试函数"""
    # 设置测试目录
    test_dir = Path(__file__).parent
    a_image_path = test_dir / "A.jpg"
    b_image_path = test_dir / "B.jpg"
    
    # 检查图片文件是否存在
    if not a_image_path.exists():
        print(f"错误: 找不到图片文件 {a_image_path}")
        print("请将 A.jpg 放入 test 文件夹")
        return
    
    if not b_image_path.exists():
        print(f"错误: 找不到图片文件 {b_image_path}")
        print("请将 B.jpg 放入 test 文件夹")
        return
    
    print("=" * 60)
    print("Faiss LSH 索引测试程序（汉明距离）")
    print("=" * 60)
    
    # 初始化 Faiss LSH 索引管理器（使用汉明距离）
    print("\n1. 初始化 Faiss LSH 索引管理器...")
    data_dir = Path(__file__).parent.parent.parent / "data"
    faiss_manager = FaissIndexManager(
        data_dir=str(data_dir)
    )
    
    print(f"   索引类型: {faiss_manager.index_type}")
    print(f"   向量维度: {faiss_manager.uuid_map.get('vector_dimension', 9000)}")
    print(f"   nbits: {faiss_manager.uuid_map.get('nbits', 128)}")
    print(f"   当前索引中的向量数: {faiss_manager.get_total_vectors()}")
    
    # 步骤1: 加载 A.jpg 并提取特征向量
    print("\n2. 加载 A.jpg 并提取空间分块直方图向量...")
    try:
        img_a = load_image_from_path(str(a_image_path))
        print(f"   ✓ 成功加载图片: {a_image_path}")
        print(f"   图片尺寸: {img_a.shape}")
        
        vector_a = extract_spatial_histogram_vector(img_a)
        print(f"   ✓ 成功提取特征向量")
        print(f"   向量维度: {len(vector_a)}")
        print(f"   向量类型: {vector_a.dtype}")
    except Exception as e:
        print(f"   ✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 步骤2: 将 A.jpg 的向量添加到 LSH 索引
    print("\n3. 将 A.jpg 的向量添加到 Faiss LSH 索引...")
    uuid_a = str(uuid.uuid4())
    print(f"   生成的 UUID: {uuid_a}")
    
    success = faiss_manager.add_vector(uuid_a, vector_a)
    if success:
        print(f"   ✓ 成功将向量添加到索引")
        print(f"   当前索引中的向量数: {faiss_manager.get_total_vectors()}")
        
        # 保存索引
        print("\n4. 保存索引到文件...")
        faiss_manager.save_index()
        print(f"   ✓ 索引已保存")
    else:
        print(f"   ✗ 添加向量失败")
        return
    
    # 步骤3: 加载 B.jpg 并提取特征向量
    print("\n5. 加载 B.jpg 并提取空间分块直方图向量...")
    try:
        img_b = load_image_from_path(str(b_image_path))
        print(f"   ✓ 成功加载图片: {b_image_path}")
        print(f"   图片尺寸: {img_b.shape}")
        
        vector_b = extract_spatial_histogram_vector(img_b)
        print(f"   ✓ 成功提取特征向量")
        print(f"   向量维度: {len(vector_b)}")
        print(f"   向量类型: {vector_b.dtype}")
    except Exception as e:
        print(f"   ✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 步骤4: 使用 B.jpg 的向量搜索相似图片
    print("\n6. 使用 B.jpg 的向量搜索相似图片...")
    print("   搜索参数:")
    print(f"   - 返回最相似的 k=5 个结果")
    print(f"   - 相似度阈值: 0.5 (50%)")
    
    results = faiss_manager.search_similar(
        query_vector=vector_b,
        k=5,
        threshold=0.5
    )
    
    # 显示搜索结果
    print(f"\n7. 搜索结果:")
    print("=" * 60)
    if results:
        print(f"   找到 {len(results)} 个相似图片:")
        for i, result in enumerate(results, 1):
            print(f"\n   结果 {i}:")
            print(f"     UUID: {result['uuid']}")
            print(f"     索引ID: {result['index']}")
            print(f"     汉明距离: {result['distance']:.2f}")
            print(f"     相似度: {result['similarity']:.4f} ({result['similarity']*100:.2f}%)")
            
            # 检查是否找到了 A.jpg
            if result['uuid'] == uuid_a:
                print(f"     ✓ 这是 A.jpg！")
    else:
        print("   未找到相似度 >= 0.5 的图片")
    
    print("=" * 60)
    
    # 步骤5: 检查相似度是否存在（使用 check_similarity_exists）
    print("\n8. 使用 check_similarity_exists 检查相似度...")
    threshold = 0.5
    exists, max_similarity, found_uuid = faiss_manager.check_similarity_exists(
        query_vector=vector_b,
        threshold=threshold
    )
    
    if exists:
        print(f"   ✓ 找到相似图片！")
        print(f"   最大相似度: {max_similarity:.4f} ({max_similarity*100:.2f}%)")
        print(f"   UUID: {found_uuid}")
        if found_uuid == uuid_a:
            print(f"   ✓ 确认是 A.jpg")
    else:
        print(f"   ✗ 未找到相似度 >= {threshold} 的图片")
        print(f"   最大相似度: {max_similarity:.4f} ({max_similarity*100:.2f}%)")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
