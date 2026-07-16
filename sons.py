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

Dispositivo de saída fixo
-------------------------
O winsound sempre toca no dispositivo PADRÃO do Windows — não dá para escolher
por onde o som sai. Para permitir fixar a saída num dispositivo específico
(mesmo que o usuário troque o padrão do Windows para conversar no fone, por
exemplo), há um segundo backend opcional baseado no `sounddevice` (PortAudio /
WASAPI), que toca os mesmos frames diretamente no endpoint escolhido.

O `sounddevice` é opcional e instalado sob demanda (como a bandeja faz com o
pystray). Enquanto nenhum dispositivo for fixado, tudo continua pelo winsound e
o app segue funcionando apenas com a biblioteca padrão.
"""

from __future__ import annotations

import math
import os
import random
import re
import struct
import subprocess
import sys
import tempfile
import threading
import wave

try:
    import winsound
except ImportError:  # fora do Windows segue sem som
    winsound = None

TAXA = 44100  # amostras por segundo

# Evita piscar uma janela de console ao instalar o sounddevice via pip (pythonw).
_CREATE_NO_WINDOW = 0x08000000

# Pasta temporária onde os WAV gerados ficam guardados.
PASTA_TEMP = os.path.join(tempfile.gettempdir(), "foco_pomodoro_sons")
os.makedirs(PASTA_TEMP, exist_ok=True)

# Cache: (nome, volume, ambiente) -> caminho do arquivo .wav já gerado.
_cache: dict[tuple, str] = {}
# Cache: (nome, volume, ambiente) -> frames de áudio (int16 mono) em memória,
# usados pelo backend de dispositivo fixo (sounddevice).
_frames_cache: dict[tuple, bytes] = {}


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


def _frames(nome: str, volume: int, ambiente: bool = False) -> bytes:
    """Frames de áudio (int16 mono, TAXA Hz) do som pedido, gerados uma vez."""
    chave = (nome, volume, ambiente)
    dados = _frames_cache.get(chave)
    if dados is not None:
        return dados
    if ambiente:
        construtor = AMBIENTES.get(nome, _tique_taque)
    else:
        construtor = ALERTAS.get(nome, ALERTAS["Bipe simples"])
    dados = bytes(construtor(volume))
    _frames_cache[chave] = dados
    return dados


def _arquivo_wav(nome: str, volume: int, ambiente: bool = False) -> str:
    chave = (nome, volume, ambiente)
    caminho = _cache.get(chave)
    if caminho and os.path.exists(caminho):
        return caminho
    prefixo = "amb_" if ambiente else ""
    seguro = re.sub(r"[^a-zA-Z0-9_]", "", nome) or "som"
    caminho = os.path.join(PASTA_TEMP, f"{prefixo}{seguro}_{volume}.wav")
    _gravar_wav(caminho, _frames(nome, volume, ambiente))
    _cache[chave] = caminho
    return caminho


# --------------------------------------------------------------------------- #
# Backend de dispositivo fixo (sounddevice / PortAudio-WASAPI)
#
# Só entra em ação quando o usuário escolhe um dispositivo de saída específico
# nas Configurações. Aí os frames são tocados diretamente naquele endpoint,
# ignorando o dispositivo padrão do Windows. Sem dispositivo escolhido, tudo
# continua pelo winsound (padrão do Windows), sem depender do sounddevice.
# --------------------------------------------------------------------------- #
_sd = None                 # módulo sounddevice, quando disponível
_sd_indisponivel = False   # True se importar/instalar falhou de vez (não insiste)
_dispositivo_nome = None   # nome do dispositivo fixo (None -> padrão do Windows)

_lock = threading.Lock()   # protege o estado da reprodução via sounddevice
_thread = None             # thread da reprodução atual (one-shot ou loop)
_parar_evento = None       # threading.Event para interromper a reprodução atual
_BLOCO = 8192              # bytes por escrita no stream (~93 ms); permite parar rápido


def definir_dispositivo(nome: str | None) -> None:
    """Fixa a saída de áudio no dispositivo de nome `nome` (como aparece no
    painel de Som do Windows). Passe None ou "" para voltar ao dispositivo
    padrão do Windows (reprodução via winsound)."""
    global _dispositivo_nome
    _dispositivo_nome = (nome or None)


def _usar_dispositivo_fixo() -> bool:
    return _dispositivo_nome is not None


def _garantir_sounddevice() -> bool:
    """Garante o sounddevice importável, instalando-o sob demanda (escopo do
    usuário, sem exigir admin). Retorna True se puder ser usado. Pode BLOQUEAR
    na primeira vez (instalação via pip); chame de uma thread de fundo."""
    global _sd, _sd_indisponivel
    if _sd is not None:
        return True
    if _sd_indisponivel or winsound is None:  # fora do Windows fica só no winsound
        return False
    try:
        import sounddevice as sd
        _sd = sd
        return True
    except Exception:
        pass
    for args in (
        [sys.executable, "-m", "pip", "install", "--user", "--quiet",
         "--disable-pip-version-check", "sounddevice"],
        [sys.executable, "-m", "pip", "install", "--quiet",
         "--disable-pip-version-check", "sounddevice"],
    ):
        try:
            subprocess.run(
                args, check=True, creationflags=_CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            continue
        try:
            import site
            import importlib
            importlib.reload(site)
        except Exception:
            pass
        try:
            import sounddevice as sd
            _sd = sd
            return True
        except Exception:
            continue
    _sd_indisponivel = True
    return False


def garantir_async() -> None:
    """Prepara o sounddevice em segundo plano (para não travar a UI na primeira
    reprodução quando já há um dispositivo fixo salvo)."""
    threading.Thread(target=_garantir_sounddevice, daemon=True).start()


def _indice_wasapi() -> int | None:
    """Índice do host API WASAPI (o mesmo que o painel de Som usa)."""
    try:
        for i, h in enumerate(_sd.query_hostapis()):
            if "WASAPI" in h["name"].upper():
                return i
    except Exception:
        pass
    return None


def listar_dispositivos() -> list[str]:
    """Nomes dos dispositivos de saída (endpoints WASAPI), na mesma forma que
    aparecem no painel de Som do Windows › Reprodução. Lista vazia se o suporte
    não estiver disponível. Pode BLOQUEAR (instala/consulta) — chame de thread."""
    if not _garantir_sounddevice():
        return []
    try:
        wasapi = _indice_wasapi()
        nomes: list[str] = []
        for d in _sd.query_devices():
            if d["max_output_channels"] > 0 and (
                wasapi is None or d["hostapi"] == wasapi
            ):
                if d["name"] not in nomes:
                    nomes.append(d["name"])
        return nomes
    except Exception:
        return []


def _indice_dispositivo(nome: str) -> int | None:
    """Índice PortAudio do dispositivo de saída WASAPI com esse nome (ou None)."""
    try:
        wasapi = _indice_wasapi()
        for i, d in enumerate(_sd.query_devices()):
            if (
                d["name"] == nome
                and d["max_output_channels"] > 0
                and (wasapi is None or d["hostapi"] == wasapi)
            ):
                return i
    except Exception:
        pass
    return None


def _parar_reproducao() -> None:
    """Interrompe a reprodução em curso pelo backend de dispositivo fixo."""
    global _thread, _parar_evento
    with _lock:
        parar, thread = _parar_evento, _thread
        _parar_evento = _thread = None
    if parar is not None:
        parar.set()
    if thread is not None:
        thread.join(timeout=1.5)


def _reproduzir(frames: bytes, loop: bool) -> bool:
    """Toca `frames` (int16 mono) no dispositivo fixo, parando o que tocava
    antes (o backend só reproduz um som por vez, como o winsound). Retorna
    False se não houver como usar o dispositivo — aí o chamador cai no winsound
    (dispositivo padrão do Windows), para o som não se perder."""
    if not _garantir_sounddevice():
        return False
    idx = _indice_dispositivo(_dispositivo_nome)
    if idx is None:
        return False  # dispositivo fixado sumiu (desconectado): usa o padrão

    _parar_reproducao()
    parar = threading.Event()

    def _worker() -> None:
        try:
            extras = _sd.WasapiSettings(auto_convert=True)
        except Exception:
            extras = None
        stream = None
        for kwargs in ({"extra_settings": extras} if extras else {}, {}):
            try:
                stream = _sd.RawOutputStream(
                    samplerate=TAXA, channels=1, dtype="int16",
                    device=idx, **kwargs,
                )
                stream.start()
                break
            except Exception:
                stream = None
        if stream is None:
            return
        try:
            n = len(frames)
            while not parar.is_set():
                pos = 0
                while pos < n and not parar.is_set():
                    stream.write(frames[pos:pos + _BLOCO])
                    pos += _BLOCO
                if not loop:
                    break
        except Exception:
            pass
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    global _thread, _parar_evento
    with _lock:
        _parar_evento = parar
        _thread = threading.Thread(target=_worker, daemon=True)
        _thread.start()
    return True


# --------------------------------------------------------------------------- #
# Reprodução (assíncrona; não trava a contagem)
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
    if volume <= 0:
        return
    if _usar_dispositivo_fixo() and _reproduzir(_frames(nome, volume), loop=False):
        return
    _tocar_arquivo(nome, volume)


def tocar_tique(volume: int) -> None:
    """Bipe curto da contagem regressiva (últimos segundos)."""
    if volume <= 0:
        return
    if _usar_dispositivo_fixo() and _reproduzir(
        _frames("__tique__", volume), loop=False
    ):
        return
    _tocar_arquivo("__tique__", volume)


def tocar_ambiente(nome: str, volume: int) -> None:
    """Inicia um som ambiente em loop contínuo (até parar ou outro som tocar).

    Observação: só se reproduz um som por vez — qualquer alerta tocado depois
    substitui o loop. Quem chama deve reiniciar o ambiente se quiser retomá-lo."""
    if volume <= 0 or nome not in AMBIENTES:
        return
    if _usar_dispositivo_fixo() and _reproduzir(
        _frames(nome, volume, ambiente=True), loop=True
    ):
        return
    if winsound is None:
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
    _parar_reproducao()  # backend de dispositivo fixo
    if winsound is None:
        return
    try:
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
