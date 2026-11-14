"""ONNX Runtime CPU embedding adapter for multilingual MiniLM-L12-v2 (384-dim)."""

from __future__ import annotations

import json
import os
import threading
import unicodedata
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ai.memory.constants import EMBEDDING_DIMS, ONNX_MODEL_CANDIDATES
from sdk.adapters.memory import ReadinessStatus

_SP_SPACE = "\u2581"


def find_onnx_model_file(snapshot_dir: str | Path) -> Path | None:
    """Locate the preferred quantized or standard ONNX graph inside a snapshot."""
    root = Path(snapshot_dir)
    if not root.is_dir():
        return None
    for rel in ONNX_MODEL_CANDIDATES:
        candidate = root / rel
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            continue
    return None


class _PureUnigramTokenizer:
    """Zero-dependency SentencePiece Unigram Viterbi tokenizer reading tokenizer.json.

    Used automatically when the optional ``tokenizers`` Rust wheel is not installed
    in ``desktop-core``, ensuring 100% out-of-the-box execution with only ``numpy``
    and ``onnxruntime``.
    """

    def __init__(self, tokenizer_json_path: Path, *, max_length: int = 256) -> None:
        payload = json.loads(tokenizer_json_path.read_text(encoding="utf-8"))
        model = payload.get("model") or {}
        raw_vocab = model.get("vocab") or []
        self._max_length = max(8, int(max_length))
        self._unk_id = int(model.get("unk_id", 3))

        self._piece_to_id: dict[str, int] = {}
        self._piece_score: dict[str, float] = {}
        max_piece_len = 1
        for idx, entry in enumerate(raw_vocab):
            if isinstance(entry, list) and len(entry) >= 2:
                piece = str(entry[0])
                score = float(entry[1])
            elif isinstance(entry, str):
                piece = entry
                score = -10.0
            else:
                continue
            self._piece_to_id[piece] = idx
            self._piece_score[piece] = score
            if len(piece) > max_piece_len:
                max_piece_len = len(piece)
        self._max_piece_len = max_piece_len

        # Detect XLM-RoBERTa vs BERT special tokens from vocab / added_tokens
        for added in payload.get("added_tokens") or []:
            if isinstance(added, dict) and "content" in added and "id" in added:
                self._piece_to_id.setdefault(str(added["content"]), int(added["id"]))

        if "<s>" in self._piece_to_id and "</s>" in self._piece_to_id:
            self._bos_id = self._piece_to_id["<s>"]
            self._eos_id = self._piece_to_id["</s>"]
            self._pad_id = self._piece_to_id.get("<pad>", 1)
        else:
            self._bos_id = self._piece_to_id.get("[CLS]", 101)
            self._eos_id = self._piece_to_id.get("[SEP]", 102)
            self._pad_id = self._piece_to_id.get("[PAD]", 0)

    @property
    def pad_id(self) -> int:
        return self._pad_id

    def _encode_word(self, piece_text: str) -> list[int]:
        n = len(piece_text)
        if n == 0:
            return []
        best_score = [-1e18] * (n + 1)
        best_prev = [-1] * (n + 1)
        best_id = [self._unk_id] * (n + 1)
        best_score[0] = 0.0

        max_l = self._max_piece_len
        p_to_id = self._piece_to_id
        p_score = self._piece_score

        for i in range(n):
            base = best_score[i]
            if base <= -1e17:
                continue
            end_limit = min(n, i + max_l)
            matched_any = False
            for j in range(i + 1, end_limit + 1):
                sub = piece_text[i:j]
                tok_id = p_to_id.get(sub)
                if tok_id is not None:
                    matched_any = True
                    cand = base + p_score.get(sub, -10.0)
                    if cand > best_score[j]:
                        best_score[j] = cand
                        best_prev[j] = i
                        best_id[j] = tok_id
            if not matched_any:
                cand = base - 20.0
                if cand > best_score[i + 1]:
                    best_score[i + 1] = cand
                    best_prev[i + 1] = i
                    best_id[i + 1] = self._unk_id

        ids: list[int] = []
        pos = n
        while pos > 0:
            ids.append(best_id[pos])
            prev = best_prev[pos]
            pos = prev if prev >= 0 else pos - 1
        ids.reverse()
        return ids

    def encode_batch(self, texts: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
        encoded_rows: list[list[int]] = []
        inner_limit = max(1, self._max_length - 2)
        for raw in texts:
            norm = unicodedata.normalize("NFKC", str(raw or "")).strip()
            if not norm:
                ids = [self._bos_id, self._eos_id]
            else:
                collapsed = " ".join(norm.split())
                sp_text = _SP_SPACE + collapsed.replace(" ", _SP_SPACE)
                piece_ids = self._encode_word(sp_text)[:inner_limit]
                ids = [self._bos_id, *piece_ids, self._eos_id]
            encoded_rows.append(ids)

        max_len = max(len(r) for r in encoded_rows)
        batch_size = len(encoded_rows)
        input_ids = np.full((batch_size, max_len), self._pad_id, dtype=np.int64)
        attention_mask = np.zeros((batch_size, max_len), dtype=np.int64)
        for row_idx, row in enumerate(encoded_rows):
            length = len(row)
            input_ids[row_idx, :length] = row
            attention_mask[row_idx, :length] = 1
        return input_ids, attention_mask


class _FastRustTokenizerWrapper:
    """Thin wrapper over HuggingFace ``tokenizers.Tokenizer``."""

    def __init__(self, tokenizer_json_path: Path, *, max_length: int = 256) -> None:
        from tokenizers import Tokenizer

        tok = Tokenizer.from_file(str(tokenizer_json_path))
        pad_id = tok.token_to_id("<pad>")
        if pad_id is None:
            pad_id = tok.token_to_id("[PAD]") or 0
        tok.enable_truncation(max_length=max(8, int(max_length)))
        tok.enable_padding(pad_id=int(pad_id))
        self._tok = tok

    def encode_batch(self, texts: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
        normalized = [str(t or "") for t in texts]
        batch = self._tok.encode_batch(normalized)
        input_ids = np.asarray([enc.ids for enc in batch], dtype=np.int64)
        attention_mask = np.asarray([enc.attention_mask for enc in batch], dtype=np.int64)
        return input_ids, attention_mask


def _load_tokenizer(snapshot_dir: Path, *, max_length: int = 256) -> Any:
    tokenizer_json = snapshot_dir / "tokenizer.json"
    if not tokenizer_json.is_file():
        raise FileNotFoundError(f"tokenizer.json not found in {snapshot_dir}")
    try:
        return _FastRustTokenizerWrapper(tokenizer_json, max_length=max_length)
    except ImportError:
        return _PureUnigramTokenizer(tokenizer_json, max_length=max_length)


class OnnxMiniLmEmbedder:
    """CPU INT8 ONNX Runtime embedder with Mean Pooling, L2 norm, and LRU cache."""

    def __init__(
        self,
        snapshot_dir: str | Path,
        *,
        dimensions: int = EMBEDDING_DIMS,
        max_length: int = 256,
        query_cache_size: int = 512,
        session: Any | None = None,
        tokenizer: Any | None = None,
    ) -> None:
        self._snapshot_dir = Path(snapshot_dir)
        self._dimensions = int(dimensions)
        self._max_length = int(max_length)
        self._cache_size = max(0, int(query_cache_size))
        self._cache_lock = threading.Lock()
        self._query_cache: OrderedDict[str, np.ndarray] = OrderedDict()

        self._tokenizer = tokenizer or _load_tokenizer(self._snapshot_dir, max_length=max_length)
        if session is not None:
            self._session = session
        else:
            import onnxruntime as ort

            onnx_path = find_onnx_model_file(self._snapshot_dir)
            if onnx_path is None:
                raise FileNotFoundError(
                    f"No ONNX model file found under {self._snapshot_dir}"
                )
            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            cpu_threads = max(1, min(4, os.cpu_count() or 2))
            opts.intra_op_num_threads = cpu_threads
            opts.inter_op_num_threads = 1
            self._session = ort.InferenceSession(
                str(onnx_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )

        self._input_names = tuple(inp.name for inp in self._session.get_inputs())

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def snapshot_dir(self) -> Path:
        return self._snapshot_dir

    def _forward(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimensions), dtype=np.float32)
        input_ids, attention_mask = self._tokenizer.encode_batch(texts)
        feeds: dict[str, np.ndarray] = {}
        for name in self._input_names:
            if name == "input_ids":
                feeds[name] = input_ids
            elif name == "attention_mask":
                feeds[name] = attention_mask
            elif name == "token_type_ids":
                feeds[name] = np.zeros_like(input_ids, dtype=np.int64)

        outputs = self._session.run(None, feeds)
        primary = np.asarray(outputs[0], dtype=np.float32)

        if primary.ndim == 3:
            # Mean pooling weighted by attention_mask: (B, L, D) -> (B, D)
            mask = attention_mask[:, :, np.newaxis].astype(np.float32)
            summed = np.sum(primary * mask, axis=1)
            counts = np.clip(np.sum(mask, axis=1), a_min=1e-9, a_max=None)
            pooled = summed / counts
        elif primary.ndim == 2:
            pooled = primary
        else:
            raise RuntimeError(f"Unexpected ONNX embedding output shape: {primary.shape}")

        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-12, a_max=None)
        normalized = (pooled / norms).astype(np.float32)
        return np.ascontiguousarray(normalized, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        key = " ".join(str(text or "").strip().split())
        if self._cache_size > 0:
            with self._cache_lock:
                cached = self._query_cache.get(key)
                if cached is not None:
                    self._query_cache.move_to_end(key)
                    return cached.copy()

        vec = self._forward([key])[0]
        if self._cache_size > 0:
            with self._cache_lock:
                self._query_cache[key] = vec
                self._query_cache.move_to_end(key)
                while len(self._query_cache) > self._cache_size:
                    self._query_cache.popitem(last=False)
        return vec.copy()

    def embed_documents(self, texts: Sequence[str], *, batch_size: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimensions), dtype=np.float32)
        step = max(1, int(batch_size))
        chunks: list[np.ndarray] = []
        for start in range(0, len(texts), step):
            chunks.append(self._forward(texts[start : start + step]))
        return np.vstack(chunks) if len(chunks) > 1 else chunks[0]

    def status(self) -> ReadinessStatus:
        return ReadinessStatus(state="ready", model_cached=True, message="ONNX MiniLM ready")
