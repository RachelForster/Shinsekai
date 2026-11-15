"""Constants for the long-term memory runtime."""

EMBEDDING_MODEL = "Xenova/paraphrase-multilingual-MiniLM-L12-v2"
LEGACY_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIMS = 384
VECTOR_COLLECTION = "character_memories_multilingual_minilm"
MEMORY_STORE_FILENAME = "shinsekai_store.db"
ONNX_MODEL_CANDIDATES = (
    "onnx/model_quantized.onnx",
    "onnx/model_int8.onnx",
    "onnx/model_quint8_avx2.onnx",
    "onnx/model_qint8_avx512_vnni.onnx",
    "onnx/model.onnx",
    "model_quantized.onnx",
    "model_int8.onnx",
    "model.onnx",
)
