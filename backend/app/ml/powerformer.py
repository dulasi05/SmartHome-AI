"""
Module 3: Powerformer-Style Activity Recognition Model
=======================================================

Implements a Powerformer-inspired Transformer with Weighted Causal Multi-Head
Attention (WCMHA) featuring power-law temporal decay.

Mathematical formulation
------------------------
Standard scaled dot-product attention:
    Attention(Q,K,V) = softmax(Q K^T / sqrt(d_k)) V

WCMHA temporal decay modification:
    W_ij = (1 + |t_i - t_j|)^{-alpha}   (power-law weight, alpha > 0)
    Attention_WCMHA(Q,K,V) = softmax((Q K^T / sqrt(d_k)) + log(W + eps)) V

Where:
  - t_i, t_j are relative timestamps of events i, j in the window
  - alpha (decay exponent) controls how fast attention decays with time distance
  - W is the [seq_len x seq_len] decay matrix
  - Causal masking is applied so position i cannot attend to future positions j > i

⚠️  IMPLEMENTATION NOTICE:
This is a Powerformer-STYLE implementation based on the publicly described
power-law temporal decay concept. It has NOT been verified against the original
Powerformer paper source code. Differences from any specific published architecture
are expected. The WCMHA attention component is isolated in PowerDecayAttention
so it can be replaced with a verified implementation when available.

Architecture:
    Input: [batch, seq_len, n_sensors]  (one-hot encoded sensor events)
    → SensorEmbedding                   → [batch, seq_len, d_model]
    → TemporalPositionalEncoding        (learnable)
    → N × PowerformerBlock              (WCMHA + FFN)
    → ResidentHead(s)                   → [batch, n_activities] per resident
"""

import math
import logging
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


# ─── Temporal Decay Attention ─────────────────────────────────────────────────

