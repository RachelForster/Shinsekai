# compact_manager.py
import json
import tiktoken
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class CompactManager:
    """管理记忆压缩的类"""
    
    def __init__(self, llm_adapter, max_tokens: int = 128000, compact_threshold: float = 0.9):
        """
        初始化CompactManager
        
        Args:
            llm_adapter: LLM适配器实例
            max_tokens: 模型最大token数
            compact_threshold: 触发压缩的阈值（0.9表示达到90%时触发）
        """
        self.llm_adapter = llm_adapter
        self.max_tokens = max_tokens
        self.compact_threshold = compact_threshold
        self.num_tokens = 0
        
        # 尝试使用tiktoken进行token计数
        try:
            # 对于DeepSeek，使用cl100k_base编码
            self.encoder = tiktoken.get_encoding("cl100k_base")
        except:
            self.encoder = None
            logger.warning("tiktoken not available, using approximate token counting")
    

    def set_token_count(self, token_count: int):
        """直接设置当前token计数"""
        self.num_tokens = token_count

    def count_tokens(self, messages: List[Dict[str, str]]) -> int:
        """计算消息列表的token数量"""
        if self.encoder:
            # 使用tiktoken精确计算
            total_tokens = 0
            # logger.debug(f"Counting tokens for {len(messages)} messages using tiktoken")
            for message in messages:
                content = message.get('content', '')
                role = message.get('role', '')
                # 每个消息都有一些额外的token开销
                # logger.debug(f"Counting tokens for message: role={role}, content: {content}")
                total_tokens += len(self.encoder.encode(content)) + 4  # 4个token用于角色和格式
            return total_tokens
        else:
            # 近似计算：1个token ≈ 4个字符（英文）或 1.3个字符（中文）
            total_chars = 0
            for message in messages:
                content = message.get('content', '')
                total_chars += len(content)
            # 保守估计：假设大部分是中文，1个token ≈ 1.5个字符
            return int(total_chars / 1.5)
    
    def increase_token_count(self, new_messages: List[Dict[str, str]], token_usage: int = 0):
        """增加当前token计数"""
        if token_usage > 0:
            self.num_tokens = token_usage
        else:
            self.num_tokens += self.count_tokens(new_messages)
        return self.num_tokens

    def needs_compaction(self, messages: List[Dict[str, str]], token_usage: int = 0) -> bool:
        """检查是否需要压缩记忆"""
        if self.num_tokens == 0:  # 如果是第一次计算token数量
            self.num_tokens = self.count_tokens(messages)
            logger.info(f"Initial token count: {self.num_tokens} tokens for {len(messages)} messages")
        else:
            self.increase_token_count(messages[-1:], token_usage)  # 只计算最近一条消息的token数
            # logger.info(f"Increase token count messages:{messages}")
        token_count = self.num_tokens
        threshold_tokens = self.max_tokens * self.compact_threshold

        return token_count > threshold_tokens
    
    def compact_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        压缩消息历史
        
        Args:
            messages: 原始消息列表
            
        Returns:
            压缩后的消息列表
        """
        if len(messages) <= 2:  # 只有system消息和少量对话，不需要压缩
            return messages
        
        # logger.info(f"Starting compaction of {len(messages)} messages")
        
        # 保留system消息
        system_message = messages[0] if messages[0]['role'] == 'system' else None
        
        # 获取需要压缩的消息（排除system消息）
        messages_to_compact = messages[1:] if system_message else messages
        
        if len(messages_to_compact) <= 1:
            return messages
        
        # 准备压缩提示
        compact_prompt = self._create_compact_prompt(messages_to_compact)
        
        try:
            # 使用LLM进行压缩
            compacted_content = self._call_llm_for_compaction(compact_prompt)
            
            # 构建压缩后的消息列表
            compacted_messages = []
            if system_message:
                compacted_messages.append(system_message)
            
            # 添加压缩后的总结消息
            compacted_messages.append({
                'role': 'user',
                'content': f"【历史对话总结】以下是之前对话的压缩总结：\n{compacted_content}\n\n请基于这个上下文继续对话。"
            })
            
            # 保留最后几条消息以保持对话连续性
            recent_messages = messages_to_compact[-3:]  # 保留最后3条消息
            compacted_messages.extend(recent_messages)
            
            # logger.info(f"Compaction completed. Original: {len(messages)} messages, Compacted: {len(compacted_messages)} messages")
            self.num_tokens = 0
            return compacted_messages
            
        except Exception as e:
            logger.error(f"Compaction failed: {e}")
            # 如果压缩失败，返回原始消息
            return messages
    
    def _create_compact_prompt(self, messages: List[Dict[str, str]]) -> str:
        """创建压缩提示"""
        prompt = """请将以下对话历史压缩成一个简洁的总结。总结应该：
1. 保留关键信息、重要决定和主要话题
2. 忽略无关紧要的细节和重复内容
3. 保持时间顺序和逻辑连贯性
4. 用中文总结，保持客观准确

对话历史：
"""
        
        for i, message in enumerate(messages):
            role = "用户" if message['role'] == 'user' else "助手"
            content = message['content']
            prompt += f"\n{role}: {content}"
        
        prompt += "\n\n请提供对话总结："
        
        return prompt
    
    def _call_llm_for_compaction(self, prompt: str) -> str:
        """调用LLM进行压缩"""
        # 创建压缩专用的消息列表
        compact_messages = [
            {'role': 'system', 'content': '你是一个专业的对话总结助手，擅长将长对话压缩成简洁准确的总结。请保留用户的重要信息和目前的对话话题。'},
            {'role': 'user', 'content': prompt}
        ]
        
        # 调用LLM
        response = self.llm_adapter.chat(compact_messages, stream=False, response_format={'type': 'text'})
        
        if response:
            try:
                if hasattr(response, 'choices') and hasattr(response.choices[0], 'message'):
                    return response.choices[0].message.content
                elif hasattr(response, 'text'):
                    return response.text
                elif hasattr(response, 'content'):
                    return response.content[0].text
                else:
                    return str(response)
            except Exception as e:
                logger.error(f"Failed to extract response content: {e}")
                return "压缩失败，请参考原始对话历史。"
        
        return "压缩失败，请参考原始对话历史。"
    
    def auto_compact_if_needed(self, messages: List[Dict[str, str]], token_usage: int = 0) -> List[Dict[str, str]]:
        """自动检查并压缩消息（如果需要）"""
        # logger.info("num tokens before compaction check: {}".format(self.num_tokens))
        if self.needs_compaction(messages, token_usage):
            logger.info("Token limit approaching, performing automatic compaction...")
            return self.compact_messages(messages)
        return messages