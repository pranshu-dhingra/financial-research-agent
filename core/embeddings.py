"""Embedding utilities for semantic search."""

import json
import math
import boto3
from config import DEBUG, REGION, EMBEDDING_MODEL_ID

try:
    import annoy
    import numpy as np
    HAS_ANNOY = True
except ImportError:
    HAS_ANNOY = False


def get_embedding(text, model_id=None, region=None):
    """
    Get L2-normalized embedding vector from Bedrock.
    
    Args:
        text: Text to embed
        model_id: Bedrock model ID (defaults to config)
        region: AWS region (defaults to config)
    
    Returns:
        List of floats (L2-normalized), or None on error
    """
    if model_id is None:
        model_id = EMBEDDING_MODEL_ID
    if region is None:
        region = REGION
    
    if not text or not text.strip():
        return None
    
    try:
        client = boto3.client("bedrock-runtime", region_name=region)
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": text}),
        )
        raw = response["body"].read().decode("utf-8")
        parsed = json.loads(raw)
        emb = parsed.get("embedding")
        
        if not emb or not isinstance(emb, list):
            return None
        
        if HAS_ANNOY:
            vec = np.array(emb, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec.tolist()
        
        # Fallback: manual L2 normalization
        vec = [float(x) for x in emb]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 0 else vec
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] get_embedding failed: {e}")
        return None
