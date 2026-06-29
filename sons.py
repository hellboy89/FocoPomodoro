"""
Geração e reprodução de alertas sonoros com controle de volume PRÓPRIO.

O Windows (winsound.Beep) não permite ajustar volume. Para ter um controle
de volume independente do Windows, aqui sintetizamos cada alerta como um WAV
de 16 bits, escalando a amplitude pelo volume escolhido (0 a 100), e o
reproduzimos com winsound. Sem dependências externas — só a stdlib.

Importante: tocamos a partir de ARQUIVO (SND_FILENAME | SND_ASYNC), e não da
memória. A combinação SND_MEMORY | SND_ASYNC do winsound é instável e às
vezes não emite som algum; via arquivo é confiável e também não trava a UI.
Cada (som, volume) é gerado uma única vez e fica em cache em disco temporário.
"""

from __future__ import annotations

import math
import os
import re
import struct
import tempfile
import wave

try:
    import winsound
except ImportError:  # fora do Windows segue sem som
    winsound = None

TAXA = 44100  # amostras por segundo

# Pasta temporária onde os WAV gerados ficam guardados.
PASTA_TEMP = os.path.join(tempfile.gettempdir(), "foco_pomodoro_sons")
os.makedirs(PASTA_TEMP, exist_ok=True)

# Cache: (nome, volume) -> caminho do arquivo .wav já gerado.
_cache: dict[tuple, str] = {}


# --------------------------------------------------------------------------- #
# Síntese de áudio
# --------------------------------------------------------------------------- #
def _tom(freq: float, dur: float, volume: int, fade: float = 0.012) -> bytearray:
    """Gera um tom senoidal com pequeno fade-in/out (evita estalos)."""
    n = int(TAXA * dur)
    amp = (max(0, min(100, volume)) / 100.0) * 32767
    nf = max(1, int(TAXA * fade))
    frames = bytearray()
    for i in range(n):
        if i < nf:
            env = i / nf
        elif i > n - nf:
            env = (n - i) / nf
        else:
            env = 1.0
        valor = int(amp * env * math.sin(2 * math.pi * freq * i / TAXA))
        frames += struct.pack("<h", valor)
    return frames


def _silencio(dur: float) -> bytearray:
    return bytearray(int(TAXA * dur) * 2)  # 2 bytes por amostra (mono 16 bits)


# Cada alerta é uma função que recebe o volume e devolve os frames de áudio.
ALERTAS = {
    "Bipe simples": lambda v: _tom(880, 0.25, v),
    "Bipe duplo":   lambda v: _tom(880, 0.12, v) + _silencio(0.07) + _tom(880, 0.12, v),
    "Sino":         lambda v: _tom(659, 0.15, v) + _tom(880, 0.15, v) + _tom(1175, 0.35, v),
    "Alarme":       lambda v: (_tom(1000, 0.14, v) + _silencio(0.09)) * 4,
    "Suave":        lambda v: _tom(440, 0.55, v, fade=0.09),
    "Digital":      lambda v: _tom(1047, 0.08, v) + _tom(1319, 0.08, v) + _tom(1568, 0.18, v),
    "__tique__":    lambda v: _tom(1320, 0.09, v, fade=0.02),
}

# Nomes disponíveis para exibir nas configurações (oculta os internos "__").
NOMES_ALERTAS = [n for n in ALERTAS if not n.startswith("__")]


def _gravar_wav(caminho: str, frames: bytearray) -> None:
    with wave.open(caminho, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(bytes(frames))


def _arquivo_wav(nome: str, volume: int) -> str:
    chave = (nome, volume)
    caminho = _cache.get(chave)
    if caminho and os.path.exists(caminho):
        return caminho
    construtor = ALERTAS.get(nome, ALERTAS["Bipe simples"])
    seguro = re.sub(r"[^a-zA-Z0-9_]", "", nome) or "som"
    caminho = os.path.join(PASTA_TEMP, f"{seguro}_{volume}.wav")
    _gravar_wav(caminho, construtor(volume))
    _cache[chave] = caminho
    return caminho


# --------------------------------------------------------------------------- #
# Reprodução (assíncrona via arquivo, não trava a contagem)
# --------------------------------------------------------------------------- #
def _tocar_arquivo(nome: str, volume: int) -> None:
    if winsound is None or volume <= 0:
        return
    try:
        caminho = _arquivo_wav(nome, volume)
        winsound.PlaySound(caminho, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        pass


def tocar(nome: str, volume: int) -> None:
    """Toca um alerta nomeado no volume informado."""
    _tocar_arquivo(nome, volume)


def tocar_tique(volume: int) -> None:
    """Bipe curto da contagem regressiva (últimos segundos)."""
    _tocar_arquivo("__tique__", volume)