class PowerDecayAttention(nn.Module):
    """
    Weighted Causal Multi-Head Attention with power-law temporal decay (WCMHA).

    Given a sequence of events with relative timestamps delta_t[i,j] = |t_i - t_j|,
    the decay weight is:
        w[i,j] = (1 + delta_t[i,j] / scale)^{-alpha}

    The log of these weights is added to the raw attention logits before softmax,
    biasing the model to attend more to temporally close events. Causal masking
    fills the future upper-triangle with -inf.
    """

    def __init__(
        self,
        d_model: int,
        n_heads: int,
        alpha: float = 1.0,
        time_scale: float = 60.0,
        dropout: float = 0.1,
    ):
        super().__init__()
        assert d_model % n_heads == 0, "d_model must be divisible by n_heads"
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_k = d_model // n_heads
        self.alpha = alpha
        self.time_scale = time_scale  # normalise time deltas (seconds)

        self.W_q = nn.Linear(d_model, d_model, bias=False)
        self.W_k = nn.Linear(d_model, d_model, bias=False)
        self.W_v = nn.Linear(d_model, d_model, bias=False)
        self.W_o = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)

    def _build_decay_matrix(self, seq_len: int, timestamps: Optional[torch.Tensor]) -> torch.Tensor:
        """
        Build [seq_len, seq_len] temporal decay matrix.
        timestamps: [batch, seq_len] relative seconds (0 = first event)
        Returns: [seq_len, seq_len] log-decay bias (to be broadcast over heads/batch)
        """
        if timestamps is not None:
            # Use actual timestamps; take mean over batch for the bias
            t = timestamps.float().mean(0)  # [seq_len]
            delta = (t.unsqueeze(1) - t.unsqueeze(0)).abs()  # [seq_len, seq_len]
        else:
            # Fall back to positional distance
            idx = torch.arange(seq_len, dtype=torch.float32)
            delta = (idx.unsqueeze(1) - idx.unsqueeze(0)).abs()

        # Power-law decay weight: w = (1 + delta/scale)^{-alpha}
        decay_weight = (1.0 + delta / self.time_scale).pow(-self.alpha)
        # Convert to log-bias (added to attention logits)
        log_decay = torch.log(decay_weight.clamp(min=1e-9))
        return log_decay  # [seq_len, seq_len]

    def forward(
        self,
        x: torch.Tensor,
        timestamps: Optional[torch.Tensor] = None,
        key_padding_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        Args:
            x            : [batch, seq_len, d_model]
            timestamps   : [batch, seq_len] relative time in seconds (optional)
            key_padding_mask: [batch, seq_len] bool, True = ignore
        Returns:
            out          : [batch, seq_len, d_model]
        """
        B, L, _ = x.shape
        H, dk = self.n_heads, self.d_k

        Q = self.W_q(x).view(B, L, H, dk).transpose(1, 2)  # [B, H, L, dk]
        K = self.W_k(x).view(B, L, H, dk).transpose(1, 2)
        V = self.W_v(x).view(B, L, H, dk).transpose(1, 2)

        # Scaled dot-product scores
        scores = torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(dk)  # [B, H, L, L]

        # Add temporal decay bias (broadcast over batch and heads)
        decay_bias = self._build_decay_matrix(L, timestamps).to(x.device)  # [L, L]
        scores = scores + decay_bias.unsqueeze(0).unsqueeze(0)

        # Causal mask: future positions get -inf
        causal_mask = torch.triu(torch.ones(L, L, device=x.device), diagonal=1).bool()
        scores = scores.masked_fill(causal_mask.unsqueeze(0).unsqueeze(0), float("-inf"))

        # Optional key-padding mask
        if key_padding_mask is not None:
            # key_padding_mask: [B, L], expand for heads and query positions
            km = key_padding_mask.unsqueeze(1).unsqueeze(2)  # [B,1,1,L]
            scores = scores.masked_fill(km, float("-inf"))

        attn = self.dropout(F.softmax(scores, dim=-1))
        out = torch.matmul(attn, V)  # [B, H, L, dk]
        out = out.transpose(1, 2).contiguous().view(B, L, self.d_model)
        return self.W_o(out)


# ─── Powerformer Block ────────────────────────────────────────────────────────

class PowerformerBlock(nn.Module):
    """Single Powerformer encoder block: WCMHA → Add&Norm → FFN → Add&Norm."""

    def __init__(
        self,
        d_model: int,
        n_heads: int,
        d_ff: int,
        alpha: float = 1.0,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.attn = PowerDecayAttention(d_model, n_heads, alpha=alpha, dropout=dropout)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_ff, d_model),
            nn.Dropout(dropout),
        )

    def forward(self, x, timestamps=None, key_padding_mask=None):
        # Pre-norm variant (more stable training)
        x = x + self.attn(self.norm1(x), timestamps=timestamps, key_padding_mask=key_padding_mask)
        x = x + self.ffn(self.norm2(x))
        return x


# ─── Temporal Positional Encoding ─────────────────────────────────────────────

class LearnableTemporalEncoding(nn.Module):
    """Learnable positional embedding (not sinusoidal) for sensor event sequences."""

    def __init__(self, d_model: int, max_len: int = 512, dropout: float = 0.1):
        super().__init__()
        self.embedding = nn.Embedding(max_len, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, L, _ = x.shape
        pos = torch.arange(L, device=x.device).unsqueeze(0).expand(B, -1)
        return self.dropout(x + self.embedding(pos))


# ─── Main Powerformer Model ───────────────────────────────────────────────────

class PowerformerActivityRecognizer(nn.Module):
    """
    Powerformer-style multi-resident activity recognition model.

    Supports:
    - Single resident (one classification head)
    - Multi-resident (separate heads per resident)
    - Arbitrary n_activities classes

    Input encoding:
        Each event in the window is encoded as a concatenation of:
          - one-hot sensor_id     [n_sensors]
          - one-hot sensor_state  [n_states]
          - time-of-day sin/cos   [2]
          - day-of-week sin/cos   [2]
    Total input dim = n_sensors + n_states + 4
    """

    def __init__(
        self,
        n_sensors: int,
        n_states: int = 4,
        n_activities: int = 14,
        n_residents: int = 1,
        d_model: int = 128,
        n_heads: int = 4,
        n_layers: int = 3,
        d_ff: int = 256,
        alpha: float = 1.0,
        dropout: float = 0.1,
        max_seq_len: int = 128,
    ):
        super().__init__()
        self.n_sensors = n_sensors
        self.n_states = n_states
        self.n_activities = n_activities
        self.n_residents = n_residents
        self.d_model = d_model

        input_dim = n_sensors + n_states + 4  # +4 for time features

        # Input projection
        self.input_proj = nn.Sequential(
            nn.Linear(input_dim, d_model),
            nn.LayerNorm(d_model),
            nn.GELU(),
        )

        # Positional encoding
        self.pos_enc = LearnableTemporalEncoding(d_model, max_len=max_seq_len, dropout=dropout)

        # Transformer blocks
        self.blocks = nn.ModuleList([
            PowerformerBlock(d_model, n_heads, d_ff, alpha=alpha, dropout=dropout)
            for _ in range(n_layers)
        ])

        self.norm = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(dropout)

        # Classification heads (one per resident)
        self.heads = nn.ModuleList([
            nn.Sequential(
                nn.Linear(d_model, d_model // 2),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(d_model // 2, n_activities),
            )
            for _ in range(n_residents)
        ])

    def forward(
        self,
        x: torch.Tensor,
        timestamps: Optional[torch.Tensor] = None,
        key_padding_mask: Optional[torch.Tensor] = None,
    ):
        """
        Args:
            x              : [batch, seq_len, input_dim]  (encoded sensor events)
            timestamps     : [batch, seq_len] relative timestamps in seconds
            key_padding_mask: [batch, seq_len] True = padding position
        Returns:
            list of [batch, n_activities] logits, one per resident head
        """
        h = self.input_proj(x)
        h = self.pos_enc(h)

        for block in self.blocks:
            h = block(h, timestamps=timestamps, key_padding_mask=key_padding_mask)

        h = self.norm(h)

        # Aggregate sequence: mean pool (ignoring padding)
        if key_padding_mask is not None:
            mask = (~key_padding_mask).float().unsqueeze(-1)  # [B, L, 1]
            h = (h * mask).sum(1) / mask.sum(1).clamp(min=1)
        else:
            h = h.mean(1)  # [batch, d_model]

        h = self.dropout(h)

        logits_per_resident = [head(h) for head in self.heads]
        return logits_per_resident  # list of [batch, n_activities]

    def predict_proba(
        self,
        x: torch.Tensor,
        timestamps: Optional[torch.Tensor] = None,
        key_padding_mask: Optional[torch.Tensor] = None,
    ) -> list[torch.Tensor]:
        """Return softmax probabilities for each resident head."""
        with torch.no_grad():
            logits_list = self.forward(x, timestamps, key_padding_mask)
            return [F.softmax(logits, dim=-1) for logits in logits_list]


# ─── Encoding utilities ────────────────────────────────────────────────────────

class WindowEncoder:
    """
    Converts a list of sensor event dicts (a sliding window) into model input tensors.

    Each event dict has keys: sensor_id, sensor_state, timestamp (ISO string or datetime)

    Output tensor shape: [1, seq_len, input_dim]
    where input_dim = n_sensors + n_states + 4 (time features)
    """

    STATE_VOCAB = ["ON", "OFF", "OPEN", "CLOSED"]

    def __init__(self, sensor_vocab: list[str]):
        self.sensor_vocab = sensor_vocab
        self.sensor_to_idx = {s: i for i, s in enumerate(sensor_vocab)}
        self.state_to_idx = {s: i for i, s in enumerate(self.STATE_VOCAB)}
        self.n_sensors = len(sensor_vocab)
        self.n_states = len(self.STATE_VOCAB)
        self.input_dim = self.n_sensors + self.n_states + 4

    def encode_window(
        self, window: list[dict]
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Returns:
            features   : [1, seq_len, input_dim] float tensor
            timestamps : [1, seq_len] relative seconds float tensor
        """
        from datetime import datetime

        rows = []
        ts_vals = []

        base_ts = None
        for event in window:
            ts = event.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except ValueError:
                    ts = None
            if ts is not None and base_ts is None:
                base_ts = ts
            rel_sec = (ts - base_ts).total_seconds() if (ts and base_ts) else 0.0
            ts_vals.append(rel_sec)

            # Sensor one-hot
            sensor_vec = [0.0] * self.n_sensors
            sid = str(event.get("sensor_id", "")).upper()
            if sid in self.sensor_to_idx:
                sensor_vec[self.sensor_to_idx[sid]] = 1.0

            # State one-hot
            state_vec = [0.0] * self.n_states
            st = str(event.get("sensor_state", "")).upper()
            if st in self.state_to_idx:
                state_vec[self.state_to_idx[st]] = 1.0

            # Time-of-day features
            hour = ts.hour if ts else 0
            dow = ts.weekday() if ts else 0
            tod_sin = math.sin(2 * math.pi * hour / 24)
            tod_cos = math.cos(2 * math.pi * hour / 24)
            dow_sin = math.sin(2 * math.pi * dow / 7)
            dow_cos = math.cos(2 * math.pi * dow / 7)

            row = sensor_vec + state_vec + [tod_sin, tod_cos, dow_sin, dow_cos]
            rows.append(row)

        if not rows:
            rows = [[0.0] * self.input_dim]
            ts_vals = [0.0]

        features = torch.tensor([rows], dtype=torch.float32)
        timestamps = torch.tensor([ts_vals], dtype=torch.float32)
        return features, timestamps


# ─── Training utilities ────────────────────────────────────────────────────────

class PowerformerTrainer:
    """
    Training and evaluation wrapper for PowerformerActivityRecognizer.

    Supports:
    - Multi-resident multi-class classification
    - Chronological train/val split (no data leakage)
    - Checkpoint save/load
    - Reproducible random seed
    """

    def __init__(
        self,
        model: PowerformerActivityRecognizer,
        device: str = "cpu",
        lr: float = 1e-3,
        weight_decay: float = 1e-4,
        seed: int = 42,
    ):
        self.model = model.to(device)
        self.device = device
        self.seed = seed
        torch.manual_seed(seed)
        np.random.seed(seed)

        self.optimizer = torch.optim.AdamW(
            model.parameters(), lr=lr, weight_decay=weight_decay
        )
        self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, T_max=50
        )
        self.criterion = nn.CrossEntropyLoss(ignore_index=-1)
        self.history: dict[str, list] = {"train_loss": [], "val_loss": [], "val_acc": []}

    def train_epoch(
        self,
        dataloader,
        resident_idx: int = 0,
    ) -> float:
        """Run one training epoch, return mean loss."""
        self.model.train()
        total_loss = 0.0
        n_batches = 0

        for batch in dataloader:
            x = batch["features"].to(self.device)
            ts = batch.get("timestamps")
            if ts is not None:
                ts = ts.to(self.device)
            labels = batch["labels"][:, resident_idx].to(self.device)

            self.optimizer.zero_grad()
            logits_list = self.model(x, timestamps=ts)
            loss = self.criterion(logits_list[resident_idx], labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        self.scheduler.step()
        avg_loss = total_loss / max(n_batches, 1)
        self.history["train_loss"].append(avg_loss)
        return avg_loss

    @torch.no_grad()
    def evaluate(
        self,
        dataloader,
        resident_idx: int = 0,
    ) -> dict:
        """Evaluate on a dataloader, return loss and accuracy."""
        self.model.eval()
        total_loss = 0.0
        correct = 0
        total = 0

        for batch in dataloader:
            x = batch["features"].to(self.device)
            ts = batch.get("timestamps")
            if ts is not None:
                ts = ts.to(self.device)
            labels = batch["labels"][:, resident_idx].to(self.device)

            logits_list = self.model(x, timestamps=ts)
            loss = self.criterion(logits_list[resident_idx], labels)
            total_loss += loss.item()

            preds = logits_list[resident_idx].argmax(dim=-1)
            mask = labels != -1
            correct += (preds[mask] == labels[mask]).sum().item()
            total += mask.sum().item()

        avg_loss = total_loss / max(len(dataloader), 1)
        acc = correct / max(total, 1)
        self.history["val_loss"].append(avg_loss)
        self.history["val_acc"].append(acc)
        return {"val_loss": avg_loss, "val_acc": acc}

    def save_checkpoint(self, path: str, epoch: int, val_acc: float):
        """Save model checkpoint with metadata."""
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(
            {
                "epoch": epoch,
                "model_state_dict": self.model.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "val_acc": val_acc,
                "history": self.history,
                "config": {
                    "n_sensors": self.model.n_sensors,
                    "n_activities": self.model.n_activities,
                    "n_residents": self.model.n_residents,
                    "d_model": self.model.d_model,
                },
            },
            path,
        )
        logger.info(f"Checkpoint saved to {path} (epoch={epoch}, val_acc={val_acc:.4f})")

    @classmethod
    def load_checkpoint(
        cls,
        path: str,
        model: PowerformerActivityRecognizer,
        device: str = "cpu",
    ) -> "PowerformerTrainer":
        """Load model from checkpoint file."""
        ckpt = torch.load(path, map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])
        trainer = cls(model, device=device)
        trainer.optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        trainer.history = ckpt.get("history", trainer.history)
        epoch = ckpt.get("epoch", 0)
        logger.info(f"Loaded checkpoint from {path} (epoch={epoch})")
        return trainer


# ─── Dataset class ────────────────────────────────────────────────────────────

class WindowDataset(torch.utils.data.Dataset):
    """
    PyTorch Dataset wrapping preprocessed sliding-window records.

    Expected window format (from preprocessor):
    {
        "features": [seq_len, input_dim],
        "timestamps": [seq_len],   # relative seconds
        "labels": [n_residents],   # integer class indices, -1 = unknown
    }
    """

    def __init__(self, windows: list[dict]):
        self.windows = windows

    def __len__(self):
        return len(self.windows)

    def __getitem__(self, idx):
        w = self.windows[idx]
        return {
            "features": torch.tensor(w["features"], dtype=torch.float32),
            "timestamps": torch.tensor(w["timestamps"], dtype=torch.float32),
            "labels": torch.tensor(w["labels"], dtype=torch.long),
        }
