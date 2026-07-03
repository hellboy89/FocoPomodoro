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
import random
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


# --------------------------------------------------------------------------- #
# Sons ambiente (loops contínuos durante o foco)
# --------------------------------------------------------------------------- #
def _tique_taque(volume: int) -> bytearray:
    """Loop de 2s imitando um relógio: 'tique' agudo e 'taque' mais grave."""
    v = max(0, min(100, volume)) * 0.5  # ambiente mais discreto que os alertas
    quadro = _tom(1800, 0.03, int(v), fade=0.008)
    quadro += _silencio(0.97)
    quadro += _tom(1350, 0.03, int(v * 0.8), fade=0.008)
    quadro += _silencio(0.97)
    return quadro


def _chuva(volume: int) -> bytearray:
    """Ruído suave tipo chuva: ruído branco filtrado por média móvel."""
    dur = 4.0  # loop de 4s disfarça bem a repetição
    n = int(TAXA * dur)
    amp = (max(0, min(100, volume)) / 100.0) * 0.35 * 32767
    rng = random.Random(42)  # semente fixa -> mesmo arquivo a cada geração
    frames = bytearray()
    media = 0.0
    suave = 0.12  # fator do filtro (menor = mais grave/abafado)
    nf = int(TAXA * 0.05)  # fade nas pontas para o loop emendar sem clique
    for i in range(n):
        media += suave * (rng.uniform(-1, 1) - media)
        if i < nf:
            env = i / nf
        elif i > n - nf:
            env = (n - i) / nf
        else:
            env = 1.0
        frames += struct.pack("<h", int(amp * env * media))
    return frames


AMBIENTES = {
    "Tique-taque": _tique_taque,
    "Chuva suave": _chuva,
}
NOMES_AMBIENTES = ["Nenhum"] + list(AMBIENTES)


def _gravar_wav(caminho: str, frames: bytearray) -> None:
    with wave.open(caminho, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(bytes(frames))


def _arquivo_wav(nome: str, volume: int, ambiente: bool = False) -> str:
    chave = (nome, volume, ambiente)
    caminho = _cache.get(chave)
    if caminho and os.path.exists(caminho):
        return caminho
    if ambiente:
        construtor = AMBIENTES.get(nome, _tique_taque)
        prefixo = "amb_"
    else:
        construtor = ALERTAS.get(nome, ALERTAS["Bipe simples"])
        prefixo = ""
    seguro = re.sub(r"[^a-zA-Z0-9_]", "", nome) or "som"
    caminho = os.path.join(PASTA_TEMP, f"{prefixo}{seguro}_{volume}.wav")
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


def tocar_ambiente(nome: str, volume: int) -> None:
    """Inicia um som ambiente em loop contínuo (até parar ou outro som tocar).

    Observação: o winsound só reproduz um som por vez — qualquer alerta
    tocado depois substitui o loop. Quem chama deve reiniciar o ambiente
    se quiser retomá-lo."""
    if winsound is None or volume <= 0 or nome not in AMBIENTES:
        return
    try:
        caminho = _arquivo_wav(nome, volume, ambiente=True)
        winsound.PlaySound(
            caminho,
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
        )
    except Exception:
        pass


def parar_ambiente() -> None:
    """Interrompe qualquer som em reprodução (inclusive o loop ambiente)."""
    if winsound is None:
        return
    try:
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
