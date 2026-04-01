#!/usr/bin/env python3
# test_compact.py - 测试compact功能

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from llm.llm_adapter import DeepSeekAdapter
from llm.llm_manager import LLMManager, LLMAdapterFactory

def test_compact_functionality():
    """测试compact功能"""
    print("=== 测试Compact功能 ===")
    
    # 创建LLM适配器
    try:
        # 使用DeepSeek适配器
        adapter = DeepSeekAdapter(
            api_key="test_key",  # 测试用
            base_url="https://api.deepseek.com",
            model="deepseek-chat"
        )
        
        # 创建LLM管理器，设置较低的阈值以便测试
        llm_manager = LLMManager(
            adapter=adapter,
            user_template="你是一个有用的助手。",
            max_tokens=1000,  # 设置较低的max_tokens以便测试
            compact_threshold=0.5  # 设置较低的阈值
        )
        
        print("1. 创建LLM管理器成功")
        
        # 添加一些测试消息
        test_messages = [
            "你好，我是测试用户。",
            "今天天气怎么样？",
            "我想学习Python编程，有什么建议吗？",
            "请告诉我人工智能的发展历史。",
            "如何提高学习效率？",
            "推荐一些好的书籍。",
            "什么是机器学习？",
            "深度学习与机器学习有什么区别？",
            "如何开始学习深度学习？",
            "Python有哪些流行的机器学习库？",
            "TensorFlow和PyTorch哪个更好？",
            "如何安装PyTorch？",
            "什么是神经网络？",
            "卷积神经网络有什么应用？",
            "循环神经网络适合处理什么类型的数据？",
            "什么是强化学习？",
            "如何评估机器学习模型的性能？",
            "什么是过拟合？如何避免？",
            "什么是交叉验证？",
            "特征工程有哪些常用方法？"
        ]
        
        print(f"2. 添加{len(test_messages)}条测试消息")
        
        # 添加消息并检查token数量
        for i, message in enumerate(test_messages):
            response = llm_manager.chat(message, auto_compact=True)
            status = llm_manager.get_compaction_status()
            print(f"  消息{i+1}: {message[:30]}... | Tokens: {status['token_count']} | 使用率: {status['percentage_used']:.1f}%")
            
            if status['needs_compaction']:
                print(f"  ⚠️  达到压缩阈值，触发自动压缩")
        
        print("\n3. 测试手动压缩")
        status = llm_manager.get_compaction_status()
        print(f"   当前状态: {status['token_count']} tokens, {status['percentage_used']:.1f}% 使用率")
        
        # 手动压缩
        success = llm_manager.manual_compact()
        if success:
            new_status = llm_manager.get_compaction_status()
            print(f"   ✅ 手动压缩成功")
            print(f"   压缩后: {new_status['token_count']} tokens, {new_status['percentage_used']:.1f}% 使用率")
        else:
            print(f"   ❌ 手动压缩失败或不需要压缩")
        
        print("\n4. 测试CompactManager独立功能")
        from llm.compact_manager import CompactManager
        
        compact_manager = CompactManager(adapter, max_tokens=1000, compact_threshold=0.5)
        
        # 创建测试消息
        test_messages_list = [
            {"role": "system", "content": "你是一个有用的助手。"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮助你的吗？"},
            {"role": "user", "content": "今天天气怎么样？"},
            {"role": "assistant", "content": "我是一个AI助手，无法获取实时天气信息。建议您查看天气预报应用或网站。"},
        ]
        
        token_count = compact_manager.count_tokens(test_messages_list)
        needs_compact = compact_manager.needs_compaction(test_messages_list)
        
        print(f"   Token计数: {token_count}")
        print(f"   需要压缩: {needs_compact}")
        
        if needs_compact:
            print("   测试压缩功能...")
            try:
                compacted = compact_manager.compact_messages(test_messages_list)
                print(f"   原始消息数: {len(test_messages_list)}")
                print(f"   压缩后消息数: {len(compacted)}")
            except Exception as e:
                print(f"   压缩测试失败: {e}")
        
        print("\n=== 测试完成 ===")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_compact_functionality()